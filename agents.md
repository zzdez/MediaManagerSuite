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

## Note sur les Limitations de Test

En tant qu'agent de développement, je n'ai pas accès aux clés API réelles pour les services externes (Plex, Sonarr, Radarr, Prowlarr, TMDB, TheTVDB, etc.). Par conséquent, bien que je puisse écrire et exécuter des tests unitaires et des tests de logique interne, je ne peux pas effectuer de tests d'intégration de bout en bout qui dépendent de ces services. Par exemple, une recherche de média qui échoue à cause d'une clé API manquante est un comportement attendu dans mon environnement de test. L'utilisateur final est responsable de la validation de ces intégrations avec ses propres clés.

Cependant, les clés API pour **Gemini** et **YouTube** sont disponibles et peuvent être utilisées pour des fonctionnalités futures.

## Documentation des API

Pour faciliter le développement et la maintenance, voici les liens vers les documentations des principales API utilisées dans ce projet :

-   **Plex:** [python-plexapi.readthedocs.io](https://python-plexapi.readthedocs.io/en/stable/introduction.html)
-   **TheTVDB:** [thetvdb.github.io/v4-api/](https://thetvdb.github.io/v4-api/)
-   **TMDB:** [developer.themoviedb.org/docs/getting-started](https://developer.themoviedb.org/docs/getting-started)
-   **Prowlarr:** [prowlarr.com/docs/api/](https://prowlarr.com/docs/api/)
-   **Sonarr:** [sonarr.tv/docs/api/](https://sonarr.tv/docs/api/)
-   **Radarr:** [radarr.video/docs/api/](https://radarr.video/docs/api/)

## Composants Clés et Concepts

- **`pending_torrents_map.json`**: Le "cerveau" de l'application. Ce fichier est la source de vérité unique pour toutes les opérations de téléchargement et d'importation en cours. Il fonctionne comme une machine à états.
- **`mapping_manager.py`**: Le gardien du `pending_torrents_map.json`. Toute interaction avec ce fichier DOIT passer par ce manager pour garantir l'intégrité des données (notamment via `FileLock`).
- **Workers Asynchrones (`sftp_scanner`, `staging_processor`)**: Scripts exécutés en arrière-plan (via APScheduler) qui gèrent la détection, le rapatriement (SFTP) et l'importation des fichiers. Ils sont coordonnés via les statuts dans `pending_torrents_map.json`.
- **Identifiants Externes (`tmdb_id`, `tvdb_id`)**: La source de vérité pour l'identification des médias. Toute nouvelle fonctionnalité de cache ou de mapping doit utiliser ces identifiants comme clés primaires pour garantir la cohérence et la fiabilité.
- **`trailer_database.json`**: La base de données centralisée pour toutes les informations relatives aux bandes-annonces. Elle stocke les résultats de recherche mis en cache et, surtout, les bandes-annonces verrouillées par l'utilisateur.
- **`trailer_manager.py`**: Le gardien du `trailer_database.json`. Toute interaction avec les données des bandes-annonces (recherche, verrouillage, nettoyage du cache) doit passer par ce manager.
- **`media_info_manager.py`**: Le "Tableau de Bord" centralisé pour un média. Ce manager a pour unique responsabilité d'agréger des informations complètes sur un film ou une série en interrogeant Plex, Sonarr, Radarr et TMDB. Il est conçu pour être la source unique de vérité pour des questions comme "Ce média est-il présent dans Plex ?" ou "Cette série est-elle encore en production ?".
- **API `/api/agent/media/details/<media_type>/<external_id>`**: Le point d'accès unique pour récupérer les informations agrégées par le `media_info_manager`. Il doit être utilisé par toute fonctionnalité frontend ayant besoin d'un aperçu détaillé d'un média.

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

---
## Journal des Sessions

### **Session du 2025-10-14 (Partie 2) : Implémentation du Tableau de Bord Média**
Cette session a introduit une nouvelle fonctionnalité majeure visant à fournir des informations contextuelles détaillées sur les médias lors de la recherche de bandes-annonces.

1.  **Création du `MediaInfoManager` (`app/utils/media_info_manager.py`)**:
    *   **Rôle**: Un nouveau service centralisé a été créé pour agréger des données provenant de multiples sources (Plex, Sonarr, Radarr, TMDB).
    *   **Fonctionnalité**: Il peut déterminer si un média est présent dans les bibliothèques, s'il possède des fichiers physiques, son statut de visionnage sur Plex (y compris via des tags personnalisés comme `vu`), et son statut de production (terminé ou en cours).
    *   **Optimisation**: Le manager charge en mémoire les listes complètes de Sonarr et Radarr au premier appel pour minimiser les requêtes API lors des vérifications ultérieures.

2.  **Nouveau Point d'API (`/api/agent/media/details/...`)**:
    *   Une nouvelle route a été ajoutée pour exposer les fonctionnalités du `MediaInfoManager` au frontend de manière propre et réutilisable.

3.  **Intégration dans la Modale de Bande-Annonce**:
    *   **Problème**: La modale de recherche de bandes-annonces manquait de contexte sur le statut du média.
    *   **Solution**: Le fichier `global_trailer_search.js` a été mis à jour pour appeler le nouveau point d'API à chaque ouverture de la modale. Un "tableau de bord" d'informations est maintenant affiché dynamiquement au-dessus des résultats, informant l'utilisateur du statut du média sur Plex, Sonarr, Radarr, etc., avant même de lancer la recherche de bande-annonce.

### **Session du 2025-10-14 : Amélioration de l'UX des Bandes-Annonces**

Cette session a porté sur l'amélioration de l'expérience utilisateur de la fonctionnalité de recherche de bandes-annonces autonome, accessible depuis le menu latéral.

1.  **Correction du Bug de Superposition des Modales :**
    *   **Problème :** La modale du lecteur vidéo (`#trailer-modal`) s'ouvrait derrière la modale de recherche (`#standalone-trailer-search-modal`), obligeant l'utilisateur à fermer manuellement la première pour voir la seconde.
    *   **Solution :** Une approche purement CSS (`z-index`) s'étant révélée insuffisante, la logique a été déplacée dans le JavaScript (`global_trailer_search.js`). Désormais, la modale de recherche est explicitement cachée avant l'ouverture de la modale de sélection des bandes-annonces, et une logique de "retour" a été implémentée pour la réafficher lorsque l'utilisateur a terminé, assurant un flux fluide et sans superposition.

2.  **Enrichissement des Résultats de Recherche :**
    *   **Problème :** Les résultats dans la modale de recherche de bandes-annonces étaient minimalistes (titre et année seulement).
    *   **Solution :** La fonction `renderStandaloneResults` a été mise à jour pour afficher des résultats enrichis, incluant le poster du média, un synopsis tronqué, et une mise en page plus claire, s'alignant sur l'apparence des autres pages de recherche de l'application pour une meilleure cohérence visuelle.
---
### **Session du 2025-10-12 : Finalisation de la Gestion des Bandes-Annonces**
Cette session a permis de finaliser l'implémentation d'un système de gestion de bandes-annonces complet et visuellement cohérent.

#### Architecture et Logique Backend
1. **Centralisation du Statut :** La logique de statut a été centralisée dans `app/utils/trailer_manager.py` via une nouvelle fonction `get_trailer_status(media_type, external_id)`. Elle retourne un des trois états : `'LOCKED'`, `'UNLOCKED'`, ou `'NONE'`. Cette fonction est maintenant la méthode de référence pour vérifier l'état d'une bande-annonce.
2. **Enrichissement des API :** Toutes les routes API retournant des listes de médias ont été mises à jour pour inclure le champ `trailer_status`. Cela concerne : * `/api/media/search` (Recherche Média) * `/api/search/lookup` (Modale de Mapping) * `/api/media_items` (Éditeur Plex) * `/api/series_details` (Modale de gestion des séries)
3. **Lecture Directe :** Une nouvelle route `/api/agent/get_locked_trailer_id` a été créée pour récupérer directement l'ID d'une vidéo verrouillée, permettant une lecture instantanée sans passer par la modale de sélection.

#### Interface et Expérience Utilisateur
1. **Système de Couleurs :** Un système de couleurs `btn-outline-*` a été appliqué de manière cohérente : * `btn-outline-success` (Vert) pour `LOCKED`. * `btn-outline-primary` (Bleu) pour `UNLOCKED`. * `btn-outline-danger` (Rouge) pour `NONE`.
2. **Icônes Unifiées :** L'icône `bi-film` est maintenant utilisée sur tous les boutons de bande-annonce pour une meilleure cohérence visuelle.
3. **Recherche Autonome :** Le bouton "Bandes-annonces" du menu latéral est désormais fonctionnel. Il ouvre une modale de recherche dédiée (`#standalone-trailer-search-modal`) gérée par `global_trailer_search.js`. Cette fonctionnalité réutilise l'API `/search_ui/api/media/search` et le système d'événements globaux (`openTrailerSearch`) pour une intégration transparente.
4. **Nettoyage :** L'ancienne fonctionnalité de résumé des bandes-annonces, son template (`_trailer_summary_modal.html`) et sa route API (`/api/plex_editor/trailers/summary`) ont été entièrement supprimés.