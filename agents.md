# Notes pour les agents IA

Ce fichier contient des informations importantes et des leçons apprises lors du développement de ce projet. Veuillez le consulter avant de commencer une nouvelle tâche.

## Points Techniques Clés

### Client TVDB (`app/utils/tvdb_client.py`)

-   **Gestion des traductions** : La fonction `get_series_details_by_id` doit gérer les traductions manquantes ou incomplètes de manière robuste. Si une traduction est demandée (par ex. en français) mais que les champs `name` ou `overview` de cette traduction sont vides ou ne contiennent que des espaces, le système **doit** utiliser les données de la langue originale (anglais) comme solution de secours. Cela évite d'envoyer des données vides au frontend.
-   **Intégrité des données** : Le dictionnaire retourné par `get_series_details_by_id` **doit** toujours contenir la clé `id` correspondant à l'ID TVDB de la série. Cet identifiant est crucial pour les opérations en aval, notamment pour le mappage et le téléchargement de médias. Son absence a déjà provoqué des régressions (erreur HTTP 400).

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
