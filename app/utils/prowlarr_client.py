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
    [DOCUMENTATION-BASED STRATEGY] Fetches the master list of all categories from the official
    '/api/v1/indexer/categories' endpoint, then enriches it by interpreting each indexer's
    capabilities to associate all relevant sub-categories.
    """
    try:
        # Étape 1: Appeler l'endpoint officiel et vérifié pour obtenir la liste maîtresse.
        current_app.logger.info("Prowlarr: Fetching master category list from CORRECT endpoint: /api/v1/indexer/categories...")
        master_categories = _make_prowlarr_request('indexer/categories')
        if not master_categories:
            raise ValueError("Could not fetch the master category list from '/api/v1/indexer/categories'.")

        # Crée notre carte de base, prête à être enrichie.
        all_categories_map = {
            str(cat['id']): {
                'id': str(cat['id']),
                'name': cat['name'],
                'indexers': []
            } for cat in master_categories
        }
        current_app.logger.info(f"Prowlarr: Master list contains {len(all_categories_map)} categories.")

        # Étape 2: Récupérer tous les indexers pour l'enrichissement.
        current_app.logger.info("Prowlarr: Fetching enabled indexers to interpret their capabilities...")
        indexers = _make_prowlarr_request('indexer')
        if not indexers:
            current_app.logger.warning("Prowlarr: The indexer list is empty. No categories will be associated with indexers.")
            return sorted(list(all_categories_map.values()), key=lambda x: int(x['id']))

        for indexer in indexers:
            indexer_id = indexer.get('id')
            indexer_name = indexer.get('name')

            if not indexer.get('enable', False) or not indexer_id or not indexer_name:
                continue

            current_app.logger.debug(f"Prowlarr: Interpreting capabilities for indexer '{indexer_name}' (ID: {indexer_id}).")
            indexer_details = _make_prowlarr_request(f'indexer/{indexer_id}')
            
            if not (indexer_details and 'capabilities' in indexer_details and 'categories' in indexer_details['capabilities']):
                continue

            # Étape 3: Interpréter les 'capabilities' comme des familles de catégories.
            supported_parent_ids = {str(cat['id']) for cat in indexer_details['capabilities']['categories']}

            # Étape 4: Enrichissement intelligent de la liste maîtresse.
            for cat_id, category_data in all_categories_map.items():
                cat_id_int = int(cat_id)

                # Vérifie si la catégorie appartient à une des familles supportées.
                # Cette logique reste la plus robuste pour associer les sous-catégories.
                is_supported = False
                if 2000 <= cat_id_int < 3000 and '2000' in supported_parent_ids: is_supported = True
                elif 5000 <= cat_id_int < 6000 and '5000' in supported_parent_ids: is_supported = True
                elif 8000 <= cat_id_int < 9000 and '8000' in supported_parent_ids: is_supported = True # Books
                elif 1000 <= cat_id_int < 2000 and '1000' in supported_parent_ids: is_supported = True # Console
                elif 3000 <= cat_id_int < 4000 and '3000' in supported_parent_ids: is_supported = True # Audio
                elif 4000 <= cat_id_int < 5000 and '4000' in supported_parent_ids: is_supported = True # PC
                elif 7000 <= cat_id_int < 8000 and '7000' in supported_parent_ids: is_supported = True # XXX

                if is_supported:
                    if indexer_name not in category_data['indexers']:
                        category_data['indexers'].append(indexer_name)

        final_list = list(all_categories_map.values())
        sorted_list = sorted(final_list, key=lambda x: int(x['id']))

        current_app.logger.info(f"Prowlarr: Successfully enriched list of {len(sorted_list)} categories using the official API endpoint.")
        return sorted_list

    except Exception as e:
        current_app.logger.error(f"Prowlarr category processing failed with DOCUMENTATION-BASED strategy: {e}", exc_info=True)
        return []