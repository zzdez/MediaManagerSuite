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
    [MULTI-INDEXER AGGREGATION] Fetches and merges categories from ALL enabled indexers,
    associating each category with the indexers that provide it.
    """
    try:
        current_app.logger.info("Prowlarr: Fetching all enabled indexers to merge categories...")
        indexers = _make_prowlarr_request('indexer')
        if not indexers:
            raise ValueError("The indexer list from Prowlarr is empty or unreachable.")

        # Dictionnaire pour agréger les catégories et leurs indexers.
        # Format: { "cat_id": {"id": "...", "name": "...", "indexers": ["name1", "name2"]} }
        all_categories_map = {}

        for indexer in indexers:
            indexer_id = indexer.get('id')
            indexer_name = indexer.get('name')

            # Ignore les indexers désactivés ou sans ID/nom
            if not indexer.get('enable', False) or not indexer_id or not indexer_name:
                continue

            current_app.logger.debug(f"Prowlarr: Fetching capabilities for indexer '{indexer_name}' (ID: {indexer_id}).")
            indexer_details = _make_prowlarr_request(f'indexer/{indexer_id}')
            
            if indexer_details and 'capabilities' in indexer_details and 'categories' in indexer_details['capabilities']:
                for cat in indexer_details['capabilities']['categories']:
                    cat_id_str = str(cat.get('id'))
                    cat_name = cat.get('name')

                    if not cat_id_str or not cat_name:
                        continue # Ignore les catégories malformées

                    # Si la catégorie n'a jamais été vue, on l'initialise
                    if cat_id_str not in all_categories_map:
                        all_categories_map[cat_id_str] = {
                            'id': cat_id_str,
                            'name': cat_name,
                            'indexers': [] # Initialise la liste des indexers
                        }

                    # On ajoute l'indexer actuel à la liste de cette catégorie
                    if indexer_name not in all_categories_map[cat_id_str]['indexers']:
                        all_categories_map[cat_id_str]['indexers'].append(indexer_name)

        if not all_categories_map:
            raise ValueError("No valid categories could be retrieved from any enabled indexer.")

        final_list = list(all_categories_map.values())
        sorted_list = sorted(final_list, key=lambda x: int(x['id']))

        current_app.logger.info(f"Prowlarr: Found {len(sorted_list)} unique categories across all enabled indexers.")
        return sorted_list

    except Exception as e:
        current_app.logger.error(f"Failed to fetch and merge Prowlarr categories: {e}", exc_info=True)
        return []