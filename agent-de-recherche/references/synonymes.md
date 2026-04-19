# Dictionnaire de synonymes

Ce fichier documente les équivalences utilisées par `scripts/matcher.py` pour
que le matching ne rate pas les variantes courantes des mots-clés.

## Philosophie

Les ATS et recruteurs emploient des formulations variées pour un même concept.
Sans synonymes, un critère `chef de projet` raterait les annonces intitulées
"Project Manager" ou "CDP" — ce qui est contraire à l'objectif.

Le matcher fait une recherche **insensible à la casse et aux accents**, et
les entrées du dictionnaire sont traitées en **mots entiers** (pas de
sous-chaîne) pour éviter les faux positifs.

## Règles pour ajouter un synonyme

1. La **clé** est la forme canonique telle que l'utilisateur l'écrit
   probablement dans `criteres.xlsx` (en minuscules, sans accents)
2. Les **valeurs** sont les variantes à considérer comme équivalentes
3. Rester conservateur : mieux vaut rater un match que produire des
   faux positifs — l'utilisateur perd confiance rapidement

## Synonymes actuels (voir `scripts/matcher.py`, dict `SYNONYMES`)

| Canonique | Variantes |
|---|---|
| `chef de projet` | chef de projets, chef de projet IT, CDP, Project Manager |
| `directeur de projet` | directeur de projets, Program Director, directeur de programme |
| `chef de programme` | Program Manager, chef de programmes |
| `scrum` | Scrum Master, Product Owner, PO, Scrum PO |
| `prince2` | Prince 2 |
| `agile` | SAFe, Kanban, Lean |
| `si` | système d'information, systèmes d'information, information system |
| `cloud` | AWS, Azure, GCP, Google Cloud |
| `transformation` | transfo, digital transformation, transformation digitale |

## Pièges à éviter

- **`PO`** : à garder explicitement sous `scrum`. Isolé, il matcherait "PORTEUR",
  "POSTE", etc. — le matcher utilise des word boundaries pour éviter ça, mais
  prudence
- **`Java`** vs **`JavaScript`** : le matcher traite les mots entiers, donc
  `Java` ne matche pas `JavaScript` — c'est volontaire
- **Acronymes courts** (2 lettres) : déconseillés car trop de faux positifs.
  Si indispensable, encadrer par un contexte (ex : "certification PO", pas "PO")

## Extension future

Si un vocabulaire métier spécifique s'avère nécessaire (ex : finance,
pharmaceutique), extraire le dictionnaire dans un YAML séparé chargé au
démarrage, pour ne pas alourdir `matcher.py`.
