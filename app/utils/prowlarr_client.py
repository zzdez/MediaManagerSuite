import requests
from flask import current_app
import logging
from datetime import datetime, timezone

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
    if categories and isinstance(categories, list) and len(categories) > 0:
        params['cat'] = ','.join(map(str, categories))
        current_app.logger.info(f"Prowlarr search: Using categories {params['cat']}")
    response_data = _make_prowlarr_request('search', params)
    if isinstance(response_data, list):
        return response_data
    else:
        current_app.logger.warning(f"Prowlarr search for query '{query}' did not return a list.")
        return []

def get_latest_from_prowlarr(categories, min_date=None):
    """
    [DEBUG VERSION] Fetches latest releases from Prowlarr using pagination with a HARD LIMIT.
    This version logs extensively to help diagnose missing results.
    """
    logging.info(f"--- Starting Prowlarr Fetch ---")
    logging.info(f"Fetching new releases since: {min_date}")

    all_releases = []
    page = 1
    pageSize = 100
    max_pages = 10  # Hard limit to prevent infinite loops

    while page <= max_pages:
        params = {
            'type': 'search',
            'page': page,
            'pageSize': pageSize,
            'sort': 'publishDate',
            'order': 'desc'
        }

        if categories and isinstance(categories, list) and len(categories) > 0:
            params['cat'] = ','.join(map(str, categories))

        logging.info(f"Requesting Prowlarr Page: {page}/{max_pages}...")
        response_data = _make_prowlarr_request('search', params)

        if response_data is None:
            logging.error(f"Prowlarr request failed for page {page}. Stopping.")
            break

        if isinstance(response_data, list):
            num_results = len(response_data)
            logging.info(f"  -> Page {page} returned {num_results} results.")

            if not response_data:
                logging.info(f"  -> Page {page} is empty. Stopping pagination.")
                break

            all_releases.extend(response_data)
            logging.info(f"  -> Total results so far: {len(all_releases)}")
            page += 1
        else:
            logging.warning(f"Prowlarr fetch for page {page} did not return a list. Stopping.")
            break

    logging.info(f"--- Prowlarr Fetch Complete ---")
    logging.info(f"Total items fetched from Prowlarr before date filtering: {len(all_releases)}")

    if min_date:
        filtered_releases = []
        for r in all_releases:
            try:
                # Prowlarr dates can be in ISO format with 'Z' or timezone info
                publish_date_str = r.get('publishDate')
                if not publish_date_str:
                    logging.warning(f"Skipping torrent with missing publishDate: {r.get('title', 'N/A')}")
                    continue

                # More robust date parsing
                if publish_date_str.endswith('Z'):
                    publish_date = datetime.fromisoformat(publish_date_str.replace('Z', '+00:00'))
                else:
                    publish_date = datetime.fromisoformat(publish_date_str)

                # Ensure our min_date is also timezone-aware for correct comparison
                if min_date.tzinfo is None:
                    min_date = min_date.replace(tzinfo=timezone.utc)

                if publish_date > min_date:
                    filtered_releases.append(r)
            except (ValueError, TypeError) as e:
                logging.warning(f"Could not parse date '{r.get('publishDate')}' for torrent '{r.get('title', 'N/A')}'. Skipping. Error: {e}")
                pass

        logging.info(f"Total items after filtering for dates > {min_date}: {len(filtered_releases)}")
        return filtered_releases

    logging.info(f"No min_date provided. Returning all {len(all_releases)} fetched items.")
    return all_releases

def get_prowlarr_applications():
    """
    Fetches the applications (Sonarr, Radarr, etc.) configured in Prowlarr.
    """
    response_data = _make_prowlarr_request('applications')
    if isinstance(response_data, list):
        current_app.logger.info(f"Prowlarr: Successfully fetched {len(response_data)} applications.")
        return response_data
    else:
        current_app.logger.error("Prowlarr: Failed to fetch applications or the response was not a list.")
        return None
