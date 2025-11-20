from flask import render_template, jsonify, current_app, request
from app.dashboard import dashboard_bp
import json
import os
from datetime import datetime, timezone
import re
import requests

# Import Prowlarr client
from app.utils.prowlarr_client import get_latest_from_prowlarr, get_prowlarr_applications
# Import TMDB client for ID conversion
from app.utils.tmdb_client import TheMovieDBClient
# Import Arr client for checking existing media and parsing names
from app.utils.arr_client import get_sonarr_series_by_guid, get_radarr_movie_by_guid, parse_media_name
# Import mapping manager to check pending torrents
from app.utils.mapping_manager import get_all_torrent_hashes
# Import the new status manager
from app.utils.status_manager import get_media_statuses

# Define paths for our state files
DASHBOARD_STATE_FILE = os.path.join('instance', 'dashboard_state.json')
DASHBOARD_IGNORED_FILE = os.path.join('instance', 'dashboard_ignored.json')

# --- Helper functions for state management ---

def get_last_refresh_time():
    """Reads the timestamp of the last refresh from the state file."""
    if not os.path.exists(DASHBOARD_STATE_FILE):
        return None
    try:
        with open(DASHBOARD_STATE_FILE, 'r') as f:
            data = json.load(f)
            # Timestamps are stored in ISO 8601 format, make it timezone-aware
            iso_ts = data.get('last_refresh_utc')
            return datetime.fromisoformat(iso_ts).replace(tzinfo=timezone.utc) if iso_ts else None
    except (json.JSONDecodeError, IOError):
        return None

def set_last_refresh_time():
    """Saves the current UTC time as the last refresh timestamp."""
    os.makedirs(os.path.dirname(DASHBOARD_STATE_FILE), exist_ok=True)
    now_utc = datetime.now(timezone.utc)
    with open(DASHBOARD_STATE_FILE, 'w') as f:
        json.dump({'last_refresh_utc': now_utc.isoformat()}, f)
    return now_utc

def get_ignored_hashes():
    """Reads the set of ignored torrent hashes."""
    if not os.path.exists(DASHBOARD_IGNORED_FILE):
        return set()
    try:
        with open(DASHBOARD_IGNORED_FILE, 'r') as f:
            return set(json.load(f))
    except (json.JSONDecodeError, IOError):
        return set()

def add_ignored_hash(torrent_hash):
    """Adds a torrent hash to the ignored file."""
    ignored_hashes = get_ignored_hashes()
    ignored_hashes.add(torrent_hash)
    os.makedirs(os.path.dirname(DASHBOARD_IGNORED_FILE), exist_ok=True)
    with open(DASHBOARD_IGNORED_FILE, 'w') as f:
        # Convert set to list for JSON serialization
        json.dump(list(ignored_hashes), f)
    current_app.logger.info(f"Added hash {torrent_hash} to ignored list.")

# --- Routes ---

@dashboard_bp.route('/dashboard')
def dashboard():
    """
    Dashboard page - loads torrents from our persistent store and prepares keyword filters.
    """
    DASHBOARD_TORRENTS_FILE = os.path.join('instance', 'dashboard_torrents.json')

    torrents = []
    if os.path.exists(DASHBOARD_TORRENTS_FILE):
        try:
            with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
                torrents = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            current_app.logger.error(f"Could not read or parse dashboard_torrents.json: {e}")
            torrents = []

    # --- Prepare keyword filters from environment variables ---
    keyword_filters = {
        "Langue": {"type": "alias", "terms": {}},
        "Qualité": {"type": "simple", "terms": []},
        "Codec": {"type": "simple", "terms": []},
        "Source": {"type": "simple", "terms": []},
        "Release Group": {"type": "simple", "terms": []}
    }

    # Process JSON-based language filters (priority)
    languages_json = current_app.config.get('SEARCH_FILTER_LANGUAGES')
    if languages_json:
        try:
            lang_terms = json.loads(languages_json)
            if isinstance(lang_terms, dict):
                keyword_filters["Langue"]["terms"] = lang_terms
            else:
                current_app.logger.warning("SEARCH_FILTER_LANGUAGES is not a valid JSON dictionary.")
        except json.JSONDecodeError:
            current_app.logger.error("Failed to decode SEARCH_FILTER_LANGUAGES JSON.")

    # Process simple list filters (for other categories)
    simple_filter_map = {
        'SEARCH_FILTER_QUALITY_LIST': 'Qualité',
        'SEARCH_FILTER_CODEC_LIST': 'Codec',
        'SEARCH_FILTER_SOURCE_LIST': 'Source',
        'SEARCH_FILTER_RELEASE_GROUP_LIST': 'Release Group'
    }
    for env_var, group_name in simple_filter_map.items():
        value = current_app.config.get(env_var)
        if value:
            keyword_filters[group_name]["terms"] = [term.strip() for term in str(value).split(',')]

    # Clean up empty filter groups
    keyword_filters = {k: v for k, v in keyword_filters.items() if v["terms"]}

    return render_template('dashboard/index.html', torrents=torrents, keyword_filters=keyword_filters)


@dashboard_bp.route('/dashboard/api/refresh')
def refresh_torrents():
    """
    API endpoint to refresh the torrent list. It fetches the latest from Prowlarr,
    merges them with the existing list, marks new ones, and saves the updated list.
    """
    DASHBOARD_TORRENTS_FILE = os.path.join('instance', 'dashboard_torrents.json')
    MAX_TORRENTS_TO_KEEP = 1000

    try:
        # Step 1: Load existing torrents
        existing_torrents = []
        if os.path.exists(DASHBOARD_TORRENTS_FILE):
            try:
                with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
                    existing_torrents = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass  # Start fresh if file is corrupt or unreadable

        # Step 2: Mark all existing torrents as not new and create a lookup map
        existing_torrents_map = {}
        for torrent in existing_torrents:
            torrent['is_new'] = False
            # The 'publishDate' might be a string, convert it for sorting
            if isinstance(torrent.get('publishDate'), str):
                 torrent['publishDate'] = datetime.fromisoformat(torrent['publishDate'].replace('Z', '+00:00'))
            existing_torrents_map[torrent['hash']] = torrent

        # Step 3: Fetch new torrents from Prowlarr
        prowlarr_categories = current_app.config.get('DASHBOARD_PROWLARR_CATEGORIES', [])
        raw_torrents_from_prowlarr = get_latest_from_prowlarr(prowlarr_categories)

        if raw_torrents_from_prowlarr is None:
            return jsonify({"status": "error", "message": "Could not retrieve data from Prowlarr."}), 500

        # --- Prepare for filtering and enrichment (reusing existing logic) ---
        ignored_hashes = get_ignored_hashes()
        pending_hashes = get_all_torrent_hashes()
        exclude_keywords = current_app.config.get('DASHBOARD_EXCLUDE_KEYWORDS', [])
        min_movie_year = current_app.config.get('DASHBOARD_MIN_MOVIE_YEAR', 1900)
        tmdb_client = TheMovieDBClient()
        apps = get_prowlarr_applications()
        sonarr_cat_ids, radarr_cat_ids = _get_app_categories(apps)

        # Step 4: Process and merge new torrents
        for raw_torrent in raw_torrents_from_prowlarr:
            torrent = _normalize_torrent(raw_torrent)
            if not torrent or torrent['hash'] in ignored_hashes:
                continue

            # If it's a new torrent, process and enrich it
            if torrent['hash'] not in existing_torrents_map:
                torrent['is_new'] = True # Mark as new

                # --- Apply filtering and enrichment (adapted from old logic) ---
                if any(re.search(kw, torrent['title'], re.IGNORECASE) for kw in exclude_keywords):
                    continue

                media_type = _determine_media_type(raw_torrent, sonarr_cat_ids, radarr_cat_ids)
                torrent['type'] = media_type

                if media_type == 'movie':
                    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', torrent['title'])
                    if year_match and int(year_match.group(1)) < min_movie_year:
                        continue

                _enrich_torrent_details(torrent, tmdb_client)
                torrent['statuses'] = get_media_statuses(
                    title=torrent.get('title'),
                    tmdb_id=torrent.get('tmdbId'),
                    tvdb_id=torrent.get('tvdbId'),
                    media_type=torrent.get('type')
                )

                existing_torrents_map[torrent['hash']] = torrent

        # Step 5: Sort, limit, and save
        final_torrents = list(existing_torrents_map.values())

        # Filter out torrents with no publishDate before sorting
        final_torrents = [t for t in final_torrents if t.get('publishDate')]

        final_torrents.sort(key=lambda x: x['publishDate'], reverse=True)
        final_torrents = final_torrents[:MAX_TORRENTS_TO_KEEP]

        # Convert datetime objects back to ISO strings for JSON serialization
        for torrent in final_torrents:
            if isinstance(torrent['publishDate'], datetime):
                torrent['publishDate'] = torrent['publishDate'].isoformat()

        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(final_torrents, f, indent=2)

        set_last_refresh_time() # Still useful to know when we last ran it

        return jsonify({"status": "success", "torrents": final_torrents})

    except Exception as e:
        current_app.logger.error(f"Error in refresh_torrents: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An unexpected error occurred."}), 500

def _normalize_torrent(raw_torrent):
    """
    Normalizes a torrent dictionary from Prowlarr into a consistent format.
    Returns None if the torrent is invalid (lacks a unique ID).
    """
    unique_id = raw_torrent.get('hash') or raw_torrent.get('guid')
    if not unique_id:
        return None

    publish_date_str = raw_torrent.get('publishDate') or raw_torrent.get('uploaded_at')
    publish_date = None
    if publish_date_str:
        try:
            publish_date = datetime.fromisoformat(publish_date_str.replace('Z', '+00:00'))
        except ValueError:
            pass

    category_name = raw_torrent.get('categoryDescription')
    if not category_name and raw_torrent.get('categories'):
        category_name = raw_torrent['categories'][0].get('name')

    return {
        'hash': str(unique_id),
        'title': raw_torrent.get('title'),
        'size': raw_torrent.get('size'),
        'seeders': raw_torrent.get('seeders'),
        'leechers': raw_torrent.get('leechers'),
        'indexerId': raw_torrent.get('indexerId'),
        'type': raw_torrent.get('type'),
        'tmdbId': raw_torrent.get('tmdb_id'),
        'guid': raw_torrent.get('guid'),
        'downloadUrl': raw_torrent.get('guid'),
        'detailsUrl': raw_torrent.get('infoUrl'),
        'publishDate': publish_date,
        'category': category_name,
        'indexer': raw_torrent.get('indexer'),
        'tvdbId': None,
        'overview': '',
        'poster_url': '',
        'statuses': [],
        'is_new': False, # Default state for the 'new' badge
    }

def _get_app_categories(apps):
    """Extracts Sonarr and Radarr category IDs from Prowlarr application data."""
    sonarr_cat_ids = set()
    radarr_cat_ids = set()
    if not apps:
        return sonarr_cat_ids, radarr_cat_ids

    for app in apps:
        implementation_name = app.get('implementationName', '')
        app_fields = app.get('fields', [])

        categories_to_sync = []

        if implementation_name == 'Sonarr':
            for field in app_fields:
                if field.get('name') in ['syncCategories', 'animeSyncCategories'] and isinstance(field.get('value'), list):
                    categories_to_sync.extend(field['value'])
            sonarr_cat_ids.update(categories_to_sync)

        elif implementation_name == 'Radarr':
            for field in app_fields:
                if field.get('name') == 'syncCategories' and isinstance(field.get('value'), list):
                    categories_to_sync.extend(field['value'])
            radarr_cat_ids.update(categories_to_sync)

    return sonarr_cat_ids, radarr_cat_ids

def _determine_media_type(raw_torrent, sonarr_cat_ids, radarr_cat_ids):
    """Determines the media type ('movie' or 'tv') based on Prowlarr categories."""
    torrent_cats = raw_torrent.get('categories', [])
    for cat_obj in torrent_cats:
        cat_id = cat_obj.get('id')
        if cat_id in radarr_cat_ids:
            return 'movie'
        elif cat_id in sonarr_cat_ids:
            return 'tv'
    # Fallback to the type provided by Prowlarr if category doesn't match
    return raw_torrent.get('type')

def _enrich_torrent_details(torrent, tmdb_client):
    """Enriches a torrent with details from TMDB (overview, poster, etc.), finding the ID if missing."""
    media_type = torrent.get('type')

    # --- Fallback logic to find TMDB ID if it's missing ---
    if not torrent.get('tmdbId'):
        parsed_info = parse_media_name(torrent['title'])
        if parsed_info and parsed_info.get('title'):
            found_id = None
            search_title = parsed_info['title']
            search_year = parsed_info.get('year')

            current_app.logger.info(f"Torrent '{torrent['title']}' is missing TMDB ID. Trying to find it with title='{search_title}', year='{search_year}'")

            search_results = []
            if media_type == 'movie':
                search_results = tmdb_client.search_movie(search_title)
            elif media_type == 'tv':
                search_results = tmdb_client.search_series(search_title)

            if search_results:
                best_match = None
                # Try to find a match with the correct year
                if search_year:
                    for res in search_results:
                        # TMDb year can be a string, so compare loosely
                        if str(res.get('year', '')) == str(search_year):
                            best_match = res
                            break
                # If no year match or no year to search for, take the first result
                if not best_match:
                    best_match = search_results[0]

                if best_match:
                    found_id = best_match.get('id')
                    torrent['tmdbId'] = found_id
                    current_app.logger.info(f"Found TMDB ID {found_id} for '{torrent['title']}'")

    # --- Proceed with enrichment if we have an ID ---
    if not torrent.get('tmdbId'):
        return # Could not find ID, cannot enrich further

    tmdb_id = torrent['tmdbId']
    if media_type == 'tv':
        details = tmdb_client.get_series_details(tmdb_id)
        if details:
            torrent['tvdbId'] = details.get('tvdb_id')
            torrent['overview'] = details.get('overview')
            torrent['poster_url'] = details.get('poster')
    elif media_type == 'movie':
        details = tmdb_client.get_movie_details(tmdb_id)
        if details:
            torrent['overview'] = details.get('overview')
            torrent['poster_url'] = details.get('poster')

@dashboard_bp.route('/dashboard/api/ignore', methods=['POST'])
def ignore_torrent():
    """
    API endpoint to add a torrent identifier to the ignore list.
    Receives the identifier from the request body.
    """
    data = request.get_json()
    torrent_id = data.get('id')

    if not torrent_id:
        return jsonify({"status": "error", "message": "No identifier provided"}), 400

    add_ignored_hash(torrent_id)

    return jsonify({"status": "success", "message": f"Identifier {torrent_id} ignored."})

@dashboard_bp.route('/dashboard/api/proxy')
def proxy_request():
    """
    A simple proxy to bypass CORS issues for client-side fetches.
    """
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        # Attempt to return JSON, but fall back to text if that fails
        try:
            return jsonify(response.json())
        except ValueError:
            return response.text
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Proxy request to {url} failed: {e}")
        return jsonify({"error": f"Failed to fetch URL: {e}"}), 502
