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
    This is the core logic for the dashboard.
    """
    try:
        last_refresh_utc = get_last_refresh_time()

        # Fetch the latest torrents from Prowlarr
        prowlarr_categories = current_app.config.get('DASHBOARD_PROWLARR_CATEGORIES', [])
        raw_torrents = get_latest_from_prowlarr(prowlarr_categories)

        if raw_torrents is None:
            # This indicates an API error in the client
            current_app.logger.error("Failed to fetch data from Prowlarr.")
            return jsonify({"status": "error", "message": "Could not retrieve data from Prowlarr."}), 500

        current_app.logger.info(f"Prowlarr returned {len(raw_torrents)} items since {last_refresh_utc}")

        # --- Prepare for filtering and enrichment ---
        ignored_hashes = get_ignored_hashes()
        pending_hashes = {torrent['torrent_hash'] for torrent in get_all_torrents_in_map()}
        exclude_keywords = current_app.config.get('DASHBOARD_EXCLUDE_KEYWORDS', [])
        min_movie_year = current_app.config.get('DASHBOARD_MIN_MOVIE_YEAR', 1900)
        tmdb_client = TheMovieDBClient()

        final_torrents = []

        # --- Process each torrent ---
        for torrent in raw_torrents:
            # Date filtering
            publish_date_str = torrent.get('publishDate')
            if publish_date_str and last_refresh_utc:
                # Prowlarr dates are ISO 8601 with timezone info
                publish_date = datetime.fromisoformat(publish_date_str)
                if publish_date <= last_refresh_utc:
                    continue # Skip torrents published before the last refresh

            # Basic filtering
            if torrent.get('hash') in ignored_hashes:
                continue
            if any(re.search(keyword, torrent.get('title', ''), re.IGNORECASE) for keyword in exclude_keywords):
                continue

            # Year filtering for movies
            if torrent.get('type') == 'movie':
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', torrent.get('title', ''))
                if year_match and int(year_match.group(1)) < min_movie_year:
                    continue

            # --- Enrichment ---
            enriched_data = {}
            if torrent.get('tmdbId'):
                if torrent.get('type') == 'tv':
                    details = tmdb_client.get_series_details(torrent['tmdbId'])
                    if details:
                         # For Sonarr, we need the TVDB ID. Fetch it from TMDB.
                        enriched_data['tvdbId'] = details.get('tvdb_id')
                        enriched_data['overview'] = details.get('overview')
                        enriched_data['poster_url'] = details.get('poster_url')
                elif torrent.get('type') == 'movie':
                    details = tmdb_client.get_movie_details(torrent['tmdbId'])
                    if details:
                        enriched_data['overview'] = details.get('overview')
                        enriched_data['poster_url'] = details.get('poster_url')

            # Combine original torrent info with enriched data
            torrent.update(enriched_data)

            # Check if media is already managed
            torrent['is_managed'] = is_media_managed(torrent, pending_hashes)

            final_torrents.append(torrent)

        # Update the refresh timestamp *after* a successful run
        set_last_refresh_time()

        return jsonify({"status": "success", "torrents": final_torrents})

    except Exception as e:
        current_app.logger.error(f"Error in refresh_torrents: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An unexpected error occurred."}), 500


def is_media_managed(torrent_info, pending_hashes):
    """
    Checks if a given torrent corresponds to media already managed by Sonarr/Radarr
    or is pending in the mapping manager.
    """
    # 1. Check if the torrent hash is already being processed
    if torrent_info.get('hash') in pending_hashes:
        return True

    media_type = torrent_info.get('type')
    tmdb_id = torrent_info.get('tmdbId')
    tvdb_id = torrent_info.get('tvdbId') # This was added during enrichment

    # 2. Check Sonarr for TV shows
    if media_type == 'tv' and tvdb_id:
        plex_guid = f'tvdb://{tvdb_id}'
        if get_sonarr_series_by_guid(plex_guid):
            return True

    # 3. Check Radarr for movies
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
