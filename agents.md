# Notes pour les agents IA

Ce fichier contient des informations importantes et des leçons apprises lors du développement de ce projet. Veuillez le consulter avant de commencer une nouvelle tâche.

## Points Techniques Clés

### Client TVDB (`app/utils/tvdb_client.py`)

-   **Gestion des traductions** : La fonction `get_series_details_by_id` doit gérer les traductions manquantes ou incomplètes de manière robuste. Si une traduction est demandée (par ex. en français) mais que les champs `name` ou `overview` de cette traduction sont vides ou ne contiennent que des espaces, le système **doit** utiliser les données de la langue originale (anglais) comme solution de secours. Cela évite d'envoyer des données vides au frontend.
-   **Intégrité des données** : Le dictionnaire retourné par `get_series_details_by_id` **doit** toujours contenir la clé `id` correspondant à l'ID TVDB de la série. Cet identifiant est crucial pour les opérations en aval, notamment pour le mappage et le téléchargement de médias. Son absence a déjà provoqué des régressions (erreur HTTP 400).

### Communication rTorrent (`app/utils/rtorrent_client.py`)

-   **Ne pas mélanger les protocoles** : Le client rTorrent de l'utilisateur fonctionne de manière fiable avec des commandes `httprpc` pour l'ajout de torrents, mais `xmlrpc` pour lister les torrents. Toute tentative de modifier ou de "moderniser" la méthode d'ajout en utilisant `xmlrpc` a provoqué des comportements instables (torrents en pause, échecs d'ajout silencieux). **Leçon :** Si une méthode de communication fonctionne, ne pas la changer. Isoler les nouvelles fonctionnalités (comme la récupération de hash par comparaison) de manière à ce qu'elles utilisent le protocole `xmlrpc` uniquement pour la lecture, sans interférer avec l'écriture (`httprpc`).
-   **Vérifier les dépendances d'import** : Lors de la restauration ou de la modification de fichiers utilitaires comme `rtorrent_client.py`, il est **impératif** de vérifier tous les autres modules qui l'importent (`seedbox_ui`, `search_ui`, etc.) pour s'assurer qu'aucune fonction renommée ou supprimée ne provoque une `ImportError`. Une recherche globale (grep) des noms de fonction est obligatoire avant de valider une telle modification.

### Éditeur Plex (`app/plex_editor/`)

-   **Déplacement de médias** : Il est désormais possible de déplacer un film ou une série vers un autre "root folder" directement depuis l'Éditeur Plex.
    -   **Frontend** (`plex_editor_ui.js`) : Un bouton "Déplacer" ouvre une modale. Cette modale appelle une API pour lister les dossiers racines disponibles. Après confirmation, elle envoie la commande de déplacement et lance un "polling" pour suivre le statut de la tâche. Le bouton se transforme en icône de chargement pendant l'opération.
    -   **Backend** (`routes.py`) : Trois nouvelles routes ont été créées : `/api/media/root_folders` (pour lister les dossiers), `/api/media/move` (pour lancer le déplacement via une commande `PUT` sur l'API Sonarr/Radarr avec `moveFiles=true`), et `/api/media/command/...` (pour suivre le statut de la tâche).

### Recherche & Téléchargement (`app/search_ui/`)

-   **Téléchargement par lots** : La page de recherche libre (`/search/`) permet désormais le téléchargement de plusieurs releases en une seule fois.
    -   **Frontend** (`app/static/js/search_logic.js`) :
        -   Des cases à cocher (`.release-checkbox`) sont ajoutées à chaque ligne de résultat.
        -   La fonction `updateBatchActions()` gère l'affichage d'un bouton de lot (`#batch-map-btn`) lorsque 2 releases ou plus sont sélectionnées. Elle désactive aussi les boutons de mappage individuels pour éviter les confusions.
        -   Lors du clic, le bouton de lot collecte les informations des releases sélectionnées et ouvre la modale de mappage.
    -   **Backend** (`app/search_ui/__init__.py`) :
        -   Une nouvelle route `/batch-download-and-map` a été créée pour gérer les requêtes de lot.
        -   La logique de traitement d'une release unique a été refactorisée dans une fonction `_process_single_release` pour être réutilisée.
        -   La route de lot boucle sur les releases et appelle `_process_single_release` pour chacune.
        -   Conformément à la demande, le processus s'arrête à la première erreur rencontrée.
