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

def _get_torznab_capabilities_xml(feed_id):
    """Fetches the capabilities XML from a specific Torznab feed ID."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')
    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL or API Key not configured for Torznab API.")
        return None

    torznab_url = f"{base_url}/{feed_id}/api"
    params = {'t': 'caps', 'apikey': api_key}

    try:
        response = requests.get(torznab_url, params=params, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr Torznab caps request for feed ID {feed_id} failed: {e}")
        return None

def get_prowlarr_categories():
    """
    [DYNAMIC DISCOVERY STRATEGY] Dynamically finds the 'All Indexers' feed ID, then
    fetches and parses its Torznab capabilities XML to get the definitive category list.
    """
    try:
        # Étape 1: Trouver dynamiquement l'ID du flux "All Indexers".
        current_app.logger.info("Prowlarr: Dynamically discovering 'All Indexers' feed ID...")
        all_feeds = _make_prowlarr_json_request('indexer')
        if not all_feeds:
            raise ValueError("Could not fetch the list of indexers/feeds from Prowlarr.")

        all_indexers_feed_id = None
        for feed in all_feeds:
            # L'API peut retourner des indexers ou des "feeds". On cherche le feed "All Indexers".
            if feed.get('name') == 'All Indexers' and feed.get('protocol') == 'torznab':
                all_indexers_feed_id = feed.get('id')
                break

        if all_indexers_feed_id is None:
            raise ValueError("Could not dynamically find the 'All Indexers' Torznab feed. Please ensure it exists and is enabled in Prowlarr.")

        current_app.logger.info(f"Prowlarr: Found 'All Indexers' feed ID: {all_indexers_feed_id}")

        # Étape 2: Obtenir le XML des capacités en utilisant le bon ID.
        xml_data = _get_torznab_capabilities_xml(all_indexers_feed_id)
        if not xml_data:
            raise ValueError(f"Failed to get XML data from Torznab caps for feed ID {all_indexers_feed_id}.")

        # Étape 3: Parser le XML pour construire la liste maîtresse.
        root = ET.fromstring(xml_data)
        all_categories_map = {}
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

        # Le reste de la logique d'enrichissement n'est plus nécessaire car Torznab est la source de vérité.
        # On peut la réactiver plus tard si on veut les badges, mais pour l'instant, la priorité est d'afficher la liste COMPLÈTE.

        final_list = list(all_categories_map.values())
        return sorted(final_list, key=lambda x: int(x['id']))

    except Exception as e:
        current_app.logger.error(f"Prowlarr category processing failed with DYNAMIC DISCOVERY strategy: {e}", exc_info=True)
        return []

def search_prowlarr(query, categories=None, lang=None):
    """(Unchanged) Searches Prowlarr using its JSON API."""
    effective_query = query
    # ... (le reste de la fonction est inchangé)
    params = {'query': effective_query, 'type': 'search'}
    if categories:
        params['category'] = categories
    return _make_prowlarr_json_request('search', params)
