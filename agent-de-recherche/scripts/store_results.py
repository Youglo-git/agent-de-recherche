"""Persiste les annonces dans annonces.db, avec déduplication par hash d'URL canonique.

Une URL canonique = URL nettoyée des paramètres de tracking (utm_*, fbclid, etc.)
et de fragment, pour qu'une même annonce vue 3 fois (LinkedIn vs newsletter vs
notification) ne crée qu'une seule ligne en base.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


# Paramètres de tracking à supprimer pour canonicaliser une URL
TRACKING_PARAMS_PREFIXES = ("utm_",)
TRACKING_PARAMS_EXACTS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "refId", "trackingId",
    "ssrc", "lipi", "trk", "trkInfo", "src",
}


@dataclass
class AnnonceCollectee:
    """Annonce telle que retournée par un script de collecte (avant insertion)."""
    url: str
    source: str
    titre: str | None = None
    entreprise: str | None = None
    localisation: str | None = None
    contrat: str | None = None
    salaire_brut: str | None = None
    extrait: str | None = None
    criteres_matches: list[str] | None = None
    criteres_manquants: list[str] | None = None
    match_global: bool = False
    # ─── Golden Rules (cf. scripts/golden_rules.py) ─────────────────────────
    date_publication: str | None = None          # ISO 8601 (AAAA-MM-JJ) si connue
    url_active: int | None = None                # 1 / 0 / None (indéterminé)
    derniere_verification_le: str | None = None  # ISO 8601 UTC, dernière vérif HTTP
    salaire_absent: bool = False                 # True si aucun salaire détecté


def url_canonique(url: str) -> str:
    """Retourne une version normalisée de l'URL (sans paramètres tracking ni fragment).

    On garde le scheme, le netloc, le path, et les query string non-tracking, triés.
    """
    parsed = urlparse(url.strip())
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k not in TRACKING_PARAMS_EXACTS
        and not any(k.startswith(prefix) for prefix in TRACKING_PARAMS_PREFIXES)
    ]
    query_pairs.sort()  # déterministe
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
        "",  # params (rarement utilisé)
        urlencode(query_pairs),
        "",  # fragment
    ))


def url_hash(url_can: str) -> str:
    """Hash SHA-256 hex (64 chars) de l'URL canonique."""
    return hashlib.sha256(url_can.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class StoreStats:
    nb_vues: int = 0
    nb_inserees: int = 0
    nb_revues: int = 0  # déjà connues, derniere_vue_le mise à jour


def stocker(
    db_path: Path,
    annonces: list[AnnonceCollectee],
    *,
    execution_id: int | None = None,
) -> StoreStats:
    """Insère ou met à jour les annonces. Retourne les stats de persistance.

    L'opération est transactionnelle : si une erreur survient, rien n'est
    committé, pour ne pas laisser la base dans un état incohérent.
    """
    stats = StoreStats(nb_vues=len(annonces))
    if not annonces:
        return stats

    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        cur = conn.cursor()
        try:
            for ann in annonces:
                u_can = url_canonique(ann.url)
                u_hash = url_hash(u_can)

                cur.execute("SELECT id FROM annonces WHERE url_hash = ?", (u_hash,))
                existing = cur.fetchone()

                if existing:
                    annonce_id = existing[0]
                    # MAJ derniere_vue_le systématique, et champs Golden Rules
                    # s'ils ont été (re)calculés sur cette passe.
                    cur.execute(
                        """
                        UPDATE annonces
                           SET derniere_vue_le          = ?,
                               url_active               = COALESCE(?, url_active),
                               derniere_verification_le = COALESCE(?, derniere_verification_le),
                               date_publication         = COALESCE(?, date_publication),
                               salaire_absent           = ?
                         WHERE id = ?
                        """,
                        (
                            now,
                            ann.url_active,
                            ann.derniere_verification_le,
                            ann.date_publication,
                            1 if ann.salaire_absent else 0,
                            annonce_id,
                        ),
                    )
                    stats.nb_revues += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO annonces (
                            url, url_canonique, url_hash, source,
                            titre, entreprise, localisation, contrat, salaire_brut,
                            salaire_absent, extrait, criteres_matches, criteres_manquants,
                            match_global, date_publication, url_active,
                            derniere_verification_le, collectee_le, derniere_vue_le
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ann.url,
                            u_can,
                            u_hash,
                            ann.source,
                            ann.titre,
                            ann.entreprise,
                            ann.localisation,
                            ann.contrat,
                            ann.salaire_brut,
                            1 if ann.salaire_absent else 0,
                            ann.extrait,
                            json.dumps(ann.criteres_matches or [], ensure_ascii=False),
                            json.dumps(ann.criteres_manquants or [], ensure_ascii=False),
                            1 if ann.match_global else 0,
                            ann.date_publication,
                            ann.url_active,
                            ann.derniere_verification_le,
                            now,
                            now,
                        ),
                    )
                    annonce_id = cur.lastrowid
                    stats.nb_inserees += 1

                if execution_id is not None and annonce_id is not None:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO annonces_executions (annonce_id, execution_id)
                        VALUES (?, ?)
                        """,
                        (annonce_id, execution_id),
                    )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise

    return stats


def demarrer_execution(db_path: Path, sources_actives: list[str]) -> int:
    """Crée une ligne dans `executions` et retourne son id."""
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO executions (debut_le, sources_actives, statut)
            VALUES (?, ?, 'en_cours')
            """,
            (_now_iso(), json.dumps(sources_actives, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)


def cloturer_execution(
    db_path: Path,
    execution_id: int,
    *,
    stats: StoreStats,
    statut: str = "terminee",
    erreur: str | None = None,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE executions
               SET fin_le = ?, nb_vues = ?, nb_matches = ?, nb_nouvelles = ?,
                   statut = ?, erreur = ?
             WHERE id = ?
            """,
            (
                _now_iso(),
                stats.nb_vues,
                stats.nb_inserees + stats.nb_revues,  # toutes les annonces match=true persistées
                stats.nb_inserees,
                statut,
                erreur,
                execution_id,
            ),
        )
        conn.commit()


DEFAULT_DB_PATH = Path.home() / ".agent-recherche" / "annonces.db"


def main() -> int:
    """CLI utilitaire — utile pour ingérer un JSON externe (debug ou import manuel)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Fichier JSON liste d'annonces (format AnnonceCollectee)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"[ERREUR] {args.input} introuvable", file=sys.stderr)
        return 1

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    annonces = [AnnonceCollectee(**item) for item in raw]
    stats = stocker(args.db, annonces)
    print(
        f"[OK] Vues={stats.nb_vues}  Insérées={stats.nb_inserees}  "
        f"Revues (déjà connues)={stats.nb_revues}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
