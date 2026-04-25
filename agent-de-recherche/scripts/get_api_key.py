"""Récupération d'une clé API Anthropic via l'Admin API.

Endpoint : GET https://api.anthropic.com/v1/organizations/api_keys/{api_key_id}

Credentials attendus (variables d'env, chargeables depuis
`~/.agent-recherche/credentials.env`) :
- ANTHROPIC_ADMIN_API_KEY  : clé admin de l'organisation Anthropic
- ANTHROPIC_API_KEY_ID     : identifiant de la clé API à consulter
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    _ENV_PATH = Path.home() / ".agent-recherche" / "credentials.env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except ImportError:
    pass


API_URL = "https://api.anthropic.com/v1/organizations/api_keys/{api_key_id}"
ANTHROPIC_VERSION = "2023-06-01"


class AdminApiError(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    admin_key = os.getenv("ANTHROPIC_ADMIN_API_KEY")
    api_key_id = os.getenv("ANTHROPIC_API_KEY_ID")
    if not admin_key:
        raise AdminApiError(
            "ANTHROPIC_ADMIN_API_KEY manquant. Voir references/credentials.md."
        )
    if not api_key_id:
        raise AdminApiError(
            "ANTHROPIC_API_KEY_ID manquant. Voir references/credentials.md."
        )
    return admin_key, api_key_id


def get_api_key(api_key_id: str | None = None, admin_key: str | None = None) -> dict:
    """Récupère les informations d'une clé API Anthropic.

    Si api_key_id ou admin_key ne sont pas fournis, ils sont lus depuis les
    variables d'environnement ANTHROPIC_API_KEY_ID et ANTHROPIC_ADMIN_API_KEY.
    """
    if not admin_key or not api_key_id:
        _admin_key, _api_key_id = _credentials()
        admin_key = admin_key or _admin_key
        api_key_id = api_key_id or _api_key_id

    resp = requests.get(
        API_URL.format(api_key_id=api_key_id),
        headers={
            "anthropic-version": ANTHROPIC_VERSION,
            "X-Api-Key": admin_key,
        },
        timeout=20,
    )

    if resp.status_code != 200:
        raise AdminApiError(
            f"Récupération clé API échouée ({resp.status_code}): {resp.text[:400]}"
        )

    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-key-id",
        default=None,
        help="Identifiant de la clé API (défaut: $ANTHROPIC_API_KEY_ID)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Fichier de sortie JSON (optionnel, sinon stdout)",
    )
    args = parser.parse_args()

    try:
        data = get_api_key(api_key_id=args.api_key_id)
    except AdminApiError as err:
        print(f"[ERREUR] {err}", file=sys.stderr)
        return 1

    output = json.dumps(data, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"[OK] Clé API '{data.get('id')}' écrite dans {args.out}.")
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
