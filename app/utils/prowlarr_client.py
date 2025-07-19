import requests
import xml.etree.ElementTree as ET
from flask import current_app

def _make_prowlarr_json_request(endpoint, params=None):
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

def _get_torznab_capabilities_xml():
    """Fetches the capabilities XML from the 'All Indexers' Torznab endpoint."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')
    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL or API Key not configured for Torznab API.")
        return None

    # The '1' is the default feed ID for 'All Indexers'. This is standard in Prowlarr.
    torznab_url = f"{base_url}/1/api"
    params = {'t': 'caps', 'apikey': api_key}

    try:
        response = requests.get(torznab_url, params=params, timeout=30)
        response.raise_for_status()
        # Return the raw text content for XML parsing
        return response.text
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr Torznab caps request failed: {e}")
        return None

def get_prowlarr_categories():
    """
    [TORZNAB STRATEGY] Fetches the complete category list from the Torznab 'caps'
    endpoint, which is the definitive source of truth, then enriches it.
    """
    try:
        # Étape 1: Obtenir le XML des capacités de Torznab.
        current_app.logger.info("Prowlarr: Fetching capabilities from Torznab endpoint (t=caps)...")
        xml_data = _get_torznab_capabilities_xml()
        if not xml_data:
            raise ValueError("Failed to get XML data from Torznab capabilities endpoint.")

        # Étape 2: Parser le XML pour construire la liste maîtresse.
        root = ET.fromstring(xml_data)
        all_categories_map = {}

        # Le chemin est <caps><categories><category><subcat>
        categories_node = root.find('categories')
        if categories_node is None:
            raise ValueError("'<categories>' node not found in Torznab XML response.")

        for category in categories_node.findall('category'):
            cat_id = category.get('id')
            cat_name = category.get('name')
            if cat_id and cat_name:
                 all_categories_map[cat_id] = {'id': cat_id, 'name': cat_name, 'indexers': []}
            
            for subcat in category.findall('subcat'):
                subcat_id = subcat.get('id')
                subcat_name = subcat.get('name')
                if subcat_id and subcat_name:
                    full_name = f"{cat_name}/{subcat_name}"
                    all_categories_map[subcat_id] = {'id': subcat_id, 'name': full_name, 'indexers': []}

        current_app.logger.info(f"Prowlarr: Successfully parsed {len(all_categories_map)} categories from Torznab XML.")

        # Étape 3: Enrichir avec les badges d'indexers (logique existante et robuste).
        current_app.logger.info("Prowlarr: Fetching enabled indexers to enrich the category list...")
        indexers = _make_prowlarr_json_request('indexer')
        if not indexers:
            current_app.logger.warning("Could not fetch indexer list for enrichment. Badges will be missing.")
        else:
            for indexer in indexers:
                indexer_id = indexer.get('id')
                indexer_name = indexer.get('name')
                if not (indexer.get('enable', False) and indexer_id and indexer_name):
                    continue

                indexer_details = _make_prowlarr_json_request(f'indexer/{indexer_id}')
                if not (indexer_details and 'capabilities' in indexer_details and 'categories' in indexer_details['capabilities']):
                    continue

                supported_parent_ids = {str(cat['id']) for cat in indexer_details['capabilities']['categories']}

                for cat_id, category_data in all_categories_map.items():
                    cat_id_int = int(cat_id)
                    is_supported = False
                    if 2000 <= cat_id_int < 3000 and '2000' in supported_parent_ids: is_supported = True
                    elif 5000 <= cat_id_int < 6000 and '5000' in supported_parent_ids: is_supported = True

                    if is_supported:
                        if indexer_name not in category_data['indexers']:
                            category_data['indexers'].append(indexer_name)

        final_list = list(all_categories_map.values())
        return sorted(final_list, key=lambda x: int(x['id']))

    except Exception as e:
        current_app.logger.error(f"Prowlarr category processing failed with TORZNAB strategy: {e}", exc_info=True)
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
    return _make_prowlarr_json_request('search', params)
