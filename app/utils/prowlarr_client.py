import requests
from flask import current_app
import logging # Ajout de logging pour une meilleure visibilité

def _make_prowlarr_request(endpoint, params=None):
    """Makes a request to Prowlarr's internal JSON API."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')
    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL or API Key not configured for JSON API.")
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
        current_app.logger.error(f"Prowlarr JSON API request for endpoint '{endpoint}' failed: {e}")
        return None

def get_prowlarr_categories():
    """
    [CORRECT PARSING STRATEGY] Fetches all indexers and recursively parses their
    'capabilities' objects, including the nested 'subCategories', to build the
    complete and definitive category list.
    """
    # ... CETTE FONCTION RESTE INCHANGÉE ET FONCTIONNELLE ...
    try:
        current_app.logger.info("Prowlarr: Fetching all indexers to correctly parse capabilities...")
        indexers = _make_prowlarr_request('indexer')
        if not indexers:
            raise ValueError("The indexer list from Prowlarr is empty or unreachable.")
        all_categories_map = {}
        def parse_categories_recursive(categories, indexer_name, parent_name=""):
            for cat in categories:
                cat_id_str = str(cat.get('id'))
                cat_name = cat.get('name', '').strip()
                if not cat_id_str or not cat_name:
                    continue
                full_name = f"{parent_name}/{cat_name}" if parent_name and not cat_name.startswith(parent_name) else cat_name
                if cat_id_str not in all_categories_map:
                    all_categories_map[cat_id_str] = {
                        'id': cat_id_str,
                        'name': full_name,
                        'indexers': []
                    }
                if indexer_name not in all_categories_map[cat_id_str]['indexers']:
                    all_categories_map[cat_id_str]['indexers'].append(indexer_name)
                if 'subCategories' in cat and cat['subCategories']:
                    parse_categories_recursive(cat['subCategories'], indexer_name, parent_name=cat_name)
        for indexer in indexers:
            indexer_name = indexer.get('name')
            if not indexer.get('enable', False) or not indexer_name:
                continue
            if 'capabilities' in indexer and 'categories' in indexer['capabilities']:
                current_app.logger.debug(f"Parsing categories for enabled indexer: '{indexer_name}'")
                parse_categories_recursive(indexer['capabilities']['categories'], indexer_name)
        if not all_categories_map:
            raise ValueError("No valid categories could be parsed from any enabled indexer.")
        final_list = list(all_categories_map.values())
        sorted_list = sorted(final_list, key=lambda x: int(x['id']))
        current_app.logger.info(f"Prowlarr: Successfully parsed {len(sorted_list)} unique categories from all indexers.")
        return sorted_list
    except Exception as e:
        current_app.logger.error(f"Prowlarr category processing failed with CORRECT parsing strategy: {e}", exc_info=True)
        return []

def search_prowlarr(query, categories=None, lang=None):
    """
    Recherche des releases sur Prowlarr, avec support optionnel pour les catégories.
    """
    params = {
        'query': query,
        'type': 'search'
    }

    # Si des catégories sont fournies, les ajouter à la requête.
    # Le paramètre API correct est 'cat' et il attend une chaîne de caractères séparée par des virgules.
    if categories and isinstance(categories, list) and len(categories) > 0:
        params['cat'] = ','.join(map(str, categories))
        current_app.logger.info(f"Prowlarr search: Using categories {params['cat']}")

    # La gestion de la langue est retirée ici, car elle sera gérée par le filtrage guessit.

    return _make_prowlarr_request('search', params)

def get_latest_from_prowlarr(categories, limit=200):
    """
    Fetches the latest releases from Prowlarr for given categories.
    Prowlarr's default sort is by publish date descending, so no query
    and a limit should give us the most recent items.
    """
    params = {
        'type': 'search',
        'limit': limit,
        'offset': 0
    }

    if categories and isinstance(categories, list) and len(categories) > 0:
        params['cat'] = ','.join(map(str, categories))
        current_app.logger.info(f"Prowlarr latest fetch: Using categories {params['cat']} with limit {limit}")

    return _make_prowlarr_request('search', params)