"""Initialise la base SQLite annonces.db avec le schéma de l'agent de recherche.

Idempotent : `CREATE TABLE IF NOT EXISTS` n'écrase pas les données existantes.
Les index sont également créés en `IF NOT EXISTS`.

Schéma :
- annonces           : une ligne par offre unique (dédup sur url_hash)
- executions         : journal des passes de recherche (audit + suivi)
- annonces_executions : lien N-N (quelle annonce a été vue à quelle exécution)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
-- Note: on n'active pas le mode WAL pour rester compatible avec les
-- filesystems montés (Drive, OneDrive, FUSE, etc.). Le mode rollback par
-- défaut est largement suffisant pour un usage mono-utilisateur.

CREATE TABLE IF NOT EXISTS annonces (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    url                      TEXT NOT NULL,
    url_canonique            TEXT NOT NULL,
    url_hash                 TEXT NOT NULL UNIQUE,         -- SHA-256 de url_canonique
    source                   TEXT NOT NULL,                -- 'France Travail', 'LinkedIn', ...
    titre                    TEXT,
    entreprise               TEXT,
    localisation             TEXT,
    contrat                  TEXT,
    salaire_brut             TEXT,                         -- chaîne brute, normalisation faite plus tard
    salaire_absent           INTEGER NOT NULL DEFAULT 0,   -- Golden Rule #3 : 1 si aucun salaire détecté
    extrait                  TEXT,                         -- 200-500 premiers caractères
    criteres_matches         TEXT,                         -- JSON : ["Prince2","CDI",...]
    criteres_manquants       TEXT,                         -- JSON : ["obligatoire absent",...]
    match_global             INTEGER NOT NULL DEFAULT 0,   -- 0=écartée, 1=retenue
    date_publication         TEXT,                         -- Golden Rule #2 : ISO 8601 (AAAA-MM-JJ) si connue
    url_active               INTEGER,                      -- Golden Rule #1 : 1=page existe, 0=lien mort, NULL=non vérifié
    derniere_verification_le TEXT,                         -- ISO 8601 UTC, dernière vérif HTTP réussie
    collectee_le             TEXT NOT NULL,                -- ISO 8601 UTC
    derniere_vue_le          TEXT NOT NULL                 -- ISO 8601 UTC, MAJ à chaque revue
);

CREATE INDEX IF NOT EXISTS idx_annonces_source     ON annonces(source);
CREATE INDEX IF NOT EXISTS idx_annonces_match      ON annonces(match_global);
CREATE INDEX IF NOT EXISTS idx_annonces_collectee  ON annonces(collectee_le);
-- Les index sur les colonnes Golden Rules (date_publication, url_active) sont
-- créés dans _migrer_golden_rules, après l'ajout des colonnes — obligatoire
-- pour les bases pré-v1 qui ne les ont pas encore.

CREATE TABLE IF NOT EXISTS executions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    debut_le        TEXT NOT NULL,
    fin_le          TEXT,
    sources_actives TEXT NOT NULL,                     -- JSON liste
    nb_vues         INTEGER NOT NULL DEFAULT 0,
    nb_matches      INTEGER NOT NULL DEFAULT 0,
    nb_nouvelles    INTEGER NOT NULL DEFAULT 0,
    statut          TEXT NOT NULL DEFAULT 'en_cours',  -- en_cours | terminee | echec
    erreur          TEXT
);

CREATE TABLE IF NOT EXISTS annonces_executions (
    annonce_id   INTEGER NOT NULL,
    execution_id INTEGER NOT NULL,
    PRIMARY KEY (annonce_id, execution_id),
    FOREIGN KEY (annonce_id) REFERENCES annonces(id) ON DELETE CASCADE,
    FOREIGN KEY (execution_id) REFERENCES executions(id) ON DELETE CASCADE
);
"""


# Colonnes "Golden Rules" ajoutées après la v1 du schéma.
# SQLite ne connaît pas `ADD COLUMN IF NOT EXISTS`, on lit donc `PRAGMA table_info`
# pour savoir si la colonne existe, puis on `ALTER TABLE` de façon idempotente.
_COLONNES_GOLDEN_RULES: dict[str, str] = {
    "salaire_absent":           "INTEGER NOT NULL DEFAULT 0",
    "date_publication":         "TEXT",
    "url_active":               "INTEGER",
    "derniere_verification_le": "TEXT",
}


def _migrer_golden_rules(conn: sqlite3.Connection) -> None:
    """Ajoute les colonnes Golden Rules à une base pré-existante, sans data loss.

    Idempotent : si la colonne existe déjà, on ne fait rien. Les index liés
    sont créés après l'ajout des colonnes (nécessaire pour les bases pré-v1).
    """
    existantes = {row[1] for row in conn.execute("PRAGMA table_info(annonces)")}
    for nom, decl in _COLONNES_GOLDEN_RULES.items():
        if nom not in existantes:
            conn.execute(f"ALTER TABLE annonces ADD COLUMN {nom} {decl}")

    # Index Golden Rules : IF NOT EXISTS → sûrs à ré-exécuter.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_annonces_publi ON annonces(date_publication)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_annonces_active ON annonces(url_active)")


def init_db(path: Path) -> None:
    """Crée ou met à jour le schéma de la base à `path`.

    Sécurisé : `CREATE TABLE IF NOT EXISTS` ne touche pas aux données existantes.
    Les colonnes Golden Rules (post-v1) sont ajoutées par migration idempotente.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrer_golden_rules(conn)
        conn.commit()


DEFAULT_DB_PATH = Path.home() / ".agent-recherche" / "annonces.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=(
            "Chemin de la base (défaut: ~/.agent-recherche/annonces.db). "
            "On évite volontairement les dossiers synchronisés (Drive, OneDrive) qui "
            "peuvent casser le verrouillage SQLite."
        ),
    )
    args = parser.parse_args()

    try:
        init_db(args.path)
    except sqlite3.Error as err:
        print(f"[ERREUR] Échec de la création du schéma : {err}", file=sys.stderr)
        return 1

    print(f"[OK] Base prête : {args.path.resolve()}")
    print("     Schéma idempotent : tu peux relancer sans risque pour les données.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
