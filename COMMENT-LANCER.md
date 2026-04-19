# Comment lancer le pipeline de recherche d'emploi

Trois manières de déclencher le pipeline, du plus simple au plus technique.

> **Mode de diffusion :** pas d'envoi par email (Microsoft a désactivé SMTP AUTH pour les comptes Hotmail personnels en 2024). À la place, un **rappel récurrent dans Outlook** (chaque dimanche à 10h00) renvoie vers `rapport.html`. Voir section 4.d pour l'import du fichier `.ics`.

---

## 1. Lancement automatique (scheduler déjà configuré)

Le pipeline tourne **tous les dimanches à 9h00** (heure locale).

- Tâche planifiée : `pipeline-recherche-emploi`
- Prochaine exécution : visible dans **Cowork → barre latérale → Scheduled**
- Au terme du pipeline, une **notification Windows** signale qu'un nouveau rapport est disponible
- Le rappel **Outlook** du dimanche 10h00 (importé une seule fois via `rappel-veille-emploi.ics`) contient le lien direct vers le rapport

Tu peux désactiver, modifier l'horaire ou forcer une exécution immédiate depuis cette même barre latérale Cowork.

---

## 2. Lancement manuel via Cowork (recommandé pour tester)

Dans n'importe quelle conversation Cowork avec accès à ce projet, dis simplement :

> Lance le pipeline de recherche d'emploi.

Claude enchaînera les skills dans l'ordre :
`agent-de-recherche` → archivage → `scoring-annonces` → `dashboard-annonces` → notification Windows.

**Variantes utiles :**
- *« Relance seulement le scoring, j'ai modifié mes critères »* → skip étape 1, rescorer tout, régénérer le dashboard
- *« Régénère le rapport sans rescorer »* → seulement `dashboard-annonces`
- *« Ouvre le dernier rapport »* → Claude ouvre `rapport.html` dans ton navigateur par défaut

---

## 3. Lancement manuel en ligne de commande (utilisateurs avancés)

Si tu veux contrôler chaque étape depuis un terminal (cmd.exe ou PowerShell sous Windows) :

```bat
:: Variables à adapter
set PROJET=C:\Users\olivi\Documents\Agent recherche d'annonces
set DB=%USERPROFILE%\.agent-recherche\annonces.db
set CREDS=%USERPROFILE%\.agent-recherche\credentials.env
set SKILLS=%USERPROFILE%\Documents\Claude\skills

:: 1. Collecte API + Golden Rules + persistance (un seul orchestrateur)
::    Les sources LinkedIn/APEC/WTTJ/HelloWork passent par Cowork+Chrome
::    et alimentent --extra-json (cf. SKILL.md agent-de-recherche).
python "%SKILLS%\agent-de-recherche\scripts\run_collecte.py" ^
  --criteres "%PROJET%\criteres.xlsx" ^
  --db-path "%DB%" ^
  --credentials "%CREDS%" ^
  --sources adzuna,france_travail

:: 2. Archivage du rapport précédent
python "%SKILLS%\dashboard-annonces\scripts\archive_rapport.py" --rapport "%PROJET%\rapport.html"

:: 3. Scoring
python "%SKILLS%\scoring-annonces\scripts\migrate_db.py" --db-path "%DB%"
python "%SKILLS%\scoring-annonces\scripts\score.py" --db-path "%DB%" --criteres "%PROJET%\criteres.xlsx"

:: 4. Dashboard
python "%SKILLS%\dashboard-annonces\scripts\generate_dashboard.py" --db-path "%DB%" --output "%PROJET%\rapport.html" --questions-dir "%PROJET%\questions-annonces"

:: 5. Notification Windows (optionnelle)
python "%SKILLS%\dashboard-annonces\scripts\notify_pipeline_done.py" --db-path "%DB%" --rapport-url "file:///C:/Users/olivi/Documents/Agent%%20recherche%%20d%%27annonces/rapport.html"

:: 6. Ouverture immédiate du rapport (optionnel)
start "" "%PROJET%\rapport.html"
```

> **Golden Rules** : `run_collecte.py` applique automatiquement les 3 règles transverses (URL active, fraîcheur < 180j, marquage salaire absent) entre la collecte et la persistance. Aucune action supplémentaire à faire.

**Codes retour** : `0` succès, non-zéro échec. Pratique pour chaîner avec `&&` ou pour intégrer dans une autre automatisation.

---

## 4. Configuration initiale à compléter (une seule fois)

### a) Credentials API

Crée le fichier `%USERPROFILE%\.agent-recherche\credentials.env` (ou utilise `setup-credentials.bat` qui le copie depuis ce dossier projet) :

```
EMAIL_DESTINATAIRE=olivierclery@hotmail.com
ADZUNA_APP_ID=...
ADZUNA_APP_KEY=...
FT_CLIENT_ID=...
FT_CLIENT_SECRET=...
```

- **Adzuna** : clé gratuite sur [developer.adzuna.com](https://developer.adzuna.com) → 250 appels/jour gratuits.
- **France Travail** : [francetravail.io](https://francetravail.io) → activer l'API « Offres d'emploi v2 » sur l'application créée.
- **LinkedIn / APEC / Welcome to the Jungle / HelloWork** : pas d'API officielle, la collecte se fait via le navigateur Chrome piloté par Cowork (aucun credential à gérer).

Tant que des credentials API ne sont pas renseignés, les sources concernées sont skip sans bloquer le pipeline.

> Les variables `SMTP_*` ne sont **plus utilisées** depuis le passage au mode « rappel Outlook ». Elles peuvent être laissées en place ou supprimées sans effet sur le pipeline.

### b) Critères

Édite directement `criteres.xlsx` dans ce dossier. Les modifications sont prises en compte dès la prochaine exécution de `scoring-annonces`. Pour rescorer tout l'historique après changement des critères :

```bat
python "%SKILLS%\scoring-annonces\scripts\score.py" --db-path "%DB%" --criteres "%PROJET%\criteres.xlsx" --rescore-all
```

### c) Notifications Windows

La notification toast utilise l'API native Windows (`Windows.UI.Notifications` via PowerShell) — aucune installation requise sur Windows 10/11.

Si la notif ne s'affiche pas, vérifier dans **Paramètres Windows → Système → Notifications** que les notifications sont autorisées pour PowerShell.

### d) Rappel Outlook hebdomadaire

Le fichier `rappel-veille-emploi.ics` (à la racine du projet) contient un événement récurrent :
- Tous les **dimanches à 10h00**
- Rappel **15 minutes avant**
- Description avec lien cliquable `file:///` vers `rapport.html`

**Pour l'importer :**

1. **Outlook web** ([outlook.live.com](https://outlook.live.com)) :
   - Calendrier → bouton **Ajouter un calendrier** → **Charger à partir d'un fichier** → sélectionner `rappel-veille-emploi.ics`.
2. **Outlook desktop** : Double-cliquer sur le fichier `.ics` → Outlook s'ouvre → cliquer **Enregistrer & Fermer**.
3. **Téléphone** : Synchronisation automatique via ton compte Outlook une fois importé sur web ou desktop.

Une fois importé, tu peux ajuster l'heure ou la fréquence directement dans Outlook (clic droit sur l'événement → modifier la série).

---

## 5. En cas de souci

| Symptôme | Cause probable | Action |
|---|---|---|
| `no such table: annonces` | `agent-de-recherche` n'a jamais tourné | Lancer la skill `agent-de-recherche` manuellement une première fois |
| Toutes les annonces écartées (gate) | Critères obligatoires trop stricts dans `criteres.xlsx` | Assouplir les mots-clés `obligatoire` ou passer certains critères `Profil_Poste` en `souhaitable` |
| Lien Outlook ne s'ouvre pas | Outlook bloque les liens `file:///` par sécurité | Copier le chemin dans la description et le coller dans l'Explorateur Windows |
| Notification Windows absente | Notifications PowerShell désactivées | Paramètres → Système → Notifications → activer pour PowerShell |
| Rapport vide | Aucune nouvelle annonce ou critères incohérents | Vérifier la table `annonces` en SQL ou relancer `agent-de-recherche` |

Les logs d'exécution sont dans la table `executions` de `annonces.db` — requêtables en SQL si besoin d'aller plus loin.
