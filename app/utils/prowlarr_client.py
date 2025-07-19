import requests
from flask import current_app

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
    try:
        current_app.logger.info("Prowlarr: Fetching all indexers to correctly parse capabilities...")
        indexers = _make_prowlarr_request('indexer')
        if not indexers:
            raise ValueError("The indexer list from Prowlarr is empty or unreachable.")

        # Dictionnaire pour agréger toutes les catégories et leurs indexers.
        all_categories_map = {}

        def parse_categories_recursive(categories, indexer_name, parent_name=""):
            """Helper function to recursively parse categories and subcategories."""
            for cat in categories:
                cat_id_str = str(cat.get('id'))
                cat_name = cat.get('name', '').strip()

                # Ignore les catégories malformées (ex: ID 100xxx sans nom)
                if not cat_id_str or not cat_name:
                    continue

                # Construit le nom complet (ex: "TV/HD")
                full_name = f"{parent_name}/{cat_name}" if parent_name and not cat_name.startswith(parent_name) else cat_name

                # Initialise la catégorie si elle n'a jamais été vue
                if cat_id_str not in all_categories_map:
                    all_categories_map[cat_id_str] = {
                        'id': cat_id_str,
                        'name': full_name,
                        'indexers': []
                    }

                # Ajoute l'indexer actuel à la liste de cette catégorie
                if indexer_name not in all_categories_map[cat_id_str]['indexers']:
                    all_categories_map[cat_id_str]['indexers'].append(indexer_name)

                # LA PARTIE CRUCIALE : L'appel récursif pour les sous-catégories
                if 'subCategories' in cat and cat['subCategories']:
                    parse_categories_recursive(cat['subCategories'], indexer_name, parent_name=cat_name)

        # Itère sur chaque indexer actif et lance le parsing
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
    """(Unchanged) Searches Prowlarr using its JSON API."""
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
