"""Recherche d'annonces via l'API officielle France Travail (ex Pôle Emploi).

Doc : https://francetravail.io/produits-partages/catalogue/offres-emploi/documentation
Auth : OAuth 2.0 client credentials (scope `api_offresdemploiv2 o2dsoffre`)

Credentials attendus dans des variables d'environnement (chargées depuis
`~/.agent-recherche/credentials.env` si python-dotenv est installé) :
- FT_CLIENT_ID
- FT_CLIENT_SECRET
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv
    _ENV_PATH = Path.home() / ".agent-recherche" / "credentials.env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except ImportError:
    # dotenv est optionnel ; on lit seulement os.environ
    pass

try:
    from load_criteres import Criteres, load_criteres
    from store_results import AnnonceCollectee
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from load_criteres import Criteres, load_criteres  # type: ignore
    from store_results import AnnonceCollectee  # type: ignore


TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

# La doc impose un délai entre appels (rate limit). On reste très conservateur.
RATE_LIMIT_SLEEP_SEC = 1.5


class FranceTravailError(RuntimeError):
    pass


def _get_token() -> str:
    client_id = os.getenv("FT_CLIENT_ID")
    client_secret = os.getenv("FT_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise FranceTravailError(
            "FT_CLIENT_ID / FT_CLIENT_SECRET manquants. Voir references/credentials.md."
        )

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "api_offresdemploiv2 o2dsoffre",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise FranceTravailError(
            f"Échec d'authentification ({resp.status_code}): {resp.text[:200]}"
        )
    return resp.json()["access_token"]


def _construire_mots_cles(criteres: Criteres) -> str:
    """Concatène les mots-clés obligatoires + souhaitables (espace = OR pour FT)."""
    termes = [m.mot_cle for m in criteres.obligatoires() + criteres.souhaitables()]
    # FT n'accepte qu'une chaîne libre (max ~250 chars). On priorise les obligatoires.
    return " ".join(termes)[:240]


def _construire_params(criteres: Criteres, *, range_start: int = 0, range_end: int = 49) -> dict[str, Any]:
    """Construit les query params de l'API à partir des critères utilisateur."""
    params: dict[str, Any] = {
        "motsCles": _construire_mots_cles(criteres),
        "range": f"{range_start}-{range_end}",
    }

    # Type de contrat (CDI -> code "CDI" dans FT) — lu depuis Profil_Poste
    contrat_critere = criteres.critere_par_nom("contrat_accepte")
    if contrat_critere and isinstance(contrat_critere.valeur, list):
        contrats = [str(c).upper() for c in contrat_critere.valeur if c]
        if contrats:
            params["typeContrat"] = ",".join(contrats)

    # Première localisation active = filtre principal
    locs_actives = [l for l in criteres.localisations if l.actif and l.ville]
    if locs_actives:
        # FT attend un code commune INSEE pour le filtre précis ;
        # à défaut, on passe la ville en mots-clés et on filtre côté matcher.
        # On ne met pas de filtre géographique strict ici pour ne pas perdre
        # des annonces "Full remote" — le matcher tranchera.
        pass

    return params


def _annonce_de_offre(offre: dict[str, Any]) -> AnnonceCollectee:
    """Mappe une offre FT au format interne AnnonceCollectee."""
    url = (
        offre.get("origineOffre", {}).get("urlOrigine")
        or f"https://candidat.francetravail.fr/offres/recherche/detail/{offre.get('id', '')}"
    )
    description = offre.get("description", "") or ""
    # France Travail expose `dateCreation` (ISO 8601 avec timezone).
    # On ne garde que AAAA-MM-JJ pour `date_publication`.
    date_creation = offre.get("dateCreation") or offre.get("dateActualisation")
    date_publication = str(date_creation)[:10] if date_creation else None

    return AnnonceCollectee(
        url=url,
        source="France Travail",
        titre=offre.get("intitule"),
        entreprise=(offre.get("entreprise") or {}).get("nom"),
        localisation=(offre.get("lieuTravail") or {}).get("libelle"),
        contrat=offre.get("typeContratLibelle") or offre.get("typeContrat"),
        salaire_brut=(offre.get("salaire") or {}).get("libelle"),
        extrait=description[:500],
        date_publication=date_publication,
    )


def rechercher(criteres: Criteres, *, max_pages: int = 4, page_size: int = 50) -> list[AnnonceCollectee]:
    """Pagine sur l'API et retourne la liste brute des annonces.

    Le matching est effectué dans un script appelant ; ici on ne fait que collecter.
    """
    token = _get_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    out: list[AnnonceCollectee] = []

    for page in range(max_pages):
        start = page * page_size
        end = start + page_size - 1
        params = _construire_params(criteres, range_start=start, range_end=end)

        resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=20)
        if resp.status_code in (200, 206):
            data = resp.json()
            offres = data.get("resultats", [])
            out.extend(_annonce_de_offre(o) for o in offres)
            if len(offres) < page_size:
                break  # plus rien à paginer
        elif resp.status_code == 204:
            break  # aucun résultat
        else:
            raise FranceTravailError(
                f"Recherche FT échouée ({resp.status_code}): {resp.text[:200]}"
            )

        time.sleep(RATE_LIMIT_SLEEP_SEC)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--criteres", type=Path, default=Path("criteres.xlsx"))
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--out", type=Path, help="Optionnel : écrire le résultat brut en JSON")
    args = parser.parse_args()

    criteres = load_criteres(args.criteres)
    try:
        annonces = rechercher(criteres, max_pages=args.max_pages)
    except FranceTravailError as err:
        print(f"[ERREUR] {err}", file=sys.stderr)
        return 1

    print(f"[OK] {len(annonces)} annonces collectées sur France Travail.")
    if args.out:
        args.out.write_text(
            json.dumps([a.__dict__ for a in annonces], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"     → écrit dans {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
