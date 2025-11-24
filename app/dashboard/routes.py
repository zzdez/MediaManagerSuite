from flask import render_template, jsonify, current_app, request
from app.dashboard import dashboard_bp
import json
import os
from datetime import datetime, timezone, timedelta
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
# Import the release parser
from app.utils.release_parser import parse_release_data

# Define paths for our state files
DASHBOARD_STATE_FILE = os.path.join('instance', 'dashboard_state.json')
DASHBOARD_IGNORED_FILE = os.path.join('instance', 'dashboard_ignored.json')
DASHBOARD_TORRENTS_FILE = os.path.join('instance', 'dashboard_torrents.json')

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
    torrents = []
    if os.path.exists(DASHBOARD_TORRENTS_FILE):
        try:
            with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
                torrents = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            current_app.logger.error(f"Could not read or parse dashboard_torrents.json: {e}")
            torrents = []

    # Ensure all torrents have parsed_data for backward compatibility
    for torrent in torrents:
        if 'parsed_data' not in torrent or not torrent['parsed_data']:
            torrent['parsed_data'] = parse_release_data(torrent['title'])

    # --- NEW: Server-side filter on page load to ensure UI consistency ---
    prowlarr_categories = current_app.config.get('DASHBOARD_PROWLARR_CATEGORIES', [])
    if prowlarr_categories:
        initial_count = len(torrents)
        allowed_cat_ids = set(prowlarr_categories)

        # Filter the loaded torrents. This relies on 'category_ids' being present.
        # Old torrents without this key will be filtered out, thus cleaning the data over time.
        torrents = [
            torrent for torrent in torrents
            if any(cat_id in allowed_cat_ids for cat_id in torrent.get('category_ids', []))
        ]
        current_app.logger.info(f"Filtered torrents on dashboard load. Kept {len(torrents)} of {initial_count} torrents.")

    return render_template('dashboard/index.html', torrents=torrents)


@dashboard_bp.route('/dashboard/api/refresh')
def refresh_torrents():
    """
    API endpoint to refresh the torrent list. It fetches the latest from Prowlarr,
    merges them with the existing list, and re-evaluates the status of ALL torrents.
    """
    try:
        # Step 1: Load existing torrents and create a lookup map
        existing_torrents_map = {}
        if os.path.exists(DASHBOARD_TORRENTS_FILE):
            try:
                with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
                    for torrent in json.load(f):
                        torrent['is_new'] = False
                        if isinstance(torrent.get('publishDate'), str):
                            torrent['publishDate'] = datetime.fromisoformat(torrent['publishDate'].replace('Z', '+00:00'))
                        existing_torrents_map[torrent['hash']] = torrent
            except (json.JSONDecodeError, IOError):
                pass  # Start fresh if file is corrupt

        # Step 2: Fetch new torrents from Prowlarr
        last_refresh = get_last_refresh_time()
        prowlarr_categories = current_app.config.get('DASHBOARD_PROWLARR_CATEGORIES', [])
        raw_torrents_from_prowlarr = get_latest_from_prowlarr(
            categories=prowlarr_categories,
            min_date=last_refresh
        )

        if raw_torrents_from_prowlarr is None:
            return jsonify({"status": "error", "message": "Could not retrieve data from Prowlarr."}), 500

        # Step 2.5: Post-filter results by category because Prowlarr API ignores 'cat' on general searches
        if prowlarr_categories:
            initial_count = len(raw_torrents_from_prowlarr)
            allowed_cat_ids = set(prowlarr_categories)

            filtered_torrents = [
                torrent for torrent in raw_torrents_from_prowlarr
                if any(cat.get('id') in allowed_cat_ids for cat in torrent.get('categories', []))
            ]
            raw_torrents_from_prowlarr = filtered_torrents
            final_count = len(raw_torrents_from_prowlarr)
            current_app.logger.info(f"Filtered Prowlarr results by configured categories. Kept {final_count} of {initial_count} torrents.")

        # --- Prepare for enrichment ---
        ignored_hashes = get_ignored_hashes()
        # Make the TMDB client initialization conditional on the API key's existence
        tmdb_api_key = current_app.config.get('TMDB_API_KEY')
        tmdb_client = TheMovieDBClient() if tmdb_api_key else None
        if not tmdb_client:
            current_app.logger.warning("TMDB_API_KEY not set. Skipping enrichment and status checks.")

        apps = get_prowlarr_applications()
        sonarr_cat_ids, radarr_cat_ids = _get_app_categories(apps)
        exclude_keywords = current_app.config.get('DASHBOARD_EXCLUDE_KEYWORDS', [])
        min_movie_year = current_app.config.get('DASHBOARD_MIN_MOVIE_YEAR', 1900)

        # Step 3: Process and merge new torrents into the main map
        for raw_torrent in raw_torrents_from_prowlarr:
            torrent = _normalize_torrent(raw_torrent)
            if not torrent or torrent['hash'] in ignored_hashes:
                continue

            # If it's a new torrent, mark it and perform basic enrichment
            if torrent['hash'] not in existing_torrents_map:
                torrent['is_new'] = True

                if any(re.search(kw, torrent['title'], re.IGNORECASE) for kw in exclude_keywords):
                    continue

                media_type = _determine_media_type(raw_torrent, sonarr_cat_ids, radarr_cat_ids)
                torrent['type'] = media_type

                if media_type == 'movie':
                    year_match = re.search(r'\b(19\d{2}|20\d{2})\b', torrent['title'])
                    if year_match and int(year_match.group(1)) < min_movie_year:
                        continue

                # Add to the map to be processed in the next step
                existing_torrents_map[torrent['hash']] = torrent

        # Step 4: Re-evaluate status and enrich ALL torrents in the map
        for torrent_hash, torrent in existing_torrents_map.items():
            # Ensure essential data is present, especially for older torrents
            if 'type' not in torrent:
                 # Find the original raw torrent to determine media type if possible
                raw_info = next((t for t in raw_torrents_from_prowlarr if (_normalize_torrent(t) or {}).get('hash') == torrent_hash), None)
                torrent['type'] = _determine_media_type(raw_info, sonarr_cat_ids, radarr_cat_ids) if raw_info else 'movie'

            # Only perform enrichment and status checks if the TMDB client is available
            if tmdb_client:
                # Enrich details (finds missing IDs, gets poster, etc.)
                _enrich_torrent_details(torrent, tmdb_client)

                # The release data must be parsed BEFORE checking status
                # so we can identify season packs.
                if 'parsed_data' not in torrent or not torrent['parsed_data']:
                    torrent['parsed_data'] = parse_release_data(torrent['title'])

                # Get the latest status, passing the parsed data
                torrent['statuses'] = get_media_statuses(
                    title=torrent.get('title'),
                    tmdb_id=torrent.get('tmdbId'),
                    tvdb_id=torrent.get('tvdbId'),
                    media_type=torrent.get('type'),
                    parsed_data=torrent['parsed_data']
                )
            elif 'parsed_data' not in torrent or not torrent['parsed_data']:
                 # Even if TMDB isn't configured, we should still parse the release data
                 # for the frontend filters to work.
                 torrent['parsed_data'] = parse_release_data(torrent['title'])

        # Step 5: Sort, and save the complete, updated list
        final_torrents = list(existing_torrents_map.values())
        final_torrents = [t for t in final_torrents if t.get('publishDate')]
        final_torrents.sort(key=lambda x: x['publishDate'], reverse=True)

        for torrent in final_torrents:
            if isinstance(torrent['publishDate'], datetime):
                torrent['publishDate'] = torrent['publishDate'].isoformat()

        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(final_torrents, f, indent=2)

        set_last_refresh_time()

        return jsonify({"status": "success", "torrents": final_torrents})

    except Exception as e:
        current_app.logger.error(f"Error in refresh_torrents: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An unexpected error occurred."}), 500

def _normalize_torrent(raw_torrent):
    """
    Normalizes a torrent dictionary from Prowlarr into a consistent format.
    Ensures TMDB ID is an integer. Returns None if the torrent is invalid.
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

    # Also extract the raw category IDs for server-side filtering
    category_ids = [cat.get('id') for cat in raw_torrent.get('categories', []) if cat.get('id') is not None]

    tmdb_id_raw = raw_torrent.get('tmdbId') or raw_torrent.get('tmdb_id')
    tmdb_id_int = None
    if tmdb_id_raw:
        try:
            # Ensure the ID is a valid integer
            tmdb_id_int = int(tmdb_id_raw)
        except (ValueError, TypeError):
            tmdb_id_int = None # Discard if not a valid number

    return {
        'hash': str(unique_id),
        'title': raw_torrent.get('title'),
        'size': raw_torrent.get('size'),
        'seeders': raw_torrent.get('seeders'),
        'leechers': raw_torrent.get('leechers'),
        'indexerId': raw_torrent.get('indexerId'),
        'type': raw_torrent.get('type'),
        'tmdbId': tmdb_id_int,
        'guid': raw_torrent.get('guid'),
        'downloadUrl': raw_torrent.get('guid'),
        'detailsUrl': raw_torrent.get('infoUrl'),
        'publishDate': publish_date,
        'category': category_name,
        'category_ids': category_ids,
        'indexer': raw_torrent.get('indexer'),
        'tvdbId': None,
        'overview': '',
        'poster_url': '',
        'statuses': [],
        'is_new': False,
        'parsed_data': {},
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

@dashboard_bp.route('/dashboard/api/refresh-statuses')
def refresh_statuses():
    """
    API endpoint to refresh just the statuses of the existing torrent list
    without fetching new ones from Prowlarr.
    """
    try:
        if not os.path.exists(DASHBOARD_TORRENTS_FILE):
            return jsonify({"status": "success", "torrents": []})

        existing_torrents = []
        with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
            existing_torrents = json.load(f)

        # Get the TMDB client
        tmdb_api_key = current_app.config.get('TMDB_API_KEY')
        tmdb_client = TheMovieDBClient() if tmdb_api_key else None
        if not tmdb_client:
            current_app.logger.warning("TMDB_API_KEY not set. Skipping status refresh.")
            # Return the unmodified list if TMDB isn't available
            return jsonify({"status": "success", "torrents": existing_torrents})

        # Re-evaluate status for ALL torrents in the list
        for torrent in existing_torrents:
            # Ensure parsed_data is present for status checking
            if 'parsed_data' not in torrent or not torrent['parsed_data']:
                torrent['parsed_data'] = parse_release_data(torrent['title'])

            # The 'is_new' flag is irrelevant here, but we set it to false for consistency
            torrent['is_new'] = False

            # Get the latest status
            torrent['statuses'] = get_media_statuses(
                title=torrent.get('title'),
                tmdb_id=torrent.get('tmdbId'),
                tvdb_id=torrent.get('tvdbId'),
                media_type=torrent.get('type'),
                parsed_data=torrent['parsed_data']
            )

        # Save the complete, updated list
        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(existing_torrents, f, indent=2)

        return jsonify({"status": "success", "torrents": existing_torrents})

    except Exception as e:
        current_app.logger.error(f"Error in refresh_statuses: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An unexpected error occurred during status refresh."}), 500

@dashboard_bp.route('/dashboard/api/cleanup', methods=['POST'])
def cleanup_torrents():
    """
    API endpoint to clean up old torrents from the dashboard's persistent store.
    """
    data = request.get_json()
    days_to_keep = data.get('days')

    if days_to_keep is None:
        return jsonify({"status": "error", "message": "Number of days not provided."}), 400

    try:
        days_to_keep = int(days_to_keep)
        if days_to_keep < 0 or days_to_keep > 30:
            raise ValueError("Days must be between 0 and 30.")
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid number of days. Must be an integer between 0 and 30."}), 400

    if not os.path.exists(DASHBOARD_TORRENTS_FILE):
        return jsonify({"status": "success", "message": "No torrents to clean up.", "cleaned_count": 0})

    try:
        with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
            all_torrents = json.load(f)

        original_count = len(all_torrents)

        if days_to_keep == 0:
            cleaned_torrents = []
            current_app.logger.info("Cleanup: Removing all torrents as requested (0 days).")
        else:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            cleaned_torrents = [
                t for t in all_torrents
                if datetime.fromisoformat(t['publishDate'].replace('Z', '+00:00')) >= cutoff_date
            ]
            current_app.logger.info(f"Cleanup: Keeping torrents from the last {days_to_keep} days.")

        cleaned_count = original_count - len(cleaned_torrents)

        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(cleaned_torrents, f, indent=2)

        return jsonify({
            "status": "success",
            "message": f"{cleaned_count} old torrent(s) removed.",
            "cleaned_count": cleaned_count
        })

    except (json.JSONDecodeError, IOError, KeyError) as e:
        current_app.logger.error(f"Error during torrent cleanup: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to process the torrent file."}), 500
