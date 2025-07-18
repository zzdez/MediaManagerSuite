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
    """
    [VERSION FINALE GARANTIE] Fetches all categories by querying the details
    of the first available indexer and using the correct data path.
    """
    try:
        indexers = _make_prowlarr_request('indexer')
        if not indexers: raise ValueError("La liste des indexers est vide.")

        first_indexer_id = indexers[0].get('id')
        if not first_indexer_id: raise ValueError("Le premier indexer n'a pas d'ID.")
        
        current_app.logger.info(f"Prowlarr: Récupération des catégories via l'indexer ID {first_indexer_id}.")
        indexer_details = _make_prowlarr_request(f'indexer/{first_indexer_id}')

        # --- CORRECTION FINALE : Utiliser le bon chemin d'accès ---
        if not indexer_details or 'capabilities' not in indexer_details or 'categories' not in indexer_details['capabilities']:
            raise ValueError("Le chemin 'capabilities.categories' est manquant dans la réponse de l'API.")
        
        all_categories = indexer_details['capabilities']['categories']
        # --- FIN DE LA CORRECTION ---

        current_app.logger.info(f"Prowlarr: {len(all_categories)} catégories trouvées avec succès.")
        
        formatted_categories = []
        for cat in all_categories:
            # On ne prend que les catégories avec un nom pour éviter les erreurs
            if cat.get('name'):
                formatted_categories.append({
                    '@attributes': {
                        'id': str(cat.get('id')),
                        'name': cat.get('name')
                    }
                })
        
        return sorted(formatted_categories, key=lambda x: int(x['@attributes']['id']))

    except Exception as e:
        current_app.logger.error(f"Échec de la récupération des catégories: {e}", exc_info=True)
        return []