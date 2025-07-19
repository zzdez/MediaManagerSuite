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
    [HYBRID STRATEGY] Fetches the master list of all categories from Prowlarr,
    then enriches it with which active indexer supports each category.
    This is the definitive method to get all sub-categories.
    """
    try:
        # Étape 1: Récupérer la liste maîtresse complète de TOUTES les catégories
        current_app.logger.info("Prowlarr: Fetching master category list from /api/v1/category...")
        master_categories = _make_prowlarr_request('category')
        if not master_categories:
            raise ValueError("Could not fetch the master category list from Prowlarr.")

        # Crée une carte pour un accès rapide, initialisant chaque catégorie avec une liste d'indexers vide.
        # Format: { "cat_id": {"id": "...", "name": "...", "indexers": []} }
        all_categories_map = {
            str(cat['id']): {
                'id': str(cat['id']),
                'name': cat['name'],
                'indexers': []
            } for cat in master_categories
        }
        current_app.logger.info(f"Prowlarr: Master list contains {len(all_categories_map)} categories.")

        # Étape 2: Récupérer tous les indexers pour l'enrichissement
        current_app.logger.info("Prowlarr: Fetching all enabled indexers to enrich the category list...")
        indexers = _make_prowlarr_request('indexer')
        if not indexers:
            raise ValueError("The indexer list from Prowlarr is empty or unreachable.")

        for indexer in indexers:
            indexer_id = indexer.get('id')
            indexer_name = indexer.get('name')

            if not indexer.get('enable', False) or not indexer_id or not indexer_name:
                continue

            # Étape 3: Utiliser les 'capabilities' uniquement pour savoir ce que l'indexer supporte
            current_app.logger.debug(f"Prowlarr: Enriching with capabilities from indexer '{indexer_name}' (ID: {indexer_id}).")
            indexer_details = _make_prowlarr_request(f'indexer/{indexer_id}')
            
            if indexer_details and 'capabilities' in indexer_details and 'categories' in indexer_details['capabilities']:
                # On récupère les ID de toutes les catégories (mères et filles) que l'indexer annonce supporter
                supported_cat_ids = {str(cat['id']) for cat in indexer_details['capabilities']['categories']}

                # Pour chaque catégorie supportée, on ajoute le badge à notre liste maîtresse
                for cat_id in supported_cat_ids:
                    if cat_id in all_categories_map:
                        if indexer_name not in all_categories_map[cat_id]['indexers']:
                            all_categories_map[cat_id]['indexers'].append(indexer_name)

        final_list = list(all_categories_map.values())
        sorted_list = sorted(final_list, key=lambda x: int(x['id']))

        current_app.logger.info(f"Prowlarr: Enriched list contains {len(sorted_list)} categories.")
        return sorted_list

    except Exception as e:
        current_app.logger.error(f"Failed to fetch and merge Prowlarr categories with hybrid strategy: {e}", exc_info=True)
        return []