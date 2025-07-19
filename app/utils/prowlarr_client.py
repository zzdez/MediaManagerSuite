# app/utils/prowlarr_client.py
import requests
from flask import current_app

def _make_prowlarr_request(endpoint, params=None):
    # ... (Cette fonction est déjà correcte)
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')
    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL or API Key not configured.")
        return None
    url = f"{base_url}/api/v1/{endpoint.lstrip('/')}"
    request_params = {'apikey': api_key}
    if params:
        request_params.update(params)
    try:
        response = requests.get(url, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr API request for endpoint '{endpoint}' failed: {e}")
        return None

def search_prowlarr(query, categories=None, lang=None):
    # ... (Cette fonction est déjà correcte)
    effective_query = query
    if lang:
        lang_map = {'fr': 'FRENCH', 'en': 'ENGLISH'}
        lang_term = lang_map.get(lang)
        if lang_term:
            effective_query = f"{query} {lang_term}"
    params = {'query': effective_query, 'type': 'search'}
    if categories:
        params['category'] = categories
    return _make_prowlarr_request('search', params)

def get_prowlarr_categories():
    """
    [MULTI-INDEXER] Fetches and merges categories from ALL enabled indexers.
    """
    try:
        current_app.logger.info("Prowlarr: Récupération de tous les indexers pour fusionner les catégories...")
        indexers = _make_prowlarr_request('indexer')
        if not indexers: raise ValueError("La liste des indexers est vide.")

        all_categories_map = {} # Utilise un dictionnaire pour éviter les doublons par ID

        for indexer in indexers:
            indexer_id = indexer.get('id')
            if not indexer.get('enable', False) or not indexer_id:
                continue # Ignore les indexers désactivés

            current_app.logger.debug(f"Prowlarr: Récupération des catégories pour l'indexer ID {indexer_id} ({indexer.get('name')}).")
            indexer_details = _make_prowlarr_request(f'indexer/{indexer_id}')
            
            if indexer_details and 'capabilities' in indexer_details and 'categories' in indexer_details['capabilities']:
                for cat in indexer_details['capabilities']['categories']:
                    cat_id_str = str(cat.get('id'))
                    if cat_id_str not in all_categories_map and cat.get('name'):
                        all_categories_map[cat_id_str] = {
                            '@attributes': {
                                'id': cat_id_str,
                                'name': cat.get('name')
                            }
                        }
        
        if not all_categories_map:
            raise ValueError("Aucune catégorie n'a pu être récupérée d'aucun indexer.")

        # Convertit le dictionnaire en liste et trie par ID
        final_list = list(all_categories_map.values())
        current_app.logger.info(f"Prowlarr: {len(final_list)} catégories uniques trouvées sur tous les indexers.")
        return sorted(final_list, key=lambda x: int(x['@attributes']['id']))

    except Exception as e:
        current_app.logger.error(f"Échec de la récupération multi-indexer des catégories: {e}", exc_info=True)
        return []