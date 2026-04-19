# Modèle de données

## Fichier `criteres.xlsx`

| Feuille | Rôle | Colonnes |
|---|---|---|
| `Mots_cles` | Mots-clés métier/ATS | `mot_cle`, `categorie`, `poids` (obligatoire/souhaitable/exclu), `commentaire` |
| `Localisation` | Géo + télétravail | `ville`, `region`, `rayon_km`, `teletravail_min_pct`, `actif` (OUI/NON) |
| `Profil_Poste` | Critères structurés du profil et du poste | `critere`, `valeur`, `operateur` (`>=`, `<=`, `=`, `in`, `not_in`), `poids` (`obligatoire`, `souhaitable`, `informatif`), `commentaire` |
| `Sources` | Activation par site | `source`, `methode` (API/Chrome), `actif` (OUI/NON), `notes` |

Règles de validation (cf. `scripts/load_criteres.py`) :

- `Mots_cles.poids` ∈ {`obligatoire`, `souhaitable`, `exclu`} sinon erreur explicite
- `Profil_Poste.poids` ∈ {`obligatoire`, `souhaitable`, `informatif`}
- `Profil_Poste.operateur` ∈ {`>=`, `<=`, `=`, `in`, `not_in`}
  - `>=` / `<=` exigent une valeur numérique
  - `in` / `not_in` interprètent la valeur comme une liste séparée par `,`
- Un critère `Profil_Poste` `obligatoire` ne peut pas avoir de valeur vide
- Pas de doublon de `critere` dans `Profil_Poste`
- `actif` ∈ {`OUI`, `NON`} (toléré : `YES`/`NO`, `TRUE`/`FALSE`, `1`/`0`)
- `methode` ∈ {`API`, `Chrome`}
- Au moins un mot-clé et une source sont requis

### Critères pré-remplis dans `Profil_Poste`

Le template livre une vingtaine de critères classiques d'une recherche cadre :
salaire min/cible, contrat, expérience min/max, statut, anglais, autres langues,
% télétravail min, % déplacements max, mobilité internationale, zone géographique,
taille d'entreprise, équipe à manager, budget géré.

Tu peux ajouter librement tes propres critères en insérant des lignes — la skill
de scoring suivante les utilisera dès qu'ils sont validés (`poids` ≠ `informatif`).

## Base `annonces.db`

### Table `annonces`

| Colonne | Type | Rôle |
|---|---|---|
| `id` | INTEGER PK | Identifiant interne |
| `url` | TEXT | URL d'origine (telle que collectée, avec tracking éventuel) |
| `url_canonique` | TEXT | URL nettoyée (pour dédup et lien stable) |
| `url_hash` | TEXT UNIQUE | SHA-256 hex de `url_canonique` — clé de dédup |
| `source` | TEXT | Nom du site (`France Travail`, `LinkedIn`, etc.) |
| `titre` | TEXT | Intitulé du poste |
| `entreprise` | TEXT | Nom de l'entreprise (si disponible) |
| `localisation` | TEXT | Lieu (texte brut) |
| `contrat` | TEXT | Type de contrat (texte brut) |
| `salaire_brut` | TEXT | Fourchette texte (normalisation downstream) |
| `salaire_absent` | INTEGER (0/1) | **Golden Rule #3** : 1 si aucune info salaire détectée |
| `extrait` | TEXT | 200-500 premiers caractères de la description |
| `criteres_matches` | TEXT (JSON) | Liste des mots-clés trouvés |
| `criteres_manquants` | TEXT (JSON) | Liste des obligatoires absents |
| `match_global` | INTEGER (0/1) | 1 si retenue, 0 si écartée |
| `date_publication` | TEXT (`AAAA-MM-JJ`) | **Golden Rule #2** : date de publication si connue (NULL sinon) |
| `url_active` | INTEGER (0/1/NULL) | **Golden Rule #1** : 1=page existe, 0=lien mort, NULL=indéterminé |
| `derniere_verification_le` | TEXT (ISO UTC) | Date/heure de la dernière vérif HTTP |
| `collectee_le` | TEXT (ISO) | Première fois vue |
| `derniere_vue_le` | TEXT (ISO) | MAJ à chaque revue |

### Golden Rules — rappel synthétique

| Règle | Colonne(s) impactée(s) | Comportement |
|---|---|---|
| #1 URL active | `url_active`, `derniere_verification_le` | Les annonces `url_active = 0` sont écartées avant insertion. `NULL` (401/403/timeout) = conservées (doute bénéficie à l'annonce) |
| #2 Récente (≤ 6 mois) | `date_publication` | Les annonces > 180 jours sont écartées avant insertion. Date inconnue = conservée |
| #3 Salaire non bloquant | `salaire_absent` | Le critère `salaire_annuel_brut_min_eur` est `souhaitable` dans le template. `salaire_absent = 1` ⇒ toujours conservée |

### Table `executions`

Journal d'audit des passes de recherche : `debut_le`, `fin_le`, `sources_actives`,
`nb_vues`, `nb_matches`, `nb_nouvelles`, `statut`, `erreur`.

### Table `annonces_executions`

Lien N-N pour savoir quelles annonces ont été observées à chaque exécution
(utile pour suivre la fraîcheur).

## Pourquoi SQLite ?

- Fichier unique, portable, sans serveur — adapté à un usage local mono-utilisateur
- Suffisant pour des dizaines de milliers d'annonces
- Lisible avec [DB Browser for SQLite](https://sqlitebrowser.org/) si besoin de bricoler à la main
- Permet d'évoluer vers Postgres plus tard sans changer de modèle relationnel

## Pourquoi la base est-elle dans `~/.agent-recherche/` et pas dans le dossier projet ?

Les dossiers synchronisés (OneDrive, iCloud Drive, Google Drive, Dropbox) et les
filesystems montés (FUSE) ne supportent pas correctement les verrouillages
`fcntl()` que SQLite utilise pour garantir l'intégrité de la base. Symptôme
typique : `disk I/O error` à l'ouverture.

On sépare donc :
- **Données éditables par l'utilisateur** (`criteres.xlsx`) → dossier projet, synchronisable
- **Base technique** (`annonces.db`) → `~/.agent-recherche/`, filesystem local uniquement

Si l'utilisateur veut quand même la base dans son dossier sync (ex: pour un backup
automatique), il peut passer `--path` explicitement, mais sera prévenu du risque.

## Évolutions prévues (hors périmètre actuel)

- Table `scores` : pondération fine, calculée par la skill suivante du pipeline
- Table `candidatures` : suivi des annonces sur lesquelles l'utilisateur a postulé
- Vue `annonces_actives` : annonces match=1 et non candidatées
