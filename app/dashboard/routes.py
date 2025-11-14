from flask import render_template, jsonify, current_app
from app.dashboard import dashboard_bp
import json
import os
from datetime import datetime, timezone
import re

# Import Prowlarr client
from app.utils.prowlarr_client import get_latest_from_prowlarr
# Import TMDB client for ID conversion
from app.utils.tmdb_client import TheMovieDBClient
# Import Arr client for checking existing media
from app.utils.arr_client import get_sonarr_series_by_guid, get_radarr_movie_by_guid
# Import mapping manager to check pending torrents
from app.utils.mapping_manager import get_all_torrents_in_map

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
    Dashboard page
    """
    return render_template('dashboard/index.html')


@dashboard_bp.route('/dashboard/api/refresh')
def refresh_torrents():
    """
    API endpoint to get new torrents since the last refresh.
    """
    config = current_app.config
    last_refresh_time = get_last_refresh_time()
    ignored_hashes = get_ignored_hashes()

    # Get filter settings from config
    exclude_keywords = config.get('DASHBOARD_EXCLUDE_KEYWORDS', [])
    min_movie_year = config.get('DASHBOARD_MIN_MOVIE_YEAR', 2020)
    prowlarr_categories = config.get('DASHBOARD_PROWLARR_CATEGORIES', [])

    current_app.logger.info(f"Dashboard refresh triggered. Last refresh: {last_refresh_time}")

    # Fetch latest torrents from Prowlarr
    prowlarr_results = get_latest_from_prowlarr(categories=prowlarr_categories, limit=500) # Increased limit to ensure we get new items
    if not prowlarr_results:
        set_last_refresh_time()
        return jsonify({"status": "error", "message": "Could not fetch results from Prowlarr.", "torrents": []})

    new_torrents = []
    for torrent in prowlarr_results:
        # 1. Filter by publish date
        publish_date_str = torrent.get('publishDate')
        if not publish_date_str:
            continue
        # Prowlarr dates are often in ISO 8601 with 'Z'
        publish_date = datetime.fromisoformat(publish_date_str.replace('Z', '+00:00'))
        if last_refresh_time and publish_date <= last_refresh_time:
            continue

        # 2. Filter by ignored hash
        if torrent.get('guid') in ignored_hashes:
            continue

        title_lower = torrent.get('title', '').lower()

        # 3. Filter by excluded keywords
        if any(keyword in title_lower for keyword in exclude_keywords):
            continue

        # 4. Filter by movie year
        year_match = re.search(r'\b(19[89]\d|20\d{2})\b', title_lower)
        if year_match:
            year = int(year_match.group(1))
            if year < min_movie_year:
                continue

        new_torrents.append(torrent)

    current_app.logger.info(f"Found {len(new_torrents)} new torrents after basic filtering. Now enriching...")

    enriched_torrents = []
    tmdb_client = TheMovieDBClient()

    pending_torrents_map = get_all_torrents_in_map()
    pending_hashes = set(pending_torrents_map.keys())

    for torrent in new_torrents:
        tmdb_id = torrent.get('tmdbId')
        media_type = torrent.get('type')
        tvdb_id = None

        if media_type == 'tv' and tmdb_id:
            try:
                series_details = tmdb_client.get_series_details(tmdb_id)
                if series_details:
                    tvdb_id = series_details.get('tvdb_id')
                    torrent['tvdbId'] = tvdb_id
            except Exception as e:
                current_app.logger.error(f"Failed to get TVDB ID for TMDB ID {tmdb_id}: {e}")

        torrent['is_managed'] = is_media_managed(torrent, pending_hashes)

        enriched_torrents.append(torrent)

    current_app.logger.info(f"Enriched {len(enriched_torrents)} torrents.")

    set_last_refresh_time()

    return jsonify({"status": "success", "torrents": enriched_torrents})

def is_media_managed(torrent_info, pending_hashes):
    """
    Checks if a given torrent corresponds to media already managed by Sonarr/Radarr
    or is pending in the mapping manager.
    """
    if torrent_info.get('guid') in pending_hashes:
        return True

    media_type = torrent_info.get('type')
    tmdb_id = torrent_info.get('tmdbId')
    tvdb_id = torrent_info.get('tvdbId')

    if media_type == 'tv' and tvdb_id:
        plex_guid = f'tvdb://{tvdb_id}'
        if get_sonarr_series_by_guid(plex_guid):
            return True

    if media_type == 'movie' and tmdb_id:
        plex_guid = f'tmdb://{tmdb_id}'
        if get_radarr_movie_by_guid(plex_guid):
            return True

    return False

@dashboard_bp.route('/dashboard/api/ignore/<torrent_hash>', methods=['POST'])
def ignore_torrent(torrent_hash):
    """
    API endpoint to add a torrent hash to the ignore list.
    """
    if not torrent_hash:
        return jsonify({"status": "error", "message": "No hash provided"}), 400

    add_ignored_hash(torrent_hash)

    return jsonify({"status": "success", "message": f"Hash {torrent_hash} ignored."})
