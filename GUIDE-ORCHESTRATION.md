# Guide d'orchestration — Pipeline de recherche d'emploi

## Vue d'ensemble

Le pipeline complet est composé de **4 skills** atomiques, chacune avec une responsabilité unique :

```
agent-de-recherche  →  scoring-annonces  →  dashboard-annonces  →  envoi-rapport-email
   (collecte)            (notation)            (visualisation)        (diffusion)
```

Chaque skill peut être lancée **indépendamment** : elles communiquent uniquement par le contenu de la base SQLite (`~/.agent-recherche/annonces.db`) et par le fichier `rapport.html` dans le dossier de travail.

## Séquence d'appel par le scheduler

Pour une exécution automatisée (cron, Windows Task Scheduler, ou la skill `schedule` de Cowork), enchaîner les commandes ci-dessous **dans cet ordre** :

```bash
# Variables (à adapter selon ta config)
PROJET="$HOME/Documents/Agent recherche d'annonces"
DB="$HOME/.agent-recherche/annonces.db"
CREDS="$HOME/.agent-recherche/credentials.env"

# 1. Collecte
cd "$HOME/.claude/skills/agent-de-recherche"
python scripts/load_criteres.py
python scripts/init_db.py  # idempotent, ne fait rien si DB existe
# (les scripts/search_*.py sont appelés via la skill, pas en CLI direct)

# 2. Scoring
cd "$HOME/.claude/skills/scoring-annonces"
python scripts/migrate_db.py --db-path "$DB"
python scripts/score.py --db-path "$DB" --criteres "$PROJET/criteres.xlsx"

# 3. Dashboard
cd "$HOME/.claude/skills/dashboard-annonces"
python scripts/generate_dashboard.py \
    --db-path "$DB" \
    --output "$PROJET/rapport.html" \
    --questions-dir "questions-annonces"

# 4. Email
cd "$HOME/.claude/skills/envoi-rapport-email"
python scripts/send_report.py \
    --rapport "$PROJET/rapport.html" \
    --db-path "$DB" \
    --credentials "$CREDS"
```

## Fréquences recommandées

| Skill | Fréquence type | Raisonnement |
|---|---|---|
| `agent-de-recherche` | 1 à 2 fois/jour | Les sites publient au fil de l'eau ; éviter d'être détecté en scraping (cadence raisonnable). |
| `scoring-annonces` | À chaque collecte (chaîné) | Le scoring est rapide (<1s pour 100 annonces) — on l'enchaîne automatiquement. |
| `dashboard-annonces` | Avant chaque envoi | Le dashboard reflète l'état au moment de l'envoi. |
| `envoi-rapport-email` | 1 fois/jour le matin OU 1 fois/semaine le lundi | Selon ta tolérance : daily pour ne rien rater, hebdo pour rester focus. |

**Recommandation Olivier** : un seul cron quotidien à 7h00 qui enchaîne les 4. Si tu trouves les emails trop fréquents, baisse à 3 fois/semaine (lun/mer/ven).

## Gestion des erreurs

Le pipeline est conçu pour qu'**une étape qui échoue n'invalide pas les précédentes** :

- Si `agent-de-recherche` échoue → la DB reste dans son état précédent. Les étapes suivantes traitent ce qui est déjà là.
- Si `scoring-annonces` échoue à mi-parcours → les annonces déjà scorées restent scorées (commit par batch de 100). Relance et seules les non scorées seront retraitées (idempotent).
- Si `dashboard-annonces` échoue → l'ancien `rapport.html` reste utilisable.
- Si `envoi-rapport-email` échoue → la table `envois` log l'erreur. Pas d'envoi en double si on relance plus tard (à condition de vérifier la table).

### Codes retour

Tous les scripts retournent **0** en cas de succès, **non-zéro** en cas d'erreur. Le scheduler peut donc utiliser :

```bash
python scripts/score.py --db-path "$DB" || { echo "Scoring KO"; exit 1; }
```

ou enchaîner avec `&&` pour stopper la chaîne au premier échec :

```bash
python scripts/migrate_db.py && python scripts/score.py && python ../dashboard-annonces/scripts/generate_dashboard.py && python ../envoi-rapport-email/scripts/send_report.py
```

## Logs

Aucune skill ne crée de fichier log dédié — les sorties partent sur stdout/stderr. Le scheduler doit donc rediriger :

```bash
# Cron Linux/Mac
0 7 * * * /usr/bin/env bash $HOME/scripts/pipeline-emploi.sh >> $HOME/.agent-recherche/pipeline.log 2>&1
```

Pour Windows (Task Scheduler) :

```batch
pipeline-emploi.bat >> "%USERPROFILE%\.agent-recherche\pipeline.log" 2>&1
```

La table `executions` (créée par `agent-de-recherche`) et la table `envois` (créée par `envoi-rapport-email`) fournissent en plus une journalisation structurée requêtable en SQL.

## Mise en place côté Cowork

La skill `schedule` de Cowork permet de planifier directement depuis Claude :

```
"Crée une tâche planifiée qui lance le pipeline de recherche d'emploi tous
les jours à 7h00 : agent-de-recherche, puis scoring-annonces, puis
dashboard-annonces, puis envoi-rapport-email."
```

Claude utilisera le tool `mcp__scheduled-tasks__create_scheduled_task` pour créer le cron et appellera les 4 skills en séquence.

## Premier démarrage — checklist

Avant la première exécution automatisée :

1. ✅ Lancer `agent-de-recherche` une fois manuellement pour créer `criteres.xlsx` et `annonces.db`.
2. ✅ Compléter `criteres.xlsx` avec tes vrais critères (mots-clés, salaire, ville, télétravail).
3. ✅ Renseigner `~/.agent-recherche/credentials.env` (au minimum `EMAIL_DESTINATAIRE` et les `SMTP_*` ou `EMAIL_MODE=ms365`).
4. ✅ Vérifier les credentials API si tu actives France Travail (voir `agent-de-recherche/references/credentials.md`).
5. ✅ Lancer **manuellement** une passe complète des 4 skills pour vérifier qu'aucune étape ne bloque.
6. ✅ Tester `send_report.py --dry-run` pour valider la composition du mail.
7. ✅ Une fois le rapport reçu → planifier le cron.

## Évolutions possibles (V2+)

- **Skill `sync-candidatures`** : 4ème skill légère qui importe le `localStorage` du navigateur (export JSON manuel, ou via une extension navigateur) vers la DB SQLite, pour avoir un suivi pérenne des candidatures cross-machine.
- **Skill `synthese-question`** : surveille `~/Téléchargements/` pour les fiches `.md` issues du bouton "Question Claude", les déplace automatiquement dans `questions-annonces/`, et notifie quand Cowork peut s'en saisir.
- **Skill `relance-recruteur`** : pour les annonces marquées "candidatée" il y a > 14 jours sans réponse, génère un email de relance et le pousse dans la boîte d'envoi en draft.
- **Skill `analyse-tendances`** : tous les mois, analyse `annonces.db` pour détecter les évolutions du marché (technos en hausse, salaires médians par région, etc.) et produire un rapport stratégique.

Chaque évolution serait une **nouvelle skill atomique** plutôt qu'une extension de l'existant — c'est ce qui rend le pipeline durable.
