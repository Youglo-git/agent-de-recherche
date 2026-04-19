"""Recherche d'annonces via l'API Adzuna.

Doc : https://developer.adzuna.com/docs/search
Adzuna agrège plusieurs sources (dont Indeed) ; c'est un bon complément gratuit.

Credentials attendus (variables d'env, chargeables depuis
`~/.agent-recherche/credentials.env`) :
- ADZUNA_APP_ID
- ADZUNA_APP_KEY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv
    _ENV_PATH = Path.home() / ".agent-recherche" / "credentials.env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except ImportError:
    pass

try:
    from load_criteres import Criteres, load_criteres
    from store_results import AnnonceCollectee
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent))
    from load_criteres import Criteres, load_criteres  # type: ignore
    from store_results import AnnonceCollectee  # type: ignore


API_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
DEFAULT_COUNTRY = "fr"
RATE_LIMIT_SLEEP_SEC = 1.0


class AdzunaError(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise AdzunaError(
            "ADZUNA_APP_ID / ADZUNA_APP_KEY manquants. Voir references/credentials.md."
        )
    return app_id, app_key


def _what_query(criteres: Criteres) -> str:
    """Adzuna: 'what' = recherche mots-clés libres, espace = AND."""
    # Prio aux obligatoires, sinon on trop restrictif dès la requête.
    termes = [m.mot_cle for m in criteres.obligatoires()]
    return " ".join(termes)[:200]


def _where_query(criteres: Criteres) -> str:
    """Adzuna: 'where' = localisation texte libre. On prend la première ville active."""
    for loc in criteres.localisations:
        if loc.actif and loc.ville and loc.ville.lower() not in {"full remote", "remote", "télétravail"}:
            return loc.ville
    return ""


def _annonce_de_result(r: dict[str, Any]) -> AnnonceCollectee:
    # Adzuna expose `created` au format ISO 8601 (ex: "2026-03-12T14:22:00Z")
    # → on ne garde que la partie date (AAAA-MM-JJ) pour `date_publication`.
    created = r.get("created")
    date_publication = str(created)[:10] if created else None

    return AnnonceCollectee(
        url=r.get("redirect_url") or r.get("adref") or "",
        source="Adzuna",
        titre=r.get("title"),
        entreprise=(r.get("company") or {}).get("display_name"),
        localisation=(r.get("location") or {}).get("display_name"),
        contrat=r.get("contract_type"),
        salaire_brut=(
            f"{r['salary_min']}-{r['salary_max']} {r.get('salary_is_predicted','')}".strip()
            if r.get("salary_min") and r.get("salary_max")
            else None
        ),
        extrait=(r.get("description") or "")[:500],
        date_publication=date_publication,
    )


def rechercher(
    criteres: Criteres,
    *,
    country: str = DEFAULT_COUNTRY,
    max_pages: int = 5,
    results_per_page: int = 50,
) -> list[AnnonceCollectee]:
    app_id, app_key = _credentials()
    what = _what_query(criteres)
    where = _where_query(criteres)

    # Salaire min : lu depuis la feuille Profil_Poste si défini
    salaire_critere = criteres.critere_par_nom("salaire_annuel_brut_min_eur")
    salaire_min = (
        int(salaire_critere.valeur)
        if salaire_critere and isinstance(salaire_critere.valeur, (int, float))
        else None
    )

    out: list[AnnonceCollectee] = []
    for page in range(1, max_pages + 1):
        params: dict[str, Any] = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": results_per_page,
            "content-type": "application/json",
            "what": what,
        }
        if where:
            params["where"] = where
        if salaire_min:
            params["salary_min"] = salaire_min

        resp = requests.get(
            API_URL.format(country=country, page=page),
            params=params,
            timeout=20,
        )
        if resp.status_code != 200:
            raise AdzunaError(
                f"Recherche Adzuna échouée ({resp.status_code}): {resp.text[:200]}"
            )

        data = resp.json()
        results = data.get("results", [])
        out.extend(_annonce_de_result(r) for r in results)
        if len(results) < results_per_page:
            break

        time.sleep(RATE_LIMIT_SLEEP_SEC)

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--criteres", type=Path, default=Path("criteres.xlsx"))
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--country", default=DEFAULT_COUNTRY)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    criteres = load_criteres(args.criteres)
    try:
        annonces = rechercher(criteres, country=args.country, max_pages=args.max_pages)
    except AdzunaError as err:
        print(f"[ERREUR] {err}", file=sys.stderr)
        return 1

    print(f"[OK] {len(annonces)} annonces collectées sur Adzuna.")
    if args.out:
        args.out.write_text(
            json.dumps([a.__dict__ for a in annonces], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
