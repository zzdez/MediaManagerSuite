# MediaManagerSuite (MMS) - Guide pour l'Agent de Développement

Ce document sert de guide pour toute intervention sur le projet MediaManagerSuite. Il a pour but de préserver la cohérence, la stabilité et la vision à long terme de l'application.

## Mission Principale

MediaManagerSuite (MMS) est une application web conçue pour rationaliser et automatiser la gestion d'une médiathèque personnelle. Sa mission est de faire le pont entre la recherche de contenu (films et séries), son téléchargement via une seedbox (rTorrent), et son organisation finale dans les bibliothèques gérées par Sonarr et Radarr, en vue d'une lecture sur Plex.

## Architecture Globale

- **Backend**: Python avec le micro-framework Flask.
- **Frontend**: HTML, CSS (Bootstrap), et JavaScript (jQuery).
- **Structure**: L'application est une monolithique modulaire qui suit le pattern "Application Factory". Le code est organisé par fonctionnalités dans des **Blueprints** (ex: `search_ui`, `seedbox_ui`).
- **Logique Métier**: La logique réutilisable (clients API, processeurs de tâches) est centralisée dans le répertoire `app/utils`.
- **Interaction Frontend/Backend**: Le frontend communique principalement avec le backend via des requêtes **AJAX** vers les points de terminaison de l'API Flask (souvent préfixés par `/api/...`).

## Règles d'Or (Non Négociables)

Ces règles doivent être respectées scrupuleusement lors de toute modification du code.

1.  **PAS DE SUPPOSITIONS** : Toute modification doit se baser sur le code existant et fonctionnel. En cas de doute, il est impératif de demander des clarifications plutôt que d'interpréter.
2.  **NE PAS RÉINVENTER LA ROUE** : L'application est riche en fonctionnalités. La priorité est de réutiliser, d'adapter et d'étendre le code existant avant d'écrire une nouvelle logique. Cherchez d'abord dans `app/utils` et les Blueprints existants.
3.  **ÉVITER LES RÉGRESSIONS À TOUT PRIX** : Chaque nouvelle fonctionnalité doit être implémentée de la manière la moins intrusive possible pour ne pas casser ce qui fonctionne déjà. Une phase d'investigation et d'analyse d'impact doit toujours précéder une phase de modification.

## Composants Clés et Concepts

- **`pending_torrents_map.json`**: Le "cerveau" de l'application. Ce fichier est la source de vérité unique pour toutes les opérations de téléchargement et d'importation en cours. Il fonctionne comme une machine à états.
- **`mapping_manager.py`**: Le gardien du `pending_torrents_map.json`. Toute interaction avec ce fichier DOIT passer par ce manager pour garantir l'intégrité des données (notamment via `FileLock`).
- **Workers Asynchrones (`sftp_scanner`, `staging_processor`)**: Scripts exécutés en arrière-plan (via APScheduler) qui gèrent la détection, le rapatriement (SFTP) et l'importation des fichiers. Ils sont coordonnés via les statuts dans `pending_torrents_map.json`.
- **Identifiants Externes (`tmdb_id`, `tvdb_id`)**: La source de vérité pour l'identification des médias. Toute nouvelle fonctionnalité de cache ou de mapping doit utiliser ces identifiants comme clés primaires pour garantir la cohérence et la fiabilité.
- **`trailer_database.json`**: La base de données centralisée pour toutes les informations relatives aux bandes-annonces. Elle stocke les résultats de recherche mis en cache et, surtout, les bandes-annonces verrouillées par l'utilisateur.
- **`trailer_manager.py`**: Le gardien du `trailer_database.json`. Toute interaction avec les données des bandes-annonces (recherche, verrouillage, nettoyage du cache) doit passer par ce manager.

### **Logique de Gestion des Bandes-Annonces : La Recette**

Pour garantir la performance et la cohérence, toute fonctionnalité liée aux bandes-annonces doit suivre cette logique :

1.  **Pour Afficher le Statut d'un Verrou (ex: bouton vert dans une liste)** :
    *   **Utiliser `trailer_manager.is_trailer_locked(media_type, external_id)`**.
    *   Cette fonction est "légère" : elle ne fait qu'une lecture rapide du fichier JSON et ne déclenche **jamais** d'appel API. C'est la méthode à privilégier pour les vues de liste pour ne pas impacter les performances.

2.  **Pour Lancer une Recherche de Bande-Annonce (ex: clic sur le bouton "Bande-annonce")** :
    *   **Utiliser `trailer_manager.get_trailer_info(media_type, external_id, title, year)`**.
    *   Cette fonction est "lourde" : elle vérifie d'abord le cache. Si les résultats sont présents et récents, elle les retourne. Sinon, elle lance une recherche sur YouTube et met en cache la liste complète des résultats.
    *   **Ne jamais appeler cette fonction en boucle sur une liste de médias.**

3.  **Pour Verrouiller une Bande-Annonce** :
    *   **Utiliser `trailer_manager.lock_trailer(media_type, external_id, video_data)`**.
    *   Cette fonction sauvegarde les données de la vidéo choisie et, pour garder la base de données propre, **purge automatiquement tous les autres résultats de recherche** qui étaient en cache pour ce média.

En respectant cette "recette", nous assurons une expérience utilisateur fluide, une consommation d'API maîtrisée et une base de données pertinente.