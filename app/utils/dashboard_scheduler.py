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
                        if isinstance(torrent.get('publishDate'), str):
                            torrent['publishDate'] = datetime.fromisoformat(torrent['publishDate'].replace('Z', '+00:00'))
                        existing_torrents_map[torrent['hash']] = torrent
            except (json.JSONDecodeError, IOError):
                current_app.logger.error("Scheduler: Could not read or parse dashboard_torrents.json, starting fresh.")
                pass

        # Step 2: Fetch new torrents from Prowlarr
        last_refresh = get_last_refresh_time()
        prowlarr_categories = current_app.config.get('DASHBOARD_PROWLARR_CATEGORIES', [])
        raw_torrents_from_prowlarr = get_latest_from_prowlarr(
            categories=prowlarr_categories,
            min_date=last_refresh
        )

        if raw_torrents_from_prowlarr is None:
            current_app.logger.error("Scheduler: Could not retrieve data from Prowlarr. Aborting job.")
            return

        # Post-filter results by category because Prowlarr API can be unreliable
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
        for raw_torrent in raw_torrents_from_prowlarr:
            torrent = _normalize_torrent(raw_torrent)
            if not torrent or torrent['hash'] in existing_torrents_map:
                continue

            # This is a genuinely new torrent
            new_torrents_found += 1
            torrent['is_new'] = True

            if any(re.search(kw, torrent['title'], re.IGNORECASE) for kw in exclude_keywords):
                continue

            media_type = _determine_media_type(raw_torrent, sonarr_cat_ids, radarr_cat_ids)
            torrent['type'] = media_type

            if media_type == 'movie':
                year_match = re.search(r'\b(19\d{2}|20\d{2})\b', torrent['title'])
                if year_match and int(year_match.group(1)) < min_movie_year:
                    continue

            existing_torrents_map[torrent['hash']] = torrent

        current_app.logger.info(f"Scheduler: Found {new_torrents_found} new torrents from Prowlarr.")

        # Step 4: Re-evaluate status and enrich ALL torrents
        if tmdb_client:
            for torrent in existing_torrents_map.values():
                if 'type' not in torrent:
                     raw_info = next((t for t in raw_torrents_from_prowlarr if (_normalize_torrent(t) or {}).get('hash') == torrent['hash']), None)
                     torrent['type'] = _determine_media_type(raw_info, sonarr_cat_ids, radarr_cat_ids) if raw_info else 'unknown'

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
        final_torrents = [t for t in final_torrents if t.get('publishDate')]
        final_torrents.sort(key=lambda x: x['publishDate'], reverse=True)

        for torrent in final_torrents:
            if isinstance(torrent['publishDate'], datetime):
                torrent['publishDate'] = torrent['publishDate'].isoformat()

        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(final_torrents, f, indent=2)

        set_last_refresh_time()
        current_app.logger.info("Scheduler: Dashboard refresh job finished successfully.")
        return final_torrents

    except Exception as e:
        current_app.logger.error(f"Scheduler: Error in scheduled_dashboard_refresh: {e}", exc_info=True)
        return None

# Helper functions adapted from dashboard/routes.py

def _normalize_torrent(raw_torrent):
    unique_id = raw_torrent.get('hash') or raw_torrent.get('guid')
    if not unique_id:
        return None
    publish_date_str = raw_torrent.get('publishDate') or raw_torrent.get('uploaded_at')
    publish_date = datetime.fromisoformat(publish_date_str.replace('Z', '+00:00')) if publish_date_str else None
    category_name = raw_torrent.get('categoryDescription') or (raw_torrent.get('categories')[0].get('name') if raw_torrent.get('categories') else None)
    category_ids = [cat.get('id') for cat in raw_torrent.get('categories', []) if cat.get('id') is not None]
    tmdb_id_raw = raw_torrent.get('tmdbId') or raw_torrent.get('tmdb_id')
    tmdb_id_int = int(tmdb_id_raw) if tmdb_id_raw and str(tmdb_id_raw).isdigit() else None

    return {
        'hash': str(unique_id), 'title': raw_torrent.get('title'), 'size': raw_torrent.get('size'),
        'seeders': raw_torrent.get('seeders'), 'leechers': raw_torrent.get('leechers'),
        'indexerId': raw_torrent.get('indexerId'), 'type': raw_torrent.get('type'),
        'tmdbId': tmdb_id_int, 'guid': raw_torrent.get('guid'),
        'downloadUrl': raw_torrent.get('guid'), 'detailsUrl': raw_torrent.get('infoUrl'),
        'publishDate': publish_date, 'category': category_name, 'category_ids': category_ids,
        'indexer': raw_torrent.get('indexer'), 'tvdbId': None, 'overview': '', 'poster_url': '',
        'statuses': [], 'is_new': False, 'parsed_data': {},
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
    if not raw_torrent: return 'unknown'
    cat_ids = {cat.get('id') for cat in raw_torrent.get('categories', [])}
    if cat_ids.intersection(radarr_cat_ids): return 'movie'
    if cat_ids.intersection(sonarr_cat_ids): return 'tv'
    return raw_torrent.get('type', 'unknown')

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
