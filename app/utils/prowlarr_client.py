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

    response_data = _make_prowlarr_request('search', params)

    # L'API de recherche retourne une liste d'objets torrents directement.
    # Il est bon de s'assurer que nous retournons bien une liste.
    if isinstance(response_data, list):
        return response_data
    else:
        current_app.logger.warning(f"Prowlarr search for query '{query}' did not return a list.")
        return []

from datetime import datetime, timezone

def get_latest_from_prowlarr(categories, min_date=None):
    """
    Fetches ALL latest releases from Prowlarr since a given date using pagination.
    This version uses page/pageSize and stops fetching when releases are older than min_date.
    """
    all_releases = []
    page = 1
    pageSize = 100

    while True:
        params = {
            'type': 'search',
            'page': page,
            'pageSize': pageSize,
            'sort': 'publishDate', # Ensure results are sorted by date
            'order': 'desc'
        }

        if categories and isinstance(categories, list) and len(categories) > 0:
            params['cat'] = ','.join(map(str, categories))

        response_data = _make_prowlarr_request('search', params)

        if response_data is None:
            current_app.logger.error(f"Prowlarr request failed for page {page}. Returning partial results.")
            return all_releases # Return what we have so far

        if isinstance(response_data, list) and response_data:
            all_releases.extend(response_data)

            # --- Intelligent stop condition ---
            # Get the publish date of the OLDEST item in the current page
            oldest_item_date_str = response_data[-1].get('publishDate')
            if oldest_item_date_str:
                oldest_item_date = datetime.fromisoformat(oldest_item_date_str.replace('Z', '+00:00'))
                if min_date and oldest_item_date < min_date:
                    # current_app.logger.info(f"Prowlarr: Stopping pagination on page {page} because oldest item ({oldest_item_date}) is older than min_date ({min_date}).")
                    break
            # ---

            if len(response_data) < pageSize:
                # current_app.logger.info(f"Prowlarr: Stopping pagination on page {page} because received less than a full page.")
                break

            page += 1
        else:
            # current_app.logger.info(f"Prowlarr: Stopping pagination on page {page} because no more results were returned.")
            break

    # Final filtering of the aggregated results
    if min_date:
        all_releases = [
            r for r in all_releases
            if datetime.fromisoformat(r['publishDate'].replace('Z', '+00:00')) > min_date
        ]

    return all_releases

def get_prowlarr_applications():
    """
    Fetches the applications (Sonarr, Radarr, etc.) configured in Prowlarr.
    This is useful for getting the category IDs associated with each app.
    """
    response_data = _make_prowlarr_request('applications')
    
    # The response is a list of application objects.
    if isinstance(response_data, list):
        current_app.logger.info(f"Prowlarr: Successfully fetched {len(response_data)} applications.")
        return response_data
    else:
        current_app.logger.error("Prowlarr: Failed to fetch applications or the response was not a list.")
        return None
    