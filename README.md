# Agent de recherche d'annonces — état du projet

> Document de synthèse pour reprise ultérieure (Claude Code, Cowork ou équipe).
> Dernière mise à jour : 2026-04-18.

## 1. Contexte

Projet personnel d'Olivier (Directeur de Projet / Chef de Programme IT, certifié
Prince2 et Scrum PO) visant à automatiser sa recherche d'emploi.

**Objectif produit** : un agent qui, à fréquence donnée, (1) parcourt les sites
d'offres d'emploi, (2) analyse le contenu selon des critères paramétrables,
(3) classe les annonces selon un scoring, (4) produit un rapport synthétique
et (5) l'envoie par email.

**Principe d'architecture** : découpage du pipeline en briques modulaires (une
skill = une responsabilité), pour faciliter la maintenance, permettre de
remplacer une source sans toucher au reste, et simplifier le diagnostic.

## 2. État actuel

La **brique 1 du pipeline** est livrée : skill `agent-de-recherche` qui
collecte les URLs d'annonces correspondant aux critères utilisateur, avec
déduplication entre exécutions.

Les briques suivantes restent à construire :
- Skill 2 : **scoring** fin (pondération, ranking) + export tableur classé
- Skill 3 : **rapport** synthétique (Word ou PDF)
- Skill 4 : **envoi email** (MCP Microsoft 365)
- Skill 5 : **scheduler** (fréquence d'exécution paramétrable)
- Interface utilisateur d'ajout/modification/suppression de critères (envisagée
  simplement comme édition directe de `criteres.xlsx` dans un premier temps)

## 3. Arborescence des livrables

```
Agent recherche d'annonces/
├── README.md                       ← ce fichier
├── criteres.xlsx                   ← paramétrage utilisateur (à éditer dans Excel)
├── agent-de-recherche.skill        ← skill packagée (double-clic pour installer)
└── agent-de-recherche/             ← code source de la skill
    ├── SKILL.md                    ← instructions pour Claude quand la skill se déclenche
    ├── scripts/
    │   ├── init_criteres.py        ← génère criteres.xlsx (template pré-rempli)
    │   ├── init_db.py              ← crée/migre le schéma SQLite
    │   ├── load_criteres.py        ← parse et valide criteres.xlsx
    │   ├── matcher.py              ← matching critères ↔ annonce (mots-clés)
    │   ├── store_results.py        ← persistance SQLite avec déduplication
    │   ├── search_france_travail.py ← collecte via API officielle France Travail
    │   └── search_adzuna.py         ← collecte via API Adzuna (agrège Indeed & co)
    └── references/
        ├── data_model.md           ← schéma Excel et SQLite détaillés
        ├── credentials.md          ← gestion des clés API, sécurité
        ├── chrome_workflow.md      ← pilotage navigateur pour LinkedIn/APEC/WTTJ/HelloWork
        └── synonymes.md            ← dictionnaire de synonymes du matcher

~/.agent-recherche/                 ← filesystem local (pas de sync)
├── annonces.db                     ← base SQLite (créée au premier lancement)
└── credentials.env                 ← clés API (créé manuellement, chmod 600)
```

## 4. Périmètre de la skill livrée

La skill se déclenche sur des phrases comme *"lance ma veille emploi"*,
*"trouve-moi des offres"*, *"scanne les annonces"*, et orchestre un pipeline en
6 étapes :

1. Charge et valide les critères depuis `criteres.xlsx`
2. Initialise la base SQLite si premier lancement
3. Pour chaque source active, collecte les annonces :
   - **APIs officielles** (France Travail, Adzuna) — requêtes authentifiées
   - **Pilotage Chrome** (LinkedIn, APEC, Welcome to the Jungle, HelloWork) via
     le MCP `Claude_in_Chrome`, en s'appuyant sur les sessions déjà connectées
     de l'utilisateur
4. Pour chaque annonce, applique le matcher (obligatoire/souhaitable/exclu,
   insensible casse/accents, synonymes courants du domaine)
5. Stocke les annonces retenues dans SQLite, déduplication via hash SHA-256 de
   l'URL canonique (paramètres `utm_*`, `fbclid`, etc. retirés)
6. Restitue un résumé structuré : sources interrogées, annonces vues, matchées,
   nouvelles depuis la dernière exécution

Le **scoring fin** n'est PAS du ressort de cette skill — il sera traité par la
skill suivante, qui lira la base SQLite alimentée ici.

## 5. Installation et premier lancement

### 5.1 Installer la skill dans Claude Code / Cowork

Double-cliquer sur `agent-de-recherche.skill` (fichier ZIP format skill).

### 5.2 Générer le fichier de paramétrage (déjà fait)

```bash
python agent-de-recherche/scripts/init_criteres.py --path "criteres.xlsx"
```

Le template est pré-rempli pour un profil Directeur de Projet IT senior. Il
faut l'éditer dans Excel pour adapter les mots-clés, le salaire, la zone
géographique, etc.

### 5.3 Initialiser la base SQLite

```bash
python agent-de-recherche/scripts/init_db.py
# → crée ~/.agent-recherche/annonces.db
```

### 5.4 Configurer les APIs (optionnel mais recommandé)

Créer `~/.agent-recherche/credentials.env` avec :

```env
FT_CLIENT_ID=xxxxxxxx
FT_CLIENT_SECRET=xxxxxxxx
ADZUNA_APP_ID=xxxxxxxx
ADZUNA_APP_KEY=xxxxxxxx
```

Obtention des clés :
- France Travail : https://francetravail.io/data/api/offres-emploi
- Adzuna : https://developer.adzuna.com/signup

Permissions : `chmod 700 ~/.agent-recherche && chmod 600 ~/.agent-recherche/credentials.env`.

### 5.5 Lancer une recherche

Dans Claude Code ou Cowork, simplement : *"lance ma veille emploi"* ou
*"scanne les annonces"*.

## 6. Structure de `criteres.xlsx` (4 feuilles)

### Mots_cles — termes ATS pondérés

| Colonne | Rôle |
|---|---|
| `mot_cle` | Terme à rechercher (insensible casse/accents, mots entiers) |
| `categorie` | Libre (Intitule, Methodologie, Techno, Domaine...) |
| `poids` | `obligatoire` / `souhaitable` / `exclu` |
| `commentaire` | Notes libres |

Règle : une annonce est **retenue** si tous les `obligatoire` sont présents
ET aucun `exclu` n'est trouvé. Les `souhaitable` alimentent le scoring futur.

### Localisation — pôles géographiques

| Colonne | Rôle |
|---|---|
| `ville` | Ville de rattachement |
| `region` | Région (optionnel) |
| `rayon_km` | Rayon d'acceptation autour |
| `teletravail_min_pct` | % télétravail minimum accepté |
| `actif` | OUI / NON |

### Profil_Poste — critères structurés unifiés

Structure puissante : chaque ligne est un critère indépendant avec son propre
opérateur. Permet d'exprimer toutes les règles classiques d'une recherche cadre.

| Colonne | Rôle |
|---|---|
| `critere` | Identifiant technique (snake_case) |
| `valeur` | Nombre, texte, ou liste séparée par virgule |
| `operateur` | `>=`, `<=`, `=`, `in`, `not_in` |
| `poids` | `obligatoire` / `souhaitable` / `informatif` |
| `commentaire` | Notes libres |

**Critères pré-remplis** : salaire min/cible, contrat accepté, expérience min/max,
statut cadre, anglais, autres langues, % télétravail min, % déplacements max,
mobilité internationale, zone géographique, taille d'entreprise, équipe à
manager, budget géré.

**Extensible** : ajouter librement des lignes (ex : `niveau_etudes_min in "Bac+5,Master,Ingénieur"`,
`secteur_exclu not_in "Tabac,Défense"`, `temps_de_trajet_max_min <= 60`). Le
loader valide la cohérence (opérateur / type de valeur, obligatoire non vide,
pas de doublons) et pointe la cellule fautive si erreur.

### Sources — activation par site

| Colonne | Rôle |
|---|---|
| `source` | Nom du site |
| `methode` | `API` ou `Chrome` |
| `actif` | OUI / NON |
| `notes` | Notes libres |

Sites pré-configurés : France Travail, Adzuna, LinkedIn, APEC, Welcome to the
Jungle, HelloWork, Indeed.

## 7. Schéma de la base SQLite

Trois tables (détail complet dans `references/data_model.md`) :

- **`annonces`** : une ligne par offre unique. Clé de dédup = `url_hash`
  (SHA-256 de l'URL canonique). Colonnes : `url`, `url_canonique`, `source`,
  `titre`, `entreprise`, `localisation`, `contrat`, `salaire_brut`, `extrait`,
  `criteres_matches` (JSON), `criteres_manquants` (JSON), `match_global`,
  `collectee_le`, `derniere_vue_le`.

- **`executions`** : journal d'audit de chaque passe de recherche. Permet de
  tracer ce qui a été fait, quand, avec quel résultat.

- **`annonces_executions`** : lien N-N pour savoir quelles annonces ont été
  observées à quelle exécution (fraîcheur).

## 8. Points d'architecture à retenir

### 8.1 Pourquoi SQLite en local (`~/.agent-recherche/`) et pas dans le dossier projet ?

Les dossiers synchronisés (OneDrive, iCloud Drive, Google Drive) et les
filesystems montés (FUSE) ne supportent pas correctement les verrouillages
`fcntl()` que SQLite exige. Symptôme : `disk I/O error`. On sépare donc les
données éditables par l'utilisateur (`criteres.xlsx`, synchronisable) de la
base technique (`annonces.db`, local uniquement).

### 8.2 Sécurité — pas de credentials utilisateur stockés

La skill ne stocke **jamais** les mots de passe LinkedIn, APEC, WTTJ, etc.
Elle s'appuie sur le navigateur de l'utilisateur via le MCP Claude in Chrome —
celui-ci doit déjà être connecté. Si une page de login s'affiche, la skill
détecte la redirection et signale le besoin de reconnexion manuelle, sans
tenter de soumettre un formulaire.

Seules les APIs officielles (France Travail, Adzuna) nécessitent des clés
applicatives, stockées **hors du dossier projet** dans
`~/.agent-recherche/credentials.env` avec permissions restrictives.

### 8.3 Conformité aux CGU des sites

LinkedIn et certains autres sites interdisent le scraping automatisé. La skill
mitige le risque par :
- cadence respectueuse (1 req / 2-3 s par site)
- aucune connexion automatisée (l'utilisateur doit être déjà connecté)
- collecte limitée aux pages de résultats correspondant aux critères, pas de
  crawl exhaustif
- avertissement explicite de l'utilisateur au premier lancement sur le risque
  résiduel (compte éventuellement temporairement restreint)

### 8.4 Découpage fonctionnel strict (Single Responsibility)

Une skill = une étape du pipeline. Un script = une responsabilité technique.
Un fichier de paramétrage = un domaine fonctionnel. Ce choix structure toute
la solution et doit être respecté dans les briques suivantes.

### 8.5 Idempotence des scripts d'initialisation

- `init_criteres.py` refuse d'écraser `criteres.xlsx` sans `--force` (protège
  le paramétrage utilisateur)
- `init_db.py` est toujours safe à relancer (schéma `CREATE TABLE IF NOT EXISTS`,
  données préservées)

### 8.6 Déduplication robuste par hash d'URL canonique

Une même annonce vue 3 fois (LinkedIn direct, newsletter, notification) avec
des paramètres de tracking différents (`utm_source`, `fbclid`, etc.) ne crée
qu'une seule ligne en base. Testé OK.

## 9. Tests effectués

| Test | Résultat |
|---|---|
| `init_criteres.py` crée 4 feuilles avec listes déroulantes | OK |
| `init_criteres.py` refuse d'écraser sans `--force` | OK |
| `init_db.py` crée le schéma idempotent | OK |
| `load_criteres.py` valide la structure Profil_Poste | OK (détecte op/type incohérent) |
| `matcher.py` retient annonce "Directeur de projet + Prince2 + Cloud" | OK (4 critères matchés) |
| `matcher.py` écarte annonce sans l'obligatoire | OK |
| `matcher.py` écarte annonce contenant un exclu (Stagiaire) | OK |
| `matcher.py` gère casse et accents | OK (DIRECTEUR DE PROJETS → match) |
| `store_results.py` dédup sur URL canonique (2 URLs LinkedIn trackées différemment) | OK (1 seule ligne) |

Les scripts API (France Travail, Adzuna) ne sont pas testés bout-en-bout faute
de credentials — ce sera fait au premier lancement réel.

## 10. Prochaines étapes suggérées

Ordre conseillé pour construire les briques suivantes :

1. **Skill de scoring** : lire `annonces.db` + `criteres.xlsx`, calculer un
   score pondéré par annonce en croisant `criteres_matches` (mots-clés) et
   critères `Profil_Poste`, exporter un `classement.xlsx` trié.
2. **Skill de rapport** : générer un Word ou PDF synthétique à partir du
   classement (top 10 annonces + stats globales + évolution depuis le
   précédent rapport).
3. **Skill d'envoi email** via MCP Microsoft 365 : envoi du rapport en pièce
   jointe + corps de mail structuré.
4. **Scheduler** : tâche planifiée qui enchaîne les 4 skills à une fréquence
   paramétrable (hebdomadaire probablement).

Recommandation : garder la même discipline de modularité. Chaque skill reste
testable isolément et remplaçable.

## 11. Commandes utiles pour reprise

```bash
# Voir les annonces stockées
python -c "
import sqlite3
from pathlib import Path
db = Path.home() / '.agent-recherche' / 'annonces.db'
with sqlite3.connect(db) as c:
    for r in c.execute('SELECT id, source, titre, collectee_le FROM annonces ORDER BY collectee_le DESC LIMIT 20'):
        print(r)
"

# Voir l'historique des exécutions
python -c "
import sqlite3
from pathlib import Path
db = Path.home() / '.agent-recherche' / 'annonces.db'
with sqlite3.connect(db) as c:
    for r in c.execute('SELECT * FROM executions ORDER BY debut_le DESC LIMIT 10'):
        print(r)
"

# Re-package la skill après modifications
cd /path/to/skill-creator && python -m scripts.package_skill \
  "/path/to/Agent recherche d'annonces/agent-de-recherche" \
  "/path/to/Agent recherche d'annonces"
```

## 12. Dépendances Python

Minimal : `openpyxl`, `requests`. Optionnel : `python-dotenv` (pour charger
`credentials.env` automatiquement).

```bash
pip install openpyxl requests python-dotenv
```

---

**Contact projet** : Olivier Clery — olivierclery@hotmail.com
