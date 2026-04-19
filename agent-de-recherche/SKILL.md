---
name: agent-de-recherche
description: Parcourt automatiquement les sites d'offres d'emploi (LinkedIn, APEC, Welcome to the Jungle, HelloWork, France Travail, Indeed), récupère les critères de recherche depuis un fichier Excel de paramétrage, identifie les annonces qui correspondent et stocke leurs URLs avec les critères matchés dans une base SQLite locale. À utiliser dès que l'utilisateur demande de "chercher des offres d'emploi", "scanner les annonces", "lancer la veille emploi", "trouver des jobs qui correspondent", "mettre à jour mes annonces", "rafraîchir ma liste d'offres", ou évoque tout besoin lié à sa recherche d'emploi automatisée — même sans mentionner explicitement les sites cibles. Couvre uniquement la phase de collecte ; le scoring fin, le rapport et l'envoi email sont délégués à d'autres skills.
---

# Agent de recherche d'annonces

## Objectif

Cette skill alimente un pipeline de recherche d'emploi automatisé pour un Directeur de Projet / Chef de Programme IT. Elle est la **première brique** du pipeline : elle collecte les URLs d'annonces qui matchent les critères de l'utilisateur, en parcourant plusieurs sites avec une approche hybride (APIs officielles + pilotage navigateur).

D'autres skills traiteront le scoring affiné, la génération du rapport et l'envoi email — **ne déborde pas sur leur périmètre**.

## Golden Rules

Ces règles s'appliquent **à toutes les annonces**, quelle que soit la source, **en plus** des critères de la feuille Excel. Elles sont implémentées dans `scripts/golden_rules.py` et appliquées systématiquement avant le stockage. Ce sont des **invariants** du pipeline, pas des paramètres utilisateur — elles ne sont pas éditables dans `criteres.xlsx`.

1. **Annonce active** — la page de détail doit être toujours accessible. Une requête HTTP (HEAD puis GET en repli) est effectuée : 2xx/3xx = conservée ; 404/410/451 = écartée. Un 401/403 (site exigeant un login, typiquement LinkedIn) est considéré comme **statut indéterminé** : on garde l'annonce plutôt que de la jeter à tort.
2. **Annonce récente (≤ 6 mois)** — `date_publication` doit être à moins de 180 jours de la date d'exécution. Si la date n'est pas exposée par le site, on **conserve** l'annonce (on ne peut pas la dater, on ne la pénalise pas).
3. **Salaire non bloquant** — si l'annonce ne mentionne **aucun** salaire, elle est conservée dans la sélection. Le critère `salaire_annuel_brut_min_eur` n'écarte une annonce **que** si elle affiche explicitement un salaire inférieur au plancher. Implication concrète : le critère est marqué `souhaitable` (pas `obligatoire`) dans `Profil_Poste`, et le scoring / rapport sait lire l'indicateur `salaire_absent` dans la base.

Pour modifier le seuil des 6 mois ou la liste des codes HTTP "vivants", édite les constantes `AGE_MAX_JOURS` et `CODES_VIVANTS` en tête de `scripts/golden_rules.py`.

## Architecture

L'agent suit toujours la même séquence :

```
1. Charger les critères (Excel)         → scripts/load_criteres.py
2. Initialiser la base si nécessaire    → scripts/init_db.py
3. Pour chaque source, collecter        → scripts/search_<source>.py
4. Matcher chaque annonce               → scripts/matcher.py
5. Appliquer les Golden Rules           → scripts/golden_rules.py
6. Stocker (avec dédup)                 → scripts/store_results.py
7. Restituer un résumé                  → ce fichier
```

Cette séparation est volontaire : chaque script a une responsabilité unique, peut être exécuté isolément en cas d'incident, et reste testable.

## Étape 1 — Préparation (premier lancement uniquement)

Avant la première exécution, deux fichiers doivent exister :

- `criteres.xlsx` — fichier de paramétrage utilisateur, dans le **dossier de travail** (`Agent recherche d'annonces/`). Reste dans le dossier sync pour que l'utilisateur puisse l'éditer dans Excel.
- `annonces.db` — base SQLite, dans `~/.agent-recherche/annonces.db` (filesystem **local**). On évite volontairement les dossiers synchronisés (Drive, OneDrive, FUSE) car ils cassent le verrouillage SQLite.

S'ils n'existent pas, lance dans cet ordre :

```bash
python scripts/init_criteres.py --path "<dossier-de-travail>/criteres.xlsx"
python scripts/init_db.py        # défaut : ~/.agent-recherche/annonces.db
```

**Ne jamais écraser ces fichiers s'ils existent déjà** — ils contiennent les paramètres et l'historique. Les scripts sont conçus pour être idempotents et refuseront d'écraser.

## Étape 2 — Charger et valider les critères

Lis `criteres.xlsx` via `scripts/load_criteres.py`. Le fichier contient quatre feuilles :

- **Mots_cles** : intitulés de poste, technos, méthodologies (Prince2, Scrum, etc.) avec colonne `poids` (`obligatoire`, `souhaitable`, `exclu`)
- **Localisation** : villes acceptées, rayon en km, pourcentage minimum de télétravail (détail des pôles)
- **Profil_Poste** : critères structurés du profil et du poste (structure unifiée `critere` / `valeur` / `operateur` / `poids` / `commentaire`). Contient salaire, contrat, expérience, statut, langues, mobilité, télétravail, zone géo, taille d'entreprise, équipe managée, budget piloté — et tout ce que l'utilisateur ajoutera.
- **Sources** : drapeau ON/OFF par site cible — respecte ce drapeau, ne va pas chercher sur un site désactivé

Si le fichier est corrompu ou qu'une feuille manque, **arrête-toi et demande à l'utilisateur de régénérer le template** plutôt que de deviner.

## Étape 3 — Collecter par source

Selon l'approche hybride retenue :

### Sources avec API (préfère toujours)

- **France Travail** (ex Pôle Emploi) — `scripts/search_france_travail.py`. API officielle, nécessite un client_id + client_secret stockés dans `~/.agent-recherche/credentials.env` (jamais dans le repo).
- **Adzuna** — `scripts/search_adzuna.py`. API REST gratuite, agrège Indeed et plusieurs autres. Couvre une partie du besoin "Indeed" sans pilotage Chrome.

### Sources nécessitant Chrome (Claude in Chrome MCP)

Pour LinkedIn, APEC, Welcome to the Jungle et HelloWork, utilise le MCP `mcp__Claude_in_Chrome__*` :

1. `navigate` vers la page de recherche du site avec les paramètres construits à partir des critères
2. `get_page_text` pour récupérer le contenu de la page de résultats
3. Extraire les URLs des annonces et les titres
4. Pour chaque URL, optionnellement `navigate` puis `get_page_text` pour récupérer le détail (à ne faire que si la page de résultats ne donne pas assez de contexte pour matcher)

**Sécurité — point important** : ne jamais demander ni stocker les mots de passe de l'utilisateur. La skill s'appuie sur le fait que l'utilisateur est déjà connecté dans son navigateur. Si une page de login s'affiche, signale-le à l'utilisateur et invite-le à se connecter manuellement, puis reprends.

**Conformité aux CGU** : limite la cadence des requêtes (1 requête / 2-3 secondes par site), respecte les `robots.txt`, n'aspire pas le site complet — uniquement les pages de résultats correspondant aux critères. LinkedIn en particulier interdit le scraping ; prévenir l'utilisateur du risque (compte temporairement restreint) au premier lancement et lui demander confirmation explicite avant d'inclure LinkedIn.

## Étape 4 — Matcher les critères

Pour chaque annonce collectée (titre + extrait de description si disponible), passe à `scripts/matcher.py` qui retourne :

- `match` : booléen — l'annonce passe-t-elle le filtre minimum (tous les critères `obligatoire` sont présents et aucun critère `exclu` n'est présent) ?
- `criteres_matches` : liste des mots-clés effectivement trouvés
- `criteres_manquants` : liste des `obligatoire` absents (vide si match=True)

Le matcher fait une recherche **insensible à la casse et aux accents**, et détecte les variantes courantes (`Scrum` ↔ `Scrum Master`, `chef de projet` ↔ `CDP`, etc. — voir `references/synonymes.md`).

Le **scoring fin** (pondération, ranking) n'est PAS du ressort de cette skill — il est délégué à la skill suivante du pipeline.

## Étape 5 — Appliquer les Golden Rules

Passe la liste des annonces retenues par le matcher à `scripts/golden_rules.py`, fonction `appliquer(annonces)`. Elle :

1. Vérifie que `date_publication` (si renseignée par la source) est à moins de 180 jours → écarte les annonces trop anciennes.
2. Effectue une requête HTTP sur chaque URL canonique (HEAD puis GET si HEAD non supporté) pour vérifier que la page existe toujours → écarte les 404/410/451.
3. Stampe sur les survivantes `url_active = 1` et `derniere_verification_le = now()`.

La vérification réseau est la plus coûteuse du pipeline : elle est **parallélisée** (thread pool, max 8 requêtes en parallèle, timeout de 10 s par URL) et plafonnée en cadence (`time.sleep` entre lots pour respecter les hébergeurs).

Les annonces déjà présentes en base et vérifiées il y a moins de 24h sont **réutilisées sans nouvelle requête** (champ `derniere_verification_le` dans SQLite) — économie de requêtes et respect des CGU.

## Étape 6 — Stocker

Passe les annonces à `scripts/store_results.py`. Le script :

- déduplique sur le hash SHA-256 de l'URL canonique (sans paramètres de tracking)
- met à jour `derniere_vue_le` si l'URL existe déjà
- insère sinon dans la table `annonces` avec : `url`, `url_hash`, `source`, `titre`, `criteres_matches` (JSON), `criteres_manquants` (JSON), `collectee_le`, `derniere_vue_le`, `date_publication`, `url_active`, `derniere_verification_le`, `salaire_absent`

Voir `references/data_model.md` pour le schéma complet.

## Étape 7 — Restituer

Affiche un résumé structuré et concis (pas de bullet points superflus si peu de données) :

```
Recherche terminée — 18/04/2026 14:32
─────────────────────────────────────
Sources interrogées : 6 (France Travail, Adzuna, LinkedIn, APEC, WTTJ, HelloWork)
Annonces vues       : 247
Annonces matchées   : 38 (critères métier)
Golden Rules        : -4 trop anciennes (> 6 mois)
                      -3 liens morts (404/410)
Annonces retenues   : 31 (dont 9 nouvelles depuis la dernière exécution)
Annonces écartées   : 216 (critères obligatoires manquants ou critère exclu)

Détail nouvelles annonces : voir annonces.db, table `annonces`, derniere_vue_le >= 2026-04-18
```

Propose ensuite à l'utilisateur :
- de lancer la skill suivante (scoring/rapport) si elle existe
- d'ouvrir `annonces.db` (ex : DB Browser for SQLite) pour vérifier
- d'ajuster `criteres.xlsx` si trop / pas assez de résultats

## Cas d'erreur fréquents

**API France Travail retourne 401** : le token est expiré ou les credentials manquent. Demande à l'utilisateur de renseigner `~/.agent-recherche/credentials.env` selon `references/credentials.md` — ne pas tenter de deviner.

**Page LinkedIn redirige vers login** : l'utilisateur n'est pas connecté dans le navigateur piloté. Signale-le, attends la reconnexion manuelle, ne stocke jamais les credentials.

**Aucune annonce trouvée sur un site** : ne pas conclure à un bug. Logger le critère utilisé et inviter l'utilisateur à vérifier (mots-clés trop restrictifs, localisation trop pointue, source désactivée dans la feuille `Sources`).

**Excel `criteres.xlsx` modifié à la main avec format cassé** : ne pas tenter de réparer en silence. Pointer la cellule problématique et demander correction.

## Pourquoi ce découpage ?

L'utilisateur est chef de projet certifié Prince2/Scrum PO — il pense en termes de livrables, de responsabilités claires et de testabilité. Cette skill suit donc le principe Single Responsibility :

- une skill = une étape du pipeline
- un script = une responsabilité technique
- un fichier de paramétrage = un domaine fonctionnel

Cela rend la maintenance plus simple, permet de remplacer une source sans toucher au reste, et facilite le diagnostic quand quelque chose casse.
