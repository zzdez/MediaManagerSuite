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

### **Logique de Suppression rTorrent**

En raison de restrictions imposées par le fournisseur de la seedbox, la suppression des données de torrents ne peut pas se faire via l'API XML-RPC de rTorrent (`d.delete_tied`). Par conséquent, **toute suppression de données doit impérativement passer par SFTP**.

- **Fonction Clé** : `_sftp_delete_recursive` dans `app/utils/rtorrent_client.py`.
- **Compatibilité des Chemins** : Le serveur SFTP attend des chemins avec des **slashes (`/`)** comme séparateurs. Lors de la construction de chemins pour les opérations SFTP, il est crucial de ne pas utiliser `os.path.join` ou `pathlib.Path` qui dépendent de l'OS, mais de forcer l'utilisation de slashes pour garantir la compatibilité.

## Session du 2025-10-12 : Finalisation de la Gestion des Bandes-Annonces Cette session a permis de finaliser l'implémentation d'un système de gestion de bandes-annonces complet et visuellement cohérent. ### Architecture et Logique Backend 1. **Centralisation du Statut :** La logique de statut a été centralisée dans `app/utils/trailer_manager.py` via une nouvelle fonction `get_trailer_status(media_type, external_id)`. Elle retourne un des trois états : `'LOCKED'`, `'UNLOCKED'`, ou `'NONE'`. Cette fonction est maintenant la méthode de référence pour vérifier l'état d'une bande-annonce. 2. **Enrichissement des API :** Toutes les routes API retournant des listes de médias ont été mises à jour pour inclure le champ `trailer_status`. Cela concerne : * `/api/media/search` (Recherche Média) * `/api/search/lookup` (Modale de Mapping) * `/api/media_items` (Éditeur Plex) * `/api/series_details` (Modale de gestion des séries) 3. **Lecture Directe :** Une nouvelle route `/api/agent/get_locked_trailer_id` a été créée pour récupérer directement l'ID d'une vidéo verrouillée, permettant une lecture instantanée sans passer par la modale de sélection. ### Interface et Expérience Utilisateur 1. **Système de Couleurs :** Un système de couleurs `btn-outline-*` a été appliqué de manière cohérente : * `btn-outline-success` (Vert) pour `LOCKED`. * `btn-outline-primary` (Bleu) pour `UNLOCKED`. * `btn-outline-danger` (Rouge) pour `NONE`. 2. **Icônes Unifiées :** L'icône `bi-film` est maintenant utilisée sur tous les boutons de bande-annonce pour une meilleure cohérence visuelle. 3. **Recherche Autonome :** Le bouton "Bandes-annonces" du menu latéral est désormais fonctionnel. Il ouvre une modale de recherche dédiée (`#standalone-trailer-search-modal`) gérée par `global_trailer_search.js`. Cette fonctionnalité réutilise l'API `/search_ui/api/media/search` et le système d'événements globaux (`openTrailerSearch`) pour une intégration transparente. 4. **Nettoyage :** L'ancienne fonctionnalité de résumé des bandes-annonces, son template (`_trailer_summary_modal.html`) et sa route API (`/api/plex_editor/trailers/summary`) ont été entièrement supprimés. 


Client TVDB (app/utils/tvdb_client.py)
Gestion des traductions : La fonction get_series_details_by_id doit gérer les traductions manquantes ou incomplètes de manière robuste. Si une traduction est demandée (par ex. en français) mais que les champs name ou overview de cette traduction sont vides ou ne contiennent que des espaces, le système doit utiliser les données de la langue originale (anglais) comme solution de secours. Cela évite d'envoyer des données vides au frontend.
Intégrité des données : Le dictionnaire retourné par get_series_details_by_id doit toujours contenir la clé id correspondant à l'ID TVDB de la série. Cet identifiant est crucial pour les opérations en aval, notamment pour le mappage et le téléchargement de médias. Son absence a déjà provoqué des régressions (erreur HTTP 400).
Communication rTorrent (app/utils/rtorrent_client.py)
Ne pas mélanger les protocoles : Le client rTorrent de l'utilisateur fonctionne de manière fiable avec des commandes httprpc pour l'ajout de torrents, mais xmlrpc pour lister les torrents. Toute tentative de modifier ou de "moderniser" la méthode d'ajout en utilisant xmlrpc a provoqué des comportements instables (torrents en pause, échecs d'ajout silencieux). Leçon : Si une méthode de communication fonctionne, ne pas la changer. Isoler les nouvelles fonctionnalités (comme la récupération de hash par comparaison) de manière à ce qu'elles utilisent le protocole xmlrpc uniquement pour la lecture, sans interférer avec l'écriture (httprpc).
Vérifier les dépendances d'import : Lors de la restauration ou de la modification de fichiers utilitaires comme rtorrent_client.py, il est impératif de vérifier tous les autres modules qui l'importent (seedbox_ui, search_ui, etc.) pour s'assurer qu'aucune fonction renommée ou supprimée ne provoque une ImportError. Une recherche globale (grep) des noms de fonction est obligatoire avant de valider une telle modification.
Recherche & Téléchargement (app/search_ui/)
Téléchargement par lots : La page de recherche libre (/search/) permet désormais le téléchargement de plusieurs releases en une seule fois.
Frontend (app/static/js/search_logic.js) :
Des cases à cocher (.release-checkbox) sont ajoutées à chaque ligne de résultat.
La fonction updateBatchActions() gère l'affichage d'un bouton de lot (#batch-map-btn) lorsque 2 releases ou plus sont sélectionnées. Elle désactive aussi les boutons de mappage individuels pour éviter les confusions.
Lors du clic, le bouton de lot collecte les informations des releases sélectionnées et ouvre la modale de mappage.
Backend (app/search_ui/__init__.py) :
Une nouvelle route /batch-download-and-map a été créée pour gérer les requêtes de lot.
La logique de traitement d'une release unique a été refactorisée dans une fonction _process_single_release pour être réutilisée.
La route de lot boucle sur les releases et appelle _process_single_release pour chacune.
Conformément à la demande, le processus s'arrête à la première erreur rencontrée.


### Fiabilisation des Processus par Lots

Lors du développement du téléchargement par lot, plusieurs leçons importantes ont été apprises pour garantir la stabilité et éviter de surcharger les services externes comme rTorrent.

1.  **Gestion Individuelle des Erreurs** : Un processus par lot qui interagit avec une API externe ne doit pas s'arrêter complètement à la première erreur.
    *   **Problème** : Si une seule release sur dix échoue, l'approche initiale bloquait les neuf autres.
    *   **Solution** : Chaque appel (par exemple, chaque téléchargement) doit être encapsulé dans un bloc `try...except`. Le processus principal doit continuer même en cas d'échec d'un élément, et collecter les résultats (succès et échecs).

2.  **Introduction de Pauses (Throttling)** : Les appels rapides et successifs à une même API peuvent être interprétés comme une attaque par déni de service (DoS) ou simplement surcharger le service cible, provoquant des échecs en cascade.
    *   **Problème** : L'envoi de multiples commandes d'ajout à rTorrent en l'espace de quelques millisecondes a probablement causé l'échec silencieux de certains ajouts.
    *   **Solution** : Introduire une courte pause (par exemple, `time.sleep(1)`) entre chaque appel dans une boucle de traitement par lot. Cette temporisation simple mais efficace laisse le temps au service de traiter chaque requête individuellement.

3.  **Retour Détaillé à l'Utilisateur** : Pour une meilleure expérience utilisateur et un débogage facilité, il est crucial de fournir un rapport complet à la fin d'un processus par lot.
    *   **Problème** : Un simple message "Opération terminée" masque les échecs partiels.
    *   **Solution** : Le backend doit retourner une structure de données (par exemple, une liste d'objets JSON) détaillant le résultat de chaque opération. Le frontend doit ensuite interpréter ces données pour afficher un résumé clair, séparant les succès des échecs et affichant les messages d'erreur pertinents.
