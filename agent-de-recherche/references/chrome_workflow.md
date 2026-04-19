# Workflow Chrome MCP — sites sans API

Pour LinkedIn, APEC, Welcome to the Jungle, HelloWork (et Indeed si activé),
la skill utilise les outils `mcp__Claude_in_Chrome__*` pour piloter le
navigateur de l'utilisateur.

## Règles d'or

1. **Jamais de mot de passe en dur** — l'utilisateur doit déjà être connecté
2. **Cadence respectueuse** — 1 requête toutes les 2-3 secondes par site, jamais plus
3. **Périmètre limité** — uniquement les pages de résultats correspondant aux
   critères, pas un crawl exhaustif
4. **Détection de login** — si la page redirige vers `/login`, `/signin` ou
   contient un formulaire d'authentification, **arrêter** et signaler à
   l'utilisateur

## Séquence type pour un site

```
1. navigate → URL de recherche construite à partir des critères
   (ex LinkedIn : https://www.linkedin.com/jobs/search/?keywords=Directeur+de+projet&location=Paris)

2. read_page → vérifier qu'on est bien sur la page de résultats
                (sinon : login requis, alerter l'utilisateur)

3. get_page_text → récupérer le texte intégral

4. Pour chaque carte d'annonce détectée dans le texte :
   - extraire URL, titre, entreprise, lieu
   - construire un AnnonceCollectee minimal

5. (Optionnel) Pour les annonces qui matchent les obligatoires sur le titre seul :
   - navigate vers l'URL de l'annonce
   - get_page_text pour récupérer la description complète
   - réévaluer le matcher
   - sleep 2-3s avant l'annonce suivante

6. Page suivante : naviguer vers `?start=25`, `&page=2`, etc. selon le site,
   limiter à 3-5 pages par site pour rester raisonnable
```

## Construction des URLs de recherche par site

### LinkedIn
```
https://www.linkedin.com/jobs/search/?keywords=<MOTS-CLES>&location=<VILLE>&f_WT=2
```
- `keywords` : mots-clés URL-encodés, séparés par `+`
- `location` : ville simple
- `f_WT=2` : filtre télétravail (1=sur site, 2=hybride, 3=full remote)

### APEC
```
https://www.apec.fr/candidat/recherche-emploi.html?motsCles=<MOTS-CLES>&lieux=<DEPT>
```
Voir la doc Apec pour les codes département.

### Welcome to the Jungle
```
https://www.welcometothejungle.com/fr/jobs?query=<MOTS-CLES>&aroundQuery=<VILLE>
```

### HelloWork
```
https://www.hellowork.com/fr-fr/emploi/recherche.html?k=<MOTS-CLES>&l=<VILLE>
```

### Indeed (si activé en plus d'Adzuna)
```
https://fr.indeed.com/jobs?q=<MOTS-CLES>&l=<VILLE>
```

## Pseudo-code à suivre dans la skill

```python
for source in criteres.sources_actives():
    if source.methode != "Chrome":
        continue

    url = construire_url_de_recherche(source.source, criteres)
    mcp__Claude_in_Chrome__navigate(url=url)

    page = mcp__Claude_in_Chrome__read_page()
    if est_page_de_login(page):
        prevenir_utilisateur(f"{source.source} : reconnexion requise")
        continue  # passer au site suivant, ne pas bloquer toute la passe

    texte = mcp__Claude_in_Chrome__get_page_text()
    cartes = extraire_cartes_annonces(texte, source=source.source)

    for carte in cartes:
        result = matcher.evaluer(carte.titre + " " + carte.extrait, criteres)
        if result.match:
            annonce = AnnonceCollectee(
                url=carte.url, source=source.source,
                titre=carte.titre, entreprise=carte.entreprise,
                criteres_matches=result.criteres_matches, match_global=True,
            )
            stocker(db_path, [annonce], execution_id=exec_id)

    sleep(3)  # respect du rate-limit entre sites
```

## Détecter une page de login

Indicateurs concrets dans le texte récupéré :
- présence des mots `Sign in`, `Connexion`, `Se connecter`, `Login`
- URL contenant `/login`, `/signin`, `/uas/login`, `/connexion`
- absence des mots-clés caractéristiques d'une page résultats (`offres`, `jobs`, `résultats`)

En cas de doute, demander à l'utilisateur plutôt que de continuer à l'aveugle.
