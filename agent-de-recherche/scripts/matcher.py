"""Évalue si une annonce matche les critères utilisateur.

Principe :
- normalisation insensible à la casse et aux accents
- recherche de mots entiers (word boundaries) pour éviter les faux positifs
  (ex: 'Java' ne doit pas matcher 'JavaScript' ; 'PO' ne doit pas matcher 'PORTEUR')
- dictionnaire de synonymes simple et extensible (references/synonymes.md)

Le matcher répond à la seule question : "cette annonce passe-t-elle le filtre
minimum ?". Le scoring fin (pondération, ranking) est fait par une autre skill.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Import relatif pour permettre l'exécution directe comme script
try:
    from load_criteres import Criteres, MotCle, load_criteres
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).parent))
    from load_criteres import Criteres, MotCle, load_criteres  # type: ignore


# Synonymes ↔ canonique. Clé : canonique (tel qu'écrit dans criteres.xlsx, insensible casse)
# Valeur : liste de variantes qui déclenchent aussi un match.
# On garde ça léger ; la doc d'étoffement est dans references/synonymes.md
SYNONYMES: dict[str, list[str]] = {
    "chef de projet": ["chef de projets", "chef de projet it", "cdp", "project manager"],
    "directeur de projet": ["directeur de projets", "program director", "directeur de programme"],
    "chef de programme": ["program manager", "chef de programmes"],
    "scrum": ["scrum master", "product owner", "po", "scrum po"],
    "prince2": ["prince 2"],
    "agile": ["safe", "kanban", "lean"],
    "si": ["système d'information", "systemes d'information", "information system"],
    "cloud": ["aws", "azure", "gcp", "google cloud"],
    "transformation": ["transfo", "digital transformation", "transformation digitale"],
}


@dataclass
class MatchResult:
    match: bool
    criteres_matches: list[str] = field(default_factory=list)
    criteres_manquants: list[str] = field(default_factory=list)
    criteres_exclus_trouves: list[str] = field(default_factory=list)

    def resume(self) -> str:
        if not self.match:
            if self.criteres_exclus_trouves:
                return f"Écartée : critère exclu trouvé ({', '.join(self.criteres_exclus_trouves)})"
            return f"Écartée : obligatoires manquants ({', '.join(self.criteres_manquants)})"
        return f"Retenue : {len(self.criteres_matches)} critère(s) matché(s)"


def _normaliser(texte: str) -> str:
    """Supprime accents et passe en minuscules pour recherche robuste."""
    if not texte:
        return ""
    # Décomposition NFD puis suppression des diacritiques
    nfd = unicodedata.normalize("NFD", texte)
    sans_accents = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return sans_accents.lower()


def _contient(haystack_norm: str, terme: str) -> bool:
    """Cherche un terme (avec ses synonymes) comme mot entier, insensible casse/accents."""
    if not terme:
        return False
    terme_norm = _normaliser(terme)
    candidats = {terme_norm}

    # Ajouter les synonymes si le terme correspond à une entrée canonique
    if terme_norm in SYNONYMES:
        for syn in SYNONYMES[terme_norm]:
            candidats.add(_normaliser(syn))

    for candidat in candidats:
        # Word boundary pour éviter les sous-chaînes trompeuses.
        # On autorise l'espace comme délimiteur (pour "chef de projet").
        pattern = r"(?:^|\W)" + re.escape(candidat) + r"(?:\W|$)"
        if re.search(pattern, haystack_norm):
            return True
    return False


def evaluer(annonce_texte: str, criteres: Criteres) -> MatchResult:
    """Évalue une annonce (texte concaténé titre + description) contre les critères.

    Règle :
    - si un critère 'exclu' est trouvé → écartée, on n'ajoute PAS l'annonce
    - si TOUS les critères 'obligatoire' ne sont pas présents → écartée
    - sinon → retenue ; la liste des 'souhaitable' matchés est remontée
    """
    texte_norm = _normaliser(annonce_texte)

    exclus_trouves = [m.mot_cle for m in criteres.exclusions() if _contient(texte_norm, m.mot_cle)]
    if exclus_trouves:
        return MatchResult(
            match=False,
            criteres_exclus_trouves=exclus_trouves,
        )

    obligatoires = criteres.obligatoires()
    manquants = [m.mot_cle for m in obligatoires if not _contient(texte_norm, m.mot_cle)]
    if manquants:
        return MatchResult(match=False, criteres_manquants=manquants)

    # À ce stade : obligatoires tous présents, aucun exclu présent
    matches_obligatoires = [m.mot_cle for m in obligatoires]
    matches_souhaitables = [
        m.mot_cle for m in criteres.souhaitables() if _contient(texte_norm, m.mot_cle)
    ]
    return MatchResult(
        match=True,
        criteres_matches=matches_obligatoires + matches_souhaitables,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--criteres", type=Path, default=Path("criteres.xlsx"))
    parser.add_argument(
        "--texte",
        type=str,
        required=True,
        help="Texte de l'annonce à évaluer (titre + description)",
    )
    args = parser.parse_args()

    criteres = load_criteres(args.criteres)
    result = evaluer(args.texte, criteres)

    print(json.dumps(
        {
            "match": result.match,
            "criteres_matches": result.criteres_matches,
            "criteres_manquants": result.criteres_manquants,
            "criteres_exclus_trouves": result.criteres_exclus_trouves,
            "resume": result.resume(),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if result.match else 2  # 2 = annonce non retenue (pas une erreur)


if __name__ == "__main__":
    raise SystemExit(main())
