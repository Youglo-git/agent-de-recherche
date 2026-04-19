"""Orchestrateur de la phase collecte + Golden Rules + persistance.

Enchaîne dans l'ordre :
  1. `init_db.py` — schéma idempotent (ajoute colonnes Golden Rules si absent)
  2. Appels aux modules `search_*.py` (Adzuna, France Travail) pour collecter
  3. `golden_rules.appliquer()` — filtrage 3 règles transverses
  4. `store_results.stocker()` — persistance en DB

Les sources LinkedIn / APEC / WTTJ / HelloWork (scraping via Chrome MCP)
restent orchestrées côté Cowork (l'agent Claude pilote le navigateur puis
appelle ce script avec le résultat en JSON via `--extra-json`).

Usage :
    python run_collecte.py --criteres criteres.xlsx
                           --db-path ~/.agent-recherche/annonces.db
                           --credentials ~/.agent-recherche/credentials.env
                           [--sources adzuna,france_travail]
                           [--extra-json browser_annonces.json]
                           [--no-reseau]

Codes retour : 0 succès complet, 1 erreur fatale (schéma, credentials, I/O).
Les échecs par source (timeout API, credentials manquants) sont loggés
mais n'interrompent pas le pipeline — on continue avec les autres sources.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Permet l'import des modules frères même hors package
sys.path.insert(0, str(Path(__file__).parent))

import init_db  # noqa: E402
import golden_rules  # noqa: E402
import store_results  # noqa: E402
from load_criteres import load_criteres  # noqa: E402


# ─── Chargement credentials (équivalent de python-dotenv minimal) ────────────

def _charger_credentials(path: Path) -> None:
    """Charge les paires KEY=VALUE du fichier dans os.environ (sans écraser)."""
    if not path.exists():
        print(f"[WARN] Fichier credentials introuvable : {path}", file=sys.stderr)
        return
    for ligne in path.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, val = ligne.split("=", 1)
        cle = cle.strip()
        val = val.strip().strip('"').strip("'")
        if cle and cle not in os.environ:
            os.environ[cle] = val


# ─── Sources API ─────────────────────────────────────────────────────────────

def _collecter_adzuna(criteres) -> list:
    try:
        import search_adzuna  # import tardif : besoin des variables d'env
    except ImportError as e:
        print(f"[SKIP] Adzuna : module introuvable ({e})", file=sys.stderr)
        return []
    if not os.environ.get("ADZUNA_APP_ID") or not os.environ.get("ADZUNA_APP_KEY"):
        print("[SKIP] Adzuna : credentials absents", file=sys.stderr)
        return []
    try:
        annonces = search_adzuna.rechercher(criteres)
        print(f"[OK] Adzuna : {len(annonces)} annonces collectées")
        return annonces
    except Exception as e:  # search_adzuna.AdzunaError + network errors
        print(f"[WARN] Adzuna a échoué : {e}", file=sys.stderr)
        return []


def _collecter_france_travail(criteres) -> list:
    try:
        import search_france_travail
    except ImportError as e:
        print(f"[SKIP] France Travail : module introuvable ({e})", file=sys.stderr)
        return []
    if not os.environ.get("FT_CLIENT_ID") or not os.environ.get("FT_CLIENT_SECRET"):
        print("[SKIP] France Travail : credentials absents", file=sys.stderr)
        return []
    try:
        annonces = search_france_travail.rechercher(criteres)
        print(f"[OK] France Travail : {len(annonces)} annonces collectées")
        return annonces
    except Exception as e:
        print(f"[WARN] France Travail a échoué : {e}", file=sys.stderr)
        return []


def _charger_extra_json(path: Path) -> list:
    """Charge des annonces fournies par un collecteur externe (ex: Chrome MCP)."""
    if not path.exists():
        print(f"[SKIP] Extra JSON : {path} introuvable", file=sys.stderr)
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    annonces = [store_results.AnnonceCollectee(**item) for item in raw]
    print(f"[OK] Extra JSON ({path.name}) : {len(annonces)} annonces")
    return annonces


# ─── Orchestration principale ────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--criteres", type=Path, required=True)
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path.home() / ".agent-recherche" / "annonces.db",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path.home() / ".agent-recherche" / "credentials.env",
    )
    parser.add_argument(
        "--sources",
        default="adzuna,france_travail",
        help="Liste séparée par virgule des sources API à interroger",
    )
    parser.add_argument(
        "--extra-json",
        type=Path,
        default=None,
        help="JSON additionnel (annonces collectées par Chrome MCP par ex.)",
    )
    parser.add_argument(
        "--no-reseau",
        action="store_true",
        help="Sauter la vérification HTTP des Golden Rules (tests hors ligne)",
    )
    args = parser.parse_args()

    # 1. Préparer la DB (idempotent, ajoute colonnes Golden Rules si besoin)
    init_db.init_db(args.db_path)
    print(f"[OK] DB prête : {args.db_path}")

    # 2. Charger credentials + critères
    _charger_credentials(args.credentials)
    try:
        criteres = load_criteres(args.criteres)
    except Exception as e:
        print(f"[ERREUR] Impossible de charger les critères : {e}", file=sys.stderr)
        return 1

    # 3. Collecte multi-sources (indépendantes, échec isolé)
    sources = {s.strip().lower() for s in args.sources.split(",") if s.strip()}
    annonces_brutes: list = []
    if "adzuna" in sources:
        annonces_brutes += _collecter_adzuna(criteres)
    if "france_travail" in sources:
        annonces_brutes += _collecter_france_travail(criteres)
    if args.extra_json:
        annonces_brutes += _charger_extra_json(args.extra_json)

    if not annonces_brutes:
        print("[WARN] Aucune annonce collectée — rien à persister.", file=sys.stderr)
        return 0

    # 4. Golden Rules : filtrage transverse
    conservees, rapport = golden_rules.appliquer(
        annonces_brutes, verifier_reseau=not args.no_reseau
    )
    print(rapport.resume())

    # 5. Persistance en DB
    stats = store_results.stocker(args.db_path, conservees)
    print(
        f"[OK] Persistance : Vues={stats.nb_vues}  "
        f"Insérées={stats.nb_inserees}  Revues={stats.nb_revues}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
