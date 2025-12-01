# app/utils/dashboard_scheduler.py

import json
import os
from datetime import datetime, timezone
import re
from flask import current_app

from app.utils.prowlarr_client import get_latest_from_prowlarr, get_prowlarr_applications
from app.utils.tmdb_client import TheMovieDBClient
from app.utils.status_manager import get_media_statuses
from app.utils.release_parser import parse_release_data

DASHBOARD_STATE_FILE = os.path.join('instance', 'dashboard_state.json')
DASHBOARD_TORRENTS_FILE = os.path.join('instance', 'dashboard_torrents.json')

def get_last_refresh_time():
    """Reads the timestamp of the last refresh from the state file."""
    if not os.path.exists(DASHBOARD_STATE_FILE):
        return None
    try:
        with open(DASHBOARD_STATE_FILE, 'r') as f:
            data = json.load(f)
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

def get_dashboard_categories():
    """Loads and combines Sonarr and Radarr categories from search_settings.json."""
    settings_file = os.path.join('instance', 'search_settings.json')
    if not os.path.exists(settings_file):
        current_app.logger.warning("instance/search_settings.json not found. No category filtering will be applied.")
        return []

    try:
        with open(settings_file, 'r') as f:
            settings = json.load(f)
            sonarr_cats = settings.get('sonarr_categories', [])
            radarr_cats = settings.get('radarr_categories', [])
            # Combine and remove duplicates
            combined_cats = list(set(sonarr_cats + radarr_cats))
            current_app.logger.info(f"Loaded {len(combined_cats)} unique categories from search_settings.json.")
            return combined_cats
    except (json.JSONDecodeError, IOError) as e:
        current_app.logger.error(f"Could not read or parse instance/search_settings.json: {e}")
        return []

def scheduled_dashboard_refresh():
    """
    This function is designed to be called by the APScheduler.
    It fetches new torrents from Prowlarr and adds them to the existing list
    without altering the 'is_new' status of old torrents.
    It also refreshes the statuses of all torrents.
    """
    current_app.logger.info("Scheduler: Starting scheduled dashboard refresh job.")
    try:
        # Step 1: Load existing torrents, preserving their 'is_new' status
        existing_torrents_map = {}
        if os.path.exists(DASHBOARD_TORRENTS_FILE):
            try:
                with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
                    for torrent in json.load(f):
                        torrent['is_new'] = torrent.get('is_new', False) # Explicitly keep existing is_new status
                        if isinstance(torrent.get('publishDate'), str):
                            torrent['publishDate'] = datetime.fromisoformat(torrent['publishDate'].replace('Z', '+00:00'))
                        # Use 'guid' as the primary key for the map
                        if 'guid' in torrent and torrent['guid']:
                            existing_torrents_map[torrent['guid']] = torrent
            except (json.JSONDecodeError, IOError):
                current_app.logger.error("Scheduler: Could not read or parse dashboard_torrents.json, starting fresh.")
                pass

        # Step 2: Fetch new torrents from Prowlarr
        # If the existing torrents list is empty, force a full refresh by setting last_refresh to None
        last_refresh = get_last_refresh_time()
        if not existing_torrents_map:
             current_app.logger.info("Scheduler: Local torrent list is empty. Forcing full Prowlarr refresh (ignoring last refresh time).")
             last_refresh = None

        prowlarr_categories = get_dashboard_categories() # Use the new function
        raw_torrents_from_prowlarr = get_latest_from_prowlarr(
            categories=prowlarr_categories,
            min_date=last_refresh
        )

        if raw_torrents_from_prowlarr is None:
            current_app.logger.error("Scheduler: Could not retrieve data from Prowlarr. Aborting job.")
            return

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
        tmdb_api_key = current_app.config.get('TMDB_API_KEY')
        tmdb_client = TheMovieDBClient() if tmdb_api_key else None
        if not tmdb_client:
            current_app.logger.warning("Scheduler: TMDB_API_KEY not set. Status checks will be skipped.")

        apps = get_prowlarr_applications()
        sonarr_cat_ids, radarr_cat_ids = _get_app_categories(apps)
        exclude_keywords = current_app.config.get('DASHBOARD_EXCLUDE_KEYWORDS', [])
        min_movie_year = current_app.config.get('DASHBOARD_MIN_MOVIE_YEAR', 1900)

        # Step 3: Process and merge new torrents
        new_torrents_found = 0
        rejected_by_keyword = 0
        rejected_by_year = 0
        rejected_by_duplicate = 0

        for raw_torrent in raw_torrents_from_prowlarr:
            torrent = _normalize_torrent(raw_torrent)

            # After normalization, 'guid' is the primary identifier.
            if not torrent:
                continue

            if torrent['guid'] in existing_torrents_map:
                rejected_by_duplicate += 1
                current_app.logger.warning(f"Scheduler: Duplicate GUID {torrent['guid']} found but adding anyway for debugging.")
                # continue  <-- DISABLED FOR DEBUGGING

            # This is a genuinely new torrent, but might be filtered out

            if any(re.search(kw, torrent['title'], re.IGNORECASE) for kw in exclude_keywords):
                rejected_by_keyword += 1
                continue

            media_type = _determine_media_type(raw_torrent, sonarr_cat_ids, radarr_cat_ids)
            torrent['type'] = media_type

            if media_type == 'movie':
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', torrent['title'])
                if year_match and int(year_match.group(1)) < min_movie_year:
                    rejected_by_year += 1
                    continue

            # If we reach here, the torrent is accepted
            new_torrents_found += 1
            torrent['is_new'] = True
            existing_torrents_map[torrent['guid']] = torrent

        current_app.logger.info(
            f"Scheduler: Found {new_torrents_found} new torrents from Prowlarr. "
            f"Skipped: {rejected_by_keyword} (keywords), {rejected_by_year} (year), {rejected_by_duplicate} (duplicates - IGNORED)."
        )

        # Step 4: Re-evaluate status and enrich ALL torrents
        if tmdb_client:
            for torrent_guid, torrent in existing_torrents_map.items():
                if 'type' not in torrent:
                     # Find the original raw torrent to determine media type if possible
                     raw_info = next((t for t in raw_torrents_from_prowlarr if (_normalize_torrent(t) or {}).get('guid') == torrent_guid), None)
                     torrent['type'] = _determine_media_type(raw_info, sonarr_cat_ids, radarr_cat_ids) if raw_info else 'movie'

                _enrich_torrent_details(torrent, tmdb_client)

                if 'parsed_data' not in torrent or not torrent['parsed_data']:
                    torrent['parsed_data'] = parse_release_data(torrent['title'])

                torrent['statuses'] = get_media_statuses(
                    title=torrent.get('title'),
                    tmdb_id=torrent.get('tmdbId'),
                    tvdb_id=torrent.get('tvdbId'),
                    media_type=torrent.get('type'),
                    parsed_data=torrent['parsed_data']
                )

        # Step 5: Sort and save
        final_torrents = list(existing_torrents_map.values())
        # Sort by publish date, treating items with no date as the oldest
        final_torrents.sort(key=lambda x: x.get('publishDate') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


        for torrent in final_torrents:
            if isinstance(torrent['publishDate'], datetime):
                torrent['publishDate'] = torrent['publishDate'].isoformat()

        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(final_torrents, f, indent=2)

        set_last_refresh_time()
        current_app.logger.info("Scheduler: Dashboard refresh job finished successfully.")

    except Exception as e:
        current_app.logger.error(f"Scheduler: Error in scheduled_dashboard_refresh: {e}", exc_info=True)

# Helper functions adapted from dashboard/routes.py

def _normalize_torrent(raw_torrent):
    """
    Normalizes a torrent dictionary from Prowlarr into a consistent format.
    Ensures TMDB ID is an integer. Returns None if the torrent is invalid.
    """
    # GUID is the unique identifier for a specific release. Using it prevents
    # hiding different releases that might share the same infohash.
    unique_id = raw_torrent.get('guid')
    if not unique_id:
        current_app.logger.warning(f"Skipping torrent because it has no 'guid' for unique identification. Title: '{raw_torrent.get('title', 'N/A')}'")
        return None

    publish_date_str = raw_torrent.get('publishDate') or raw_torrent.get('uploaded_at')
    publish_date = None
    if publish_date_str:
        try:
            # Handle various ISO 8601 formats, including those with 'Z' or timezone offsets
            if 'Z' in publish_date_str.upper():
                publish_date_str = publish_date_str.upper().replace('Z', '+00:00')

            # Truncate microseconds if they are longer than 6 digits, which fromisoformat dislikes
            if '.' in publish_date_str:
                parts = publish_date_str.split('.')
                microseconds_part = parts[1].split('+')[0].split('-')[0]
                if len(microseconds_part) > 6:
                    timezone_part = ''
                    if '+' in parts[1]:
                        timezone_part = '+' + parts[1].split('+')[-1]
                    elif '-' in parts[1]:
                         timezone_part = '-' + parts[1].split('-')[-1]

                    parts[1] = microseconds_part[:6] + timezone_part
                    publish_date_str = '.'.join(parts)

            publish_date = datetime.fromisoformat(publish_date_str)
        except (ValueError, TypeError):
            current_app.logger.warning(f"Could not parse date string '{publish_date_str}' for torrent '{raw_torrent.get('title', 'N/A')}'. Setting date to None.")
            publish_date = None # Keep the torrent, just without a valid date

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
    sonarr_cat_ids, radarr_cat_ids = set(), set()
    if not apps: return sonarr_cat_ids, radarr_cat_ids
    for app in apps:
        implementation = app.get('implementationName', '')
        categories = []
        for field in app.get('fields', []):
            if field.get('name') in ['syncCategories', 'animeSyncCategories'] and isinstance(field.get('value'), list):
                categories.extend(field['value'])
        if implementation == 'Sonarr': sonarr_cat_ids.update(categories)
        elif implementation == 'Radarr': radarr_cat_ids.update(categories)
    return sonarr_cat_ids, radarr_cat_ids

def _determine_media_type(raw_torrent, sonarr_cat_ids, radarr_cat_ids):
    if not raw_torrent: return 'movie'
    cat_ids = {cat.get('id') for cat in raw_torrent.get('categories', [])}
    if cat_ids.intersection(radarr_cat_ids): return 'movie'
    if cat_ids.intersection(sonarr_cat_ids): return 'tv'
    return raw_torrent.get('type', 'movie')

def _enrich_torrent_details(torrent, tmdb_client):
    media_type = torrent.get('type')
    if not torrent.get('tmdbId'):
        from app.utils.arr_client import parse_media_name # Lazy import to avoid circular dependency issues
        parsed_info = parse_media_name(torrent['title'])
        if parsed_info and parsed_info.get('title'):
            search_results = tmdb_client.search_movie(parsed_info['title']) if media_type == 'movie' else tmdb_client.search_series(parsed_info['title'])
            if search_results:
                best_match = next((r for r in search_results if str(r.get('year', '')) == str(parsed_info.get('year'))), search_results[0])
                if best_match: torrent['tmdbId'] = best_match.get('id')

    if not torrent.get('tmdbId'): return

    tmdb_id = torrent['tmdbId']
    details = tmdb_client.get_series_details(tmdb_id) if media_type == 'tv' else tmdb_client.get_movie_details(tmdb_id)
    if details:
        if media_type == 'tv': torrent['tvdbId'] = details.get('tvdb_id')
        torrent['overview'] = details.get('overview')
        torrent['poster_url'] = details.get('poster')
