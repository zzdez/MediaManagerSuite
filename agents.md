# Notes pour les agents IA

Ce fichier contient des informations importantes et des leçons apprises lors du développement de ce projet. Veuillez le consulter avant de commencer une nouvelle tâche.

## Points Techniques Clés

### Client TVDB (`app/utils/tvdb_client.py`)

-   **Gestion des traductions** : La fonction `get_series_details_by_id` doit gérer les traductions manquantes ou incomplètes de manière robuste. Si une traduction est demandée (par ex. en français) mais que les champs `name` ou `overview` de cette traduction sont vides ou ne contiennent que des espaces, le système **doit** utiliser les données de la langue originale (anglais) comme solution de secours. Cela évite d'envoyer des données vides au frontend.
-   **Intégrité des données** : Le dictionnaire retourné par `get_series_details_by_id` **doit** toujours contenir la clé `id` correspondant à l'ID TVDB de la série. Cet identifiant est crucial pour les opérations en aval, notamment pour le mappage et le téléchargement de médias. Son absence a déjà provoqué des régressions (erreur HTTP 400).
