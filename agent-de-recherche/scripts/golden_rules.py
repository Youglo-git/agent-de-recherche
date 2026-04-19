"""Golden Rules — invariants appliqués à toute annonce avant persistance.

Trois règles transverses, indépendantes des critères utilisateur :

1. **Annonce active** : la page de détail doit répondre en HTTP 2xx ou 3xx.
   Les 404/410/451 sont écartés. Un 401/403 (site exigeant un login,
   typiquement LinkedIn) est considéré comme *statut indéterminé* et on
   conserve l'annonce plutôt que de la jeter à tort.

2. **Annonce récente** : `date_publication` doit être à moins de `AGE_MAX_JOURS`.
   Si la date n'est pas connue (certains sites ne l'exposent pas), on conserve
   l'annonce — on ne peut pas la dater, on ne la pénalise pas.

3. **Salaire non bloquant** : géré à l'amont par le fait que le critère
   `salaire_annuel_brut_min_eur` est `souhaitable` dans le template (pas
   `obligatoire`). Ce module se contente de poser le flag `salaire_absent` sur
   les annonces dont aucun salaire n'a pu être détecté — utile pour le scoring
   et le rapport.

Le résultat est une liste d'annonces enrichies, avec les champs :
- `url_active`              : 1 / 0 / None (indéterminé)
- `derniere_verification_le`: ISO 8601 UTC
- `date_publication`        : ISO 8601 (AAAA-MM-JJ) — inchangé si déjà renseigné
- `salaire_absent`          : 1 si aucune info salaire, 0 sinon

Les annonces écartées par les Golden Rules ne sont pas stockées — on les
retourne séparément pour que l'appelant puisse logger.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests

try:
    from store_results import AnnonceCollectee
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).parent))
    from store_results import AnnonceCollectee  # type: ignore


# ─── Paramétrage ──────────────────────────────────────────────────────────────

AGE_MAX_JOURS: int = 180  # Golden Rule #2 : 6 mois = 180 jours
"""Seuil de fraîcheur. Au-delà, l'annonce est écartée."""

CODES_VIVANTS: frozenset[int] = frozenset(range(200, 400))
"""HTTP 2xx et 3xx → page considérée comme accessible."""

CODES_MORTS: frozenset[int] = frozenset({404, 410, 451})
"""HTTP explicitement 'ressource absente/disparue' → on écarte."""

# Tout le reste (401, 403, 429, 5xx, timeout…) = indéterminé → on conserve.

TIMEOUT_SEC: float = 10.0
MAX_PARALLELE: int = 8
USER_AGENT = "agent-recherche-emploi/1.0 (+local, veille emploi personnelle)"


# ─── Résultats ───────────────────────────────────────────────────────────────

@dataclass
class RapportGoldenRules:
    """Bilan de l'application des règles, pour restitution utilisateur."""
    nb_entree: int = 0
    nb_sorties_trop_anciennes: int = 0
    nb_sorties_lien_mort: int = 0
    nb_conservees: int = 0
    details_ecartees: list[dict] = field(default_factory=list)

    def resume(self) -> str:
        return (
            f"Golden Rules : {self.nb_entree} en entrée → "
            f"{self.nb_conservees} conservées, "
            f"{self.nb_sorties_trop_anciennes} trop anciennes (>{AGE_MAX_JOURS}j), "
            f"{self.nb_sorties_lien_mort} liens morts."
        )


# ─── Règle #2 : fraîcheur ────────────────────────────────────────────────────

def _parser_date(value: str | None) -> datetime | None:
    """Parse une date ISO robuste aux variantes courantes (Z, +00:00, sans heure)."""
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Normaliser le 'Z' terminal (timezone UTC)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Format YYYY-MM-DD seul
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _est_trop_ancienne(annonce: AnnonceCollectee, *, maintenant: datetime) -> bool:
    """True si l'annonce est plus vieille que AGE_MAX_JOURS.

    Conservatif : si la date n'est pas connue, on retourne False (on garde).
    """
    date_pub = _parser_date(annonce.date_publication)
    if date_pub is None:
        return False
    # Forcer UTC si naïve pour la comparaison
    if date_pub.tzinfo is None:
        date_pub = date_pub.replace(tzinfo=timezone.utc)
    return (maintenant - date_pub) > timedelta(days=AGE_MAX_JOURS)


# ─── Règle #1 : URL active ───────────────────────────────────────────────────

def _verifier_url(url: str, *, session: requests.Session) -> tuple[int | None, str]:
    """Retourne (code_http, statut).

    statut ∈ {'vivant', 'mort', 'indetermine'}
    code_http = None en cas d'exception réseau/timeout.
    """
    if not url:
        return None, "indetermine"

    headers = {"User-Agent": USER_AGENT}
    # 1) HEAD d'abord — léger et autorisé par la plupart des sites
    try:
        resp = session.head(url, headers=headers, timeout=TIMEOUT_SEC, allow_redirects=True)
    except requests.RequestException:
        resp = None

    # Certains serveurs refusent HEAD (405) ou le traitent mal → tenter GET
    if resp is None or resp.status_code in (405, 501) or resp.status_code >= 400:
        try:
            resp = session.get(
                url, headers=headers, timeout=TIMEOUT_SEC, allow_redirects=True, stream=True
            )
            # On n'a pas besoin du body, on ferme tout de suite
            resp.close()
        except requests.RequestException:
            return None, "indetermine"

    code = resp.status_code
    if code in CODES_MORTS:
        return code, "mort"
    if code in CODES_VIVANTS:
        return code, "vivant"
    return code, "indetermine"


# ─── Règle #3 : salaire absent (marquage seulement) ──────────────────────────

def _salaire_absent(annonce: AnnonceCollectee) -> bool:
    """True si aucune info salaire n'est détectable dans l'annonce collectée."""
    sal = (annonce.salaire_brut or "").strip()
    if not sal:
        return True
    # Un champ 'salaire_brut' sans aucun chiffre = texte vide de sens (ex: "À négocier")
    if not any(c.isdigit() for c in sal):
        return True
    return False


# ─── Orchestration ───────────────────────────────────────────────────────────

def appliquer(
    annonces: Iterable[AnnonceCollectee],
    *,
    verifier_reseau: bool = True,
) -> tuple[list[AnnonceCollectee], RapportGoldenRules]:
    """Applique les trois Golden Rules à la liste d'annonces.

    Args:
        annonces: itérable d'AnnonceCollectee issues des scripts de collecte.
        verifier_reseau: si False, on saute la vérif HTTP (utile pour les tests
            unitaires hors-ligne). Les champs `url_active` et
            `derniere_verification_le` restent alors à None.

    Returns:
        (conservees, rapport)
    """
    annonces = list(annonces)
    rapport = RapportGoldenRules(nb_entree=len(annonces))
    maintenant = datetime.now(timezone.utc)

    # Étape 1 : filtrage sur date de publication (local, rapide)
    survivantes: list[AnnonceCollectee] = []
    for ann in annonces:
        if _est_trop_ancienne(ann, maintenant=maintenant):
            rapport.nb_sorties_trop_anciennes += 1
            rapport.details_ecartees.append({
                "url": ann.url,
                "raison": f"date_publication > {AGE_MAX_JOURS}j",
                "date_publication": ann.date_publication,
            })
            continue
        # Marquer salaire_absent AVANT la vérif réseau (peu coûteux, toujours utile)
        ann.salaire_absent = _salaire_absent(ann)
        survivantes.append(ann)

    # Étape 2 : vérification HTTP en parallèle
    if verifier_reseau and survivantes:
        with requests.Session() as session, ThreadPoolExecutor(max_workers=MAX_PARALLELE) as pool:
            futures = {pool.submit(_verifier_url, a.url, session=session): a for a in survivantes}
            for fut in as_completed(futures):
                ann = futures[fut]
                code, statut = fut.result()
                ann.derniere_verification_le = maintenant.isoformat(timespec="seconds")
                if statut == "mort":
                    ann.url_active = 0
                elif statut == "vivant":
                    ann.url_active = 1
                else:
                    ann.url_active = None  # indéterminé → on conserve

    # Étape 3 : retirer les liens morts
    conservees = []
    for ann in survivantes:
        if ann.url_active == 0:
            rapport.nb_sorties_lien_mort += 1
            rapport.details_ecartees.append({
                "url": ann.url,
                "raison": "lien mort (HTTP 404/410/451)",
            })
            continue
        conservees.append(ann)

    rapport.nb_conservees = len(conservees)
    return conservees, rapport


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Fichier JSON : liste d'AnnonceCollectee (même format que store_results.py)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Optionnel : écrire les annonces conservées en JSON",
    )
    parser.add_argument(
        "--no-reseau",
        action="store_true",
        help="Sauter la vérification HTTP (utile hors ligne, pour tests)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[ERREUR] {args.input} introuvable", file=sys.stderr)
        return 1

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    annonces = [AnnonceCollectee(**item) for item in raw]
    conservees, rapport = appliquer(annonces, verifier_reseau=not args.no_reseau)

    print(rapport.resume())
    if rapport.details_ecartees:
        print("Détail des annonces écartées :")
        for d in rapport.details_ecartees:
            print(f"  - {d['raison']} → {d['url']}")

    if args.out:
        args.out.write_text(
            json.dumps([a.__dict__ for a in conservees], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[OK] {len(conservees)} annonces conservées → {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
