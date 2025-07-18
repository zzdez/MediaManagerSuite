import requests
from flask import current_app

# --- NOUVEAU HELPER GÉNÉRIQUE ---
def _make_prowlarr_request(endpoint, params=None):
    """Fonction centralisée pour faire des requêtes à l'API Prowlarr."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')

    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL ou API Key non configuré.")
        return None

    # Construit l'URL en utilisant l'endpoint fourni
    url = f"{base_url}/api/v1/{endpoint.lstrip('/')}"
    
    request_params = {'apikey': api_key}
    if params:
        request_params.update(params)

    try:
        response = requests.get(url, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Erreur API Prowlarr pour endpoint '{endpoint}': {e}")
        return None

# --- FONCTION DE RECHERCHE (utilise maintenant le nouveau helper) ---
def search_prowlarr(query, categories=None, lang=None):
    """Recherche des releases sur Prowlarr."""
    effective_query = query
    if lang:
        lang_map = {'fr': 'FRENCH', 'en': 'ENGLISH'}
        lang_term = lang_map.get(lang)
        if lang_term:
            effective_query = f"{query} {lang_term}"
    
    params = {
        'query': effective_query,
        'type': 'search'
    }
    if categories:
        params['category'] = categories

    return _make_prowlarr_request('search', params)

# --- FONCTION DE CATÉGORIES (utilise le bon endpoint via le nouveau helper) ---
def get_prowlarr_categories():
    """Fetches all available categories from the Prowlarr API and formats them for the template."""
    # On appelle le bon endpoint : '/indexer/categories'
    all_categories = _make_prowlarr_request('indexer/categories')
    
    if not all_categories or not isinstance(all_categories, list):
        current_app.logger.error(f"Format de réponse inattendu ou vide pour les catégories Prowlarr. Réponse: {all_categories}")
        return []

    # Reformate la réponse pour que le template puisse l'utiliser
    formatted_categories = []
    for cat in all_categories:
        # Note: Le filtre agressif (if cat.get('id') % 1000 == 0) a été supprimé.
        # Nous traitons maintenant TOUTES les catégories renvoyées par l'API.

        sub_cats_formatted = []
        # La structure de la réponse pour subCategories est juste une liste de strings, pas d'objets.
        # Nous allons donc les ignorer pour l'instant pour assurer la stabilité.
        # Le template est déjà conçu pour gérer une liste 'subcat' vide.

        formatted_categories.append({
            '@attributes': {
                'id': str(cat.get('id')),
                'name': cat.get('name')
            },
            'subcat': [] # On laisse vide pour la compatibilité
        })

    return sorted(formatted_categories, key=lambda x: int(x['@attributes']['id']))