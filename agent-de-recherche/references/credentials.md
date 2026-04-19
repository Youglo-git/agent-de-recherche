# Gestion des credentials

## Principe de sécurité

**Aucun mot de passe utilisateur (LinkedIn, APEC, etc.) n'est jamais stocké.**
Pour ces sites, la skill s'appuie sur Claude in Chrome MCP qui pilote le navigateur
de l'utilisateur — celui-ci doit déjà être connecté manuellement. Si la session
expire, la skill détecte la redirection vers la page de login et invite
l'utilisateur à se reconnecter, sans tenter de soumettre un formulaire.

Les **APIs officielles** (France Travail, Adzuna) exigent en revanche des clés
applicatives. Ces clés sont stockées **hors du dossier projet**, dans
`~/.agent-recherche/credentials.env`, en variables d'environnement.

## Fichier `~/.agent-recherche/credentials.env`

À créer manuellement (le dossier doit avoir des permissions restrictives) :

```bash
mkdir -p ~/.agent-recherche
chmod 700 ~/.agent-recherche
touch ~/.agent-recherche/credentials.env
chmod 600 ~/.agent-recherche/credentials.env
```

Format attendu (une variable par ligne, syntaxe dotenv) :

```env
# France Travail — https://francetravail.io/
FT_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
FT_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Adzuna — https://developer.adzuna.com/
ADZUNA_APP_ID=xxxxxxxx
ADZUNA_APP_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

## Comment obtenir les credentials

### France Travail
1. Aller sur https://francetravail.io/data/api/offres-emploi
2. Créer un compte développeur
3. Créer une "application" et noter `client_id` + `client_secret`
4. Vérifier que les scopes `api_offresdemploiv2` et `o2dsoffre` sont activés

### Adzuna
1. Aller sur https://developer.adzuna.com/signup
2. S'inscrire (compte gratuit)
3. Récupérer `Application ID` et `Application Key` dans le dashboard

## Que faire si Claude n'arrive pas à charger les variables ?

- Vérifier que `python-dotenv` est installé : `pip install python-dotenv`
- Vérifier la présence du fichier : `ls -la ~/.agent-recherche/credentials.env`
- Vérifier qu'il n'y a pas de guillemets autour des valeurs
- En dernier recours, exporter manuellement avant de lancer :
  ```bash
  export $(grep -v '^#' ~/.agent-recherche/credentials.env | xargs) && python scripts/search_france_travail.py
  ```

## Ne jamais

- Commiter le fichier credentials dans un repo Git
- Coller les clés dans `criteres.xlsx` (qui peut être partagé)
- Stocker les credentials LinkedIn/APEC/etc. — ces sites interdisent l'usage automatisé
  de comptes, et la skill respecte cette contrainte par design
