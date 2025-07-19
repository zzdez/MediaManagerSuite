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
    [INTERPRETATION STRATEGY] Fetches the master list of all category definitions,
    then interprets each indexer's capabilities as category families (e.g., 2000 implies 2000-2999)
    to correctly associate all sub-categories.
    """
    try:
        # Étape 1: Récupérer la liste maîtresse de TOUTES les définitions de catégories.
        current_app.logger.info("Prowlarr: Fetching master category definitions from /api/v1/definitions/categories...")
        master_definitions = _make_prowlarr_request('definitions/categories')
        if not master_definitions:
            raise ValueError("Could not fetch the master category definitions from Prowlarr. Check Prowlarr version and connectivity.")

        # Crée notre carte de base, prête à être enrichie.
        all_categories_map = {
            str(cat['id']): {
                'id': str(cat['id']),
                'name': cat['name'],
                'indexers': []
            } for cat in master_definitions
        }
        current_app.logger.info(f"Prowlarr: Master definitions list contains {len(all_categories_map)} categories.")

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

            # Étape 3: Utiliser les 'capabilities' comme des indices de familles.
            current_app.logger.debug(f"Prowlarr: Interpreting capabilities for indexer '{indexer_name}' (ID: {indexer_id}).")
            indexer_details = _make_prowlarr_request(f'indexer/{indexer_id}')
            
            if not (indexer_details and 'capabilities' in indexer_details and 'categories' in indexer_details['capabilities']):
                continue

            # On récupère les ID parents que l'indexer supporte (ex: ['2000', '5000'])
            supported_parent_ids = {str(cat['id']) for cat in indexer_details['capabilities']['categories']}

            # Étape 4: Enrichissement intelligent de la liste maîtresse.
            for cat_id, category_data in all_categories_map.items():
                cat_id_int = int(cat_id)

                # Vérifie si la catégorie appartient à une des familles supportées
                is_supported = False
                if 2000 <= cat_id_int < 3000 and '2000' in supported_parent_ids: is_supported = True
                elif 5000 <= cat_id_int < 6000 and '5000' in supported_parent_ids: is_supported = True
                # Ajoutez d'autres familles au besoin (ex: 1000 pour 'Console', 3000 pour 'Audio', etc.)
                # elif 1000 <= cat_id_int < 2000 and '1000' in supported_parent_ids: is_supported = True

                if is_supported:
                    if indexer_name not in category_data['indexers']:
                        category_data['indexers'].append(indexer_name)

        final_list = list(all_categories_map.values())
        sorted_list = sorted(final_list, key=lambda x: int(x['id']))

        current_app.logger.info(f"Prowlarr: Successfully enriched list of {len(sorted_list)} categories.")
        return sorted_list

    except Exception as e:
        current_app.logger.error(f"Prowlarr category processing failed with interpretation strategy: {e}", exc_info=True)
        return []