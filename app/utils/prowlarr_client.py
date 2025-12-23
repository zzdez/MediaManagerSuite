import requests
from flask import current_app
import logging
from datetime import timezone, datetime

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

def get_latest_from_prowlarr(categories, min_date=None, search_mode=False):
    """
    Fetches all new releases from Prowlarr since a given date using robust pagination.
    It stops only when an entire page of results is older than the target date.

    Args:
        categories (list): List of category IDs.
        min_date (datetime): The cutoff date for fetching items.
        search_mode (bool): If True, forces a wildcard search query ('*') to bypass RSS caching.

    IMPORTANT: Uses 'offset' and 'limit' instead of 'page'/'pageSize' to prevent
    infinite loops on indexers that ignore 'page' for RSS feeds.
    """
    logging.info(f"--- Starting Prowlarr Fetch (Robust Pagination) ---")
    logging.info(f"Fetching new releases since: {min_date} (Search Mode: {search_mode})")

    all_releases = []

    # Configuration limits
    max_pages = current_app.config.get('PROWLARR_MAX_PAGES', 50)
    limit = 100
    max_offset = max_pages * limit
    offset = 0

    # Generic search query (wildcard) from config to allow user override if needed.
    # Default is empty string (""), which triggers RSS mode for most indexers.
    # If the user sets this to "*", it triggers Search mode.
    # If search_mode is True (forced retry), we use "*"
    search_query = "*" if search_mode else current_app.config.get('PROWLARR_SEARCH_QUERY', "")

    while offset < max_offset:
        current_page_num = (offset // limit) + 1

        # We use 'sortKey' and 'sortDir' which are the standard Arr API parameters for sorting.
        # We use 'offset' and 'limit' to guarantee correct pagination.
        params = {
            'type': 'search',
            'offset': offset,
            'limit': limit,
            'sortKey': 'publishDate',
            'sortDir': 'desc'
        }

        # IMPORTANT: Only add 'query' if it's strictly NOT empty.
        # Prowlarr treats an empty string query ("") same as None (RSS mode),
        # BUT explicitly sending query="" might cause issues with some indexers.
        # If the user provides "*", we send it.
        if search_query:
            params['query'] = search_query

        if categories:
            params['cat'] = ','.join(map(str, categories))

        logging.info(f"Requesting Prowlarr Offset: {offset} (Page equivalent: {current_page_num}/{max_pages})...")
        response_data = _make_prowlarr_request('search', params)

        if response_data is None:
            logging.error(f"Prowlarr request failed for offset {offset}. Stopping.")
            break
        if not isinstance(response_data, list) or not response_data:
            logging.info(f"Offset {offset} (Page {current_page_num}) is empty or invalid. Stopping pagination.")
            break

        # Extract dates for logging debugging
        first_date = "N/A"
        last_date = "N/A"
        if response_data:
             d1 = response_data[0].get('publishDate')
             d2 = response_data[-1].get('publishDate')
             if d1: first_date = d1
             if d2: last_date = d2

        logging.info(f"  -> Offset {offset} returned {len(response_data)} results. First item date: {first_date}, Last item date: {last_date}")
        all_releases.extend(response_data)

        if min_date:
            try:
                if min_date.tzinfo is None:
                    min_date = min_date.replace(tzinfo=timezone.utc)

                page_dates = []
                for r in response_data:
                    date_str = r.get('publishDate')
                    if date_str:
                        if date_str.endswith('Z'):
                            page_dates.append(datetime.fromisoformat(date_str.replace('Z', '+00:00')))
                        else:
                            page_dates.append(datetime.fromisoformat(date_str))

                # Check if all items on this page are older than min_date
                if page_dates and all(d < min_date for d in page_dates):
                    # SAFETY CHECK: If this is the FIRST page (offset 0), checking "all older" is dangerous
                    # if Prowlarr returned cached/stale data or if the local state is ahead (future timestamp).

                    if offset == 0:
                        logging.warning(f"  [Time Gap Detected] The newest item from Prowlarr ({page_dates[0]}) is OLDER than your last local refresh ({min_date}).")

                        if not search_mode:
                            logging.warning("  -> RSS feed appears stale. Switching to Search Mode ('*') to force fresh results from indexers.")
                            return get_latest_from_prowlarr(categories, min_date, search_mode=True)
                        else:
                            logging.warning("  -> Gap detected even in Search Mode. This implies genuine data gap or misconfigured date. IGNORING date filter for this run to force data recovery.")
                            # Disable the min_date filter for the rest of this run to ensure we capture the available data.
                            min_date = None
                    else:
                        logging.info(f"  -> All items on offset {offset} are older than {min_date}. Stopping pagination.")
                        break
            except (ValueError, TypeError) as e:
                logging.error(f"Date parsing error on offset {offset}. Stopping pagination to be safe. Error: {e}")
                break

        offset += limit

    if offset >= max_offset:
        logging.warning(f"Reached max offset limit of {max_offset} ({max_pages} pages). This can be configured with PROWLARR_MAX_PAGES. Results may be incomplete.")

    logging.info(f"--- Prowlarr Fetch Complete ---")
    logging.info(f"Total items fetched from Prowlarr before final filtering: {len(all_releases)}")

    if min_date:
        # Final, definitive filtering in memory
        filtered_releases = [
            r for r in all_releases
            if r.get('publishDate') and datetime.fromisoformat(r['publishDate'].replace('Z', '+00:00')) > min_date
        ]
        logging.info(f"Total items after final filtering for dates > {min_date}: {len(filtered_releases)}")
        return filtered_releases

    return all_releases

def get_prowlarr_applications():
    """
    Fetches the applications (Sonarr, Radarr, etc.) configured in Prowlarr.
    This is useful for getting the category IDs associated with each app.
    """
    response_data = _make_prowlarr_request('applications')

    if isinstance(response_data, list):
        current_app.logger.info(f"Prowlarr: Successfully fetched {len(response_data)} applications.")
        return response_data
    else:
        current_app.logger.error("Prowlarr: Failed to fetch applications or the response was not a list.")
        return None
