from flask import render_template, jsonify, current_app, request
from app.dashboard import dashboard_bp
import json
import os
from datetime import datetime, timezone
import re
from thefuzz import fuzz

# Import Prowlarr client
from app.utils.prowlarr_client import get_latest_from_prowlarr
# Import TMDB client for ID conversion
from app.utils.tmdb_client import TheMovieDBClient
# Import Arr client for checking existing media
from app.utils.arr_client import get_sonarr_series_by_guid, get_radarr_movie_by_guid
# Import mapping manager to check pending torrents
from app.utils.mapping_manager import get_all_torrent_hashes

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

def _parse_title_and_year(torrent_title):
    """
    Parses a torrent title to extract a clean title and a year.
    Returns a tuple (title, year).
    """
    # Remove dots, underscores, and excessive spacing
    clean_title = re.sub(r'[\._]', ' ', torrent_title)

    # Try to extract the year (e.g., 2023). This is a strong indicator for splitting.
    year_match = re.search(r'\b(19[5-9]\d|20\d{2})\b', clean_title)
    year = None
    if year_match:
        year = int(year_match.group(1))
        # Take everything before the year as the potential title
        clean_title = clean_title[:year_match.start()].strip()

    # Further clean up by removing common release tags (e.g., 1080p, MULTi, etc.)
    # This list can be expanded.
    tags_to_remove = [
        '1080p', '720p', '2160p', '4K', 'UHD', 'BluRay', 'WEB-DL', 'WEBRip', 'HDTV', 'x264', 'x265', 'H264', 'H265',
        'AAC', 'AC3', 'DTS', '5.1', '7.1', 'Atmos',
        'MULTi', 'VOSTFR', 'VFF', 'TRUEFRENCH', 'FRENCH', 'PROPER', 'REPACK',
        # Common release groups or patterns
        r'-\w+$'
    ]
    for tag in tags_to_remove:
        clean_title = re.sub(r'\b' + re.escape(tag) + r'\b', '', clean_title, flags=re.IGNORECASE)

    # Final cleanup of any resulting double spaces
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()

    return clean_title, year


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

        current_app.logger.info(f"Prowlarr client returned {len(raw_torrents)} processable items.")

        # --- Prepare for filtering and enrichment ---
        ignored_hashes = get_ignored_hashes()
        pending_hashes = get_all_torrent_hashes()
        exclude_keywords = current_app.config.get('DASHBOARD_EXCLUDE_KEYWORDS', [])
        min_movie_year = current_app.config.get('DASHBOARD_MIN_MOVIE_YEAR', 1900)
        tmdb_client = TheMovieDBClient()

        final_torrents = []

        # --- Process each torrent ---
        for raw_torrent in raw_torrents:
            # Step 1: Normalize the raw data. If it's invalid, skip it.
            torrent = _normalize_torrent(raw_torrent)
            if not torrent:
                continue

            # Step 2: Filter based on normalized data
            if torrent['hash'] in ignored_hashes:
                continue

            # Date filtering
            if torrent['publishDate'] and last_refresh_utc:
                if torrent['publishDate'] <= last_refresh_utc:
                    continue

            # Keyword filtering
            keyword_match = next((keyword for keyword in exclude_keywords if re.search(keyword, torrent['title'], re.IGNORECASE)), None)
            if keyword_match:
                continue

            # Year filtering for movies
            if torrent['type'] == 'movie':
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', torrent['title'])
                if year_match and int(year_match.group(1)) < min_movie_year:
                    continue

            # Step 3: Enrich the normalized data
            # If we don't have a TMDB ID, try to find one
            if not torrent['tmdbId']:
                clean_title, year = _parse_title_and_year(torrent['title'])

                if clean_title:
                    current_app.logger.debug(f"Attempting to find TMDB ID for title: '{clean_title}' ({year})")

                    search_results = []
                    if torrent['type'] == 'tv':
                        search_results = tmdb_client.search_series(clean_title)
                    elif torrent['type'] == 'movie':
                        search_results = tmdb_client.search_movie(clean_title)

                    if search_results:
                        best_match = None
                        highest_score = 0

                        # Filter by year first if available
                        if year:
                            year_filtered_results = [r for r in search_results if r.get('year') and int(r['year']) == year]
                            # If we have matches for the exact year, use them. Otherwise, use the full list.
                            if year_filtered_results:
                                search_results = year_filtered_results

                        # Find the best title match in the (potentially filtered) list
                        for result in search_results:
                            result_title = result.get('title') or result.get('name')
                            score = fuzz.ratio(clean_title.lower(), result_title.lower())
                            if score > highest_score:
                                highest_score = score
                                best_match = result

                        # If we found a reasonably good match, use its ID
                        if best_match and highest_score > 75: # Confidence threshold
                            torrent['tmdbId'] = best_match['id']
                            # Correction: Get the title from the best_match to log the correct info
                            best_match_title = best_match.get('title') or best_match.get('name')
                            current_app.logger.info(f"Found a match for '{clean_title}': '{best_match_title}' (ID: {best_match['id']}) with score {highest_score}")

            # Now, enrich with details if we have an ID (either original or found)
            if torrent['tmdbId']:
                current_app.logger.debug(f"Enriching torrent with TMDB ID {torrent['tmdbId']}: {torrent['title']}")
                details = None
                if torrent['type'] == 'tv':
                    details = tmdb_client.get_series_details(torrent['tmdbId'])
                    if details:
                        torrent['tvdbId'] = details.get('tvdb_id')
                        # Use the name from TMDB as it's cleaner
                        torrent['name'] = details.get('name')
                elif torrent['type'] == 'movie':
                    details = tmdb_client.get_movie_details(torrent['tmdbId'])
                    if details:
                        # Use the title from TMDB
                        torrent['name'] = details.get('title')

                if details:
                    torrent['overview'] = details.get('overview')
                    # Corrected key for poster URL
                    torrent['posterUrl'] = details.get('poster') or details.get('poster_url')


            # Step 4: Check if media is already managed
            torrent['is_managed'] = is_media_managed(torrent, pending_hashes)

            final_torrents.append(torrent)

        # Update the refresh timestamp *after* a successful run
        set_last_refresh_time()

        return jsonify({"status": "success", "torrents": final_torrents})

    except Exception as e:
        current_app.logger.error(f"Error in refresh_torrents: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An unexpected error occurred."}), 500

def _normalize_torrent(raw_torrent):
    """
    Normalizes a torrent dictionary from Prowlarr into a consistent format.
    Returns None if the torrent is invalid (lacks a unique ID).
    """
    # A torrent is invalid if it lacks a reliable unique identifier.
    # The best identifier is 'hash', but for general search results, we fall back to 'guid'.
    unique_id = raw_torrent.get('hash') or raw_torrent.get('guid')
    if not unique_id:
        current_app.logger.warning(f"Skipping torrent with no usable identifier (hash or guid): {raw_torrent.get('title')}")
        return None

    publish_date_str = raw_torrent.get('publishDate') or raw_torrent.get('uploaded_at')
    publish_date = None
    if publish_date_str:
        try:
            publish_date = datetime.fromisoformat(publish_date_str.replace('Z', '+00:00'))
        except ValueError:
            current_app.logger.warning(f"Could not parse date for torrent '{raw_torrent.get('title')}': {publish_date_str}")

    return {
        'hash': str(unique_id), # Ensure the ID is always a string for consistency
        'title': raw_torrent.get('title'),
        'name': raw_torrent.get('title'), # Start with the original title
        'size': raw_torrent.get('size'),
        'seeders': raw_torrent.get('seeders'),
        'leechers': raw_torrent.get('leechers'),
        'indexerId': raw_torrent.get('indexerId'),
        'type': raw_torrent.get('type'),
        'tmdbId': raw_torrent.get('tmdb_id'),  # snake_case to camelCase
        'guid': raw_torrent.get('guid'),
        'downloadUrl': raw_torrent.get('guid'), # Use guid for the download link
        'publishDate': publish_date,
        'category': raw_torrent.get('categoryDescription'),
        # Fields to be added during enrichment
        'tvdbId': None,
        'overview': '',
        'posterUrl': '',
        'is_managed': False,
    }

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
