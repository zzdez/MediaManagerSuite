import requests
from flask import current_app
import re
import logging

# Configure logging
logger = logging.getLogger(__name__)

# ==============================================================================
# --- UTILITY FUNCTIONS ---
# ==============================================================================

def parse_media_name(item_name: str) -> dict:
    """
    Parses a media item name to determine if it's a TV show or a movie and extracts details.
    """
    logger.debug(f"parse_media_name: Called with item_name='{item_name}'")
    # Regex patterns for TV shows
    tv_patterns = [
        re.compile(r"^(?P<title>.+?)[ ._]?S(?P<season>\d{1,2})E(?P<episode>\d{1,3})", re.IGNORECASE),
        re.compile(r"^(?P<title>.+?)[ ._]?Season[ ._]?(?P<season>\d{1,2})[ ._]?Episode[ ._]?(?P<episode>\d{1,3})", re.IGNORECASE),
        re.compile(r"^(?P<title>.+?)[ ._]?(?P<season>\d{1,2})x(?P<episode>\d{1,3})", re.IGNORECASE), # e.g. Show.Title.1x01
        re.compile(r"^(?P<title>(?:[A-Za-z0-9._ ()-]+?)+)(?:[._\s]+S(?P<season>\d{1,2}))(?:[._\s]+E(?P<episode>\d{1,3}))",re.IGNORECASE), # General SxxExx with flexible separators
        re.compile(r"^(?P<title>.+?)[ ._](?P<year>(?:19|20)\d{2})[ ._]S(?P<season>\d{1,2})E(?P<episode>\d{1,3})", re.IGNORECASE), # Title Year SxxExx
        re.compile(r"^(?P<title>.+?)[ ._]S(?P<season>\d{1,2})[ ._]E(?P<episode>\d{1,3})[ ._](?P<year>(?:19|20)\d{2})", re.IGNORECASE), # Title SxxExx Year
    ]

    # Regex patterns for movies
    movie_patterns = [
        re.compile(r"^(?P<title>.+?)[ ._]\((?P<year>(?:19|20)\d{2})\)", re.IGNORECASE), # Movie Title (YYYY)
        re.compile(r"^(?P<title>.+?)[ ._](?P<year>(?:19|20)\d{2})[ ._](?!S\d{2}E\d{2})", re.IGNORECASE), # Movie.Title.YYYY (ensure not a TV show year)
        re.compile(r"^(?P<title>.+?)[ ._\[(](?P<year>(?:19|20)\d{2})[\])].*$", re.IGNORECASE), # More flexible movie year, removed lookbehind
    ]

    result = {
        "type": "unknown",
        "title": None,
        "year": None,
        "season": None,
        "episode": None,
        "raw_name": item_name,
    }

    # Check for TV show patterns first
    for pattern in tv_patterns:
        match = pattern.match(item_name)
        if match:
            data = match.groupdict()
            result["type"] = "tv"
            result["title"] = data.get("title", "").replace('.', ' ').replace('_', ' ').strip()
            result["season"] = int(data.get("season")) if data.get("season") else None
            result["episode"] = int(data.get("episode")) if data.get("episode") else None
            result["year"] = int(data.get("year")) if data.get("year") else None # Year can be part of TV show name
            logger.info(f"Parsed as TV show: {item_name} -> {result}")
            logger.debug(f"parse_media_name: Returning: {result}")
            return result

    # Check for movie patterns if not identified as TV show
    for pattern in movie_patterns:
        match = pattern.match(item_name)
        if match:
            data = match.groupdict()
            # Avoid misinterpreting season/episode numbers as years if they are at the end
            potential_year_str = data.get("year")
            if potential_year_str:
                try:
                    year_val = int(potential_year_str)
                    if 1900 <= year_val <= 2099: # Basic sanity check for year
                        # If a year is found and it's not part of a clear TV pattern, assume movie
                        result["type"] = "movie"
                        result["title"] = data.get("title", "").replace('.', ' ').replace('_', ' ').strip()
                        result["year"] = year_val
                        logger.info(f"Parsed as movie: {item_name} -> {result}")
                        logger.debug(f"parse_media_name: Returning: {result}")
                        return result
                except ValueError:
                    pass # Not a valid year

    # If no pattern matched strongly
    logger.info(f"Could not determine type for: {item_name}, returning as 'unknown'")
    # Attempt to clean title even if unknown type
    cleaned_title = re.sub(r'[\._]', ' ', item_name) # Replace dots/underscores with spaces
    cleaned_title = re.sub(r'\s{2,}', ' ', cleaned_title).strip() # Remove multiple spaces
    # Try to remove common tags like 1080p, WEB-DL etc. for a cleaner unknown title
    common_tags_pattern = r'(1080p|720p|4K|WEB-DL|WEBRip|BluRay|x264|x265|AAC|DTS|HDRip|HDTV|XviD|DivX).*$'
    cleaned_title = re.sub(common_tags_pattern, '', cleaned_title, flags=re.IGNORECASE).strip()
    result["title"] = cleaned_title if cleaned_title else item_name

    logger.debug(f"parse_media_name: Returning: {result}")
    return result

# ==============================================================================
# --- RADARR CLIENT FUNCTIONS ---
# ==============================================================================

def trigger_radarr_scan(download_path):
    """Triggers Radarr's DownloadedMoviesScan command for a specific path."""
    command_payload = {
        'name': 'DownloadedMoviesScan',
        'path': download_path,
        'importMode': 'Move', # Ensures the item is moved by Radarr
        'downloadClientId': 'MediaManagerSuite_SFTP_Scanner' # Optional: for easier identification in Radarr logs
    }
    current_app.logger.info(f"Radarr: Sending DownloadedMoviesScan command for path: {download_path}")
    response = _radarr_api_request('POST', 'command', json_data=command_payload)
    # Radarr's response for command execution usually includes an 'id' and 'status' or 'state'
    current_app.logger.debug(f"Radarr raw status check: response.get('status') is '{response.get('status')}', type is {type(response.get('status'))}")
    if response and (response.get('status') == 'started' or response.get('state') == 'started' or response.get('status') == 'success' or response.get('status') == 'queued'):
        current_app.logger.info(f"Radarr: Successfully triggered DownloadedMoviesScan for {download_path}. Response: {response}")
        return True
    else:
        current_app.logger.error(f"Radarr: Failed to trigger DownloadedMoviesScan for {download_path}. Response: {response}")
        return False

def _radarr_api_request(method, endpoint, params=None, json_data=None):
    """Helper function to make requests to the Radarr API."""
    config = current_app.config
    headers = {'X-Api-Key': config.get('RADARR_API_KEY')}
    url = f"{config.get('RADARR_URL', '').rstrip('/')}/api/v3/{endpoint.lstrip('/')}"

    try:
        response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Radarr API request failed: {e}")
        return None

def get_radarr_tag_id(tag_label):
    """Finds a tag by its label in Radarr and returns its ID. Creates it if not found."""
    all_tags = _radarr_api_request('GET', 'tag')
    if all_tags is None:
        return None

    for tag in all_tags:
        if tag.get('label', '').lower() == tag_label.lower():
            current_app.logger.info(f"Radarr: Found existing tag '{tag_label}' with ID {tag['id']}.")
            return tag['id']

    current_app.logger.info(f"Radarr: Tag '{tag_label}' not found. Creating it...")
    new_tag = _radarr_api_request('POST', 'tag', json_data={'label': tag_label})
    if new_tag and 'id' in new_tag:
        current_app.logger.info(f"Radarr: Successfully created tag '{tag_label}' with ID {new_tag['id']}.")
        return new_tag['id']
    else:
        current_app.logger.error(f"Radarr: Failed to create tag '{tag_label}'. Response: {new_tag}")
        return None

def get_radarr_movie_by_guid(plex_guid):
    """Finds a movie in Radarr using a Plex GUID (e.g., 'imdb://tt1234567')."""
    if 'imdb' in plex_guid:
        id_key = 'imdbId'
        id_value = plex_guid.split('//')[-1]
    elif 'tmdb' in plex_guid:
            id_key = 'tmdbId'
            try:
                id_value = int(plex_guid.split('//')[-1])
            except (ValueError, IndexError):
                current_app.logger.error(f"Impossible d'extraire un entier du tmdb_guid: {plex_guid}")
                return None
    else:
        return None

    movies = _radarr_api_request('GET', 'movie')
    if movies:
        for movie in movies:
            if movie.get(id_key) == id_value:
                return movie
    return None

def update_radarr_movie(movie_data):
    """Updates a movie in Radarr using its full data object."""
    # Radarr's PUT endpoint requires the movie ID in the URL.
    return _radarr_api_request('PUT', f"movie/{movie_data['id']}", json_data=movie_data)

def check_radarr_movie_exists(movie_title: str, movie_year: int = None) -> bool:
    """
    Checks if a movie exists in Radarr and has an associated, non-missing file.
    """
    logger.debug(f"check_radarr_movie_exists: Called with title='{movie_title}', year={movie_year}")
    logger.info(f"Radarr: Checking if movie exists: {movie_title} ({movie_year})")
    # Fetch all movies from Radarr. This is simpler than 'lookup' for existing movies.
    # In a very large library, this could be slow. Consider optimizations if performance issues arise.
    logger.debug("check_radarr_movie_exists: About to call _radarr_api_request('GET', 'movie')")
    all_movies = _radarr_api_request('GET', 'movie')
    logger.debug(f"check_radarr_movie_exists: _radarr_api_request('GET', 'movie') returned (first 50 chars): {str(all_movies)[:50] if all_movies else 'None'}")
    if not all_movies:
        logger.error("Radarr: Failed to fetch movie list from Radarr.")
        logger.debug(f"check_radarr_movie_exists: Returning {False}")
        return False

    found_movies = []
    for movie in all_movies:
        # Basic title match (case-insensitive, remove common punctuation)
        cleaned_api_title = re.sub(r'[^\w\s]', '', movie.get('title', '')).lower()
        cleaned_search_title = re.sub(r'[^\w\s]', '', movie_title).lower()

        if cleaned_search_title == cleaned_api_title:
            if movie_year:
                if movie.get('year') == movie_year:
                    found_movies.append(movie)
            else:
                found_movies.append(movie)

    if not found_movies:
        logger.info(f"Radarr: Movie '{movie_title}' ({movie_year if movie_year else 'Any Year'}) not found.")
        logger.debug(f"check_radarr_movie_exists: Returning {False}")
        return False

    # If multiple movies match, prefer the one with a matching year or log ambiguity.
    # For now, we'll check the first one found if no year is specified,
    # or the one matching the year.
    target_movie = None
    if len(found_movies) == 1:
        target_movie = found_movies[0]
    elif len(found_movies) > 1:
        if movie_year:
            # Already filtered by year if movie_year was provided
            target_movie = found_movies[0] # Pick first of year-matched
            logger.info(f"Radarr: Multiple movies found for '{movie_title}' ({movie_year}). Using first match: ID {target_movie.get('id')}")
        else:
            # No year provided, multiple title matches. This is ambiguous.
            # For now, take the first one and log. A more robust solution might involve other heuristics.
            target_movie = found_movies[0]
            logger.warning(f"Radarr: Multiple movies found for '{movie_title}' (no year specified). "
                           f"Using first match: {target_movie.get('title')} ({target_movie.get('year')}), ID {target_movie.get('id')}. "
                           f"Consider providing a year for accuracy.")

    if not target_movie: # Should not happen if found_movies was populated, but as a safeguard.
        logger.info(f"Radarr: Movie '{movie_title}' ({movie_year}) not conclusively found after filtering.")
        logger.debug(f"check_radarr_movie_exists: Returning {False}")
        return False

    # Check if the movie has a file and is not missing
    # 'hasFile' is a primary indicator. 'sizeOnDisk' > 0 confirms the file is not empty.
    # 'status' can also be 'downloaded'
    movie_file_path = target_movie.get('movieFile', {}).get('path', 'N/A')
    has_file = target_movie.get('hasFile', False)
    size_on_disk = target_movie.get('sizeOnDisk', 0)

    if has_file and size_on_disk > 0:
        logger.debug(f"check_radarr_movie_exists: Condition for True met. Movie: '{target_movie.get('title')}', Year: {target_movie.get('year')}, hasFile: {has_file}, sizeOnDisk: {size_on_disk}, Path: {movie_file_path}")
        logger.info(f"Radarr: Movie '{target_movie.get('title')}' ({target_movie.get('year')}) exists with file. Path: {movie_file_path}, Size: {size_on_disk}. Guardrail will consider it PRESENT.")
        return True
    else:
        logger.debug(f"check_radarr_movie_exists: Condition for True NOT met. Movie: '{target_movie.get('title')}', Year: {target_movie.get('year')}, hasFile: {has_file}, sizeOnDisk: {size_on_disk}, Path: {movie_file_path}")
        logger.info(f"Radarr: Movie '{target_movie.get('title')}' ({target_movie.get('year')}) found, but no valid file. Path: {movie_file_path}, hasFile: {has_file}, sizeOnDisk: {size_on_disk}. Guardrail will consider it ABSENT/MISSING.")
        return False

# ==============================================================================
# --- SONARR CLIENT FUNCTIONS ---
# ==============================================================================

def trigger_sonarr_scan(download_path):
    """Triggers Sonarr's DownloadedEpisodesScan command for a specific path."""
    command_payload = {
        'name': 'DownloadedEpisodesScan',
        'path': download_path,
        'importMode': 'Move', # Ensures the item is moved by Sonarr
        'downloadClientId': 'MediaManagerSuite_SFTP_Scanner' # Optional: for easier identification in Sonarr logs
    }
    current_app.logger.info(f"Sonarr: Sending DownloadedEpisodesScan command for path: {download_path}")
    response = _sonarr_api_request('POST', 'command', json_data=command_payload)
    current_app.logger.debug(f"Sonarr raw status check: response.get('status') is '{response.get('status')}', type is {type(response.get('status'))}")
    if response and (response.get('status') == 'started' or response.get('state') == 'started' or response.get('status') == 'success' or response.get('status') == 'queued'): # Sonarr API can be inconsistent here
        current_app.logger.info(f"Sonarr: Successfully triggered DownloadedEpisodesScan for {download_path}. Response: {response}")
        return True
    else:
        current_app.logger.error(f"Sonarr: Failed to trigger DownloadedEpisodesScan for {download_path}. Response: {response}")
        return False

def _sonarr_api_request(method, endpoint, params=None, json_data=None):
    """Helper function to make requests to the Sonarr API."""
    config = current_app.config
    headers = {'X-Api-Key': config.get('SONARR_API_KEY')}
    url = f"{config.get('SONARR_URL', '').rstrip('/')}/api/v3/{endpoint.lstrip('/')}"

    try:
        response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=20)
        response.raise_for_status()
        # Some Sonarr responses (like DELETE) have no JSON body but are successes (200 OK)
        if response.status_code == 200 and not response.text:
             return {"status": "success"}
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Sonarr API request failed: {e}")
        return None

def get_sonarr_tag_id(tag_label):
    """Finds a tag by its label in Sonarr and returns its ID. Creates it if not found."""
    all_tags = _sonarr_api_request('GET', 'tag')
    if all_tags is None: return None

    for tag in all_tags:
        if tag.get('label', '').lower() == tag_label.lower():
            current_app.logger.info(f"Sonarr: Found existing tag '{tag_label}' with ID {tag['id']}.")
            return tag['id']

    current_app.logger.info(f"Sonarr: Tag '{tag_label}' not found. Creating it...")
    new_tag = _sonarr_api_request('POST', 'tag', json_data={'label': tag_label})
    if new_tag and 'id' in new_tag:
        current_app.logger.info(f"Sonarr: Successfully created tag '{tag_label}' with ID {new_tag['id']}.")
        return new_tag['id']

    current_app.logger.error(f"Sonarr: Failed to create tag '{tag_label}'.")
    return None

def get_sonarr_series_by_guid(plex_guid):
    """Finds a series in Sonarr using a Plex GUID (e.g., 'tvdb://12345')."""
    id_value = None
    if 'tvdb' in plex_guid:
        id_key = 'tvdbId'
        try:
            id_value = int(plex_guid.split('//')[-1])
        except (ValueError, IndexError):
            return None
    elif 'imdb' in plex_guid:
        id_key = 'imdbId'
        id_value = plex_guid.split('//')[-1]
    else:
        return None

    all_series = _sonarr_api_request('GET', 'series')
    if all_series:
        for series in all_series:
            if series.get(id_key) == id_value:
                return series
    return None

def get_sonarr_series_by_id(series_id):
    """Fetches a single series from Sonarr by its internal ID."""
    return _sonarr_api_request('GET', f'series/{series_id}')

def update_sonarr_series(series_data):
    """Updates a series in Sonarr using its full data object."""
    # Sonarr's PUT endpoint for a single series includes the ID in the URL.
    return _sonarr_api_request('PUT', f"series/{series_data['id']}", json_data=series_data)

def get_sonarr_episode_files(series_id):
    """Gets a list of all episode files for a given series ID."""
    return _sonarr_api_request('GET', 'episodefile', params={'seriesId': series_id})

def delete_sonarr_episode_file(episode_file_id):
    """Deletes a single episode file from Sonarr's database and from disk."""
    return _sonarr_api_request('DELETE', f'episodefile/{episode_file_id}')

# ... (après les autres fonctions sonarr)

def get_all_sonarr_series():
    """Fetches all series from Sonarr."""
    current_app.logger.info("Récupération de toutes les séries depuis l'API Sonarr.")
    return _sonarr_api_request('GET', 'series')

def check_sonarr_episode_exists(series_title: str, season_number: int, episode_number: int) -> bool:
    """
    Checks if a specific TV show episode exists in Sonarr and has a file.
    """
    logger.debug(f"check_sonarr_episode_exists: Called with series='{series_title}', S{season_number}E{episode_number}")
    logger.info(f"Sonarr: Checking if episode exists: {series_title} S{season_number:02d}E{episode_number:02d}")

    logger.debug("check_sonarr_episode_exists: About to call get_all_sonarr_series()")
    all_series = get_all_sonarr_series() # Uses the existing function
    logger.debug(f"check_sonarr_episode_exists: get_all_sonarr_series() returned (first 50 chars): {str(all_series)[:50] if all_series else 'None'}")
    if not all_series:
        logger.error(f"Sonarr: Could not retrieve series list to find '{series_title}'.")
        logger.debug(f"check_sonarr_episode_exists: Returning {False}")
        return False

    found_series = None
    # Normalize search title: lowercase and remove punctuation/special chars for robust matching.
    normalized_search_title = re.sub(r'[^\w\s]', '', series_title).lower()

    for series in all_series:
        # Normalize API title similarly
        normalized_api_title = re.sub(r'[^\w\s]', '', series.get('title', '')).lower()
        if normalized_api_title == normalized_search_title:
            found_series = series
            break
        # Fallback to checking titleSlug if direct title match fails
        normalized_api_titleslug = series.get('titleSlug', '').lower()
        if normalized_api_titleslug == normalized_search_title.replace(" ", "-"): # titleSlug uses dashes
            found_series = series
            logger.info(f"Sonarr: Matched '{series_title}' using titleSlug: '{series.get('title')}' (ID: {series.get('id')})")
            break


    if not found_series:
        logger.warning(f"Sonarr: Series '{series_title}' not found in Sonarr.")
        logger.debug(f"check_sonarr_episode_exists: Returning {False}")
        return False

    series_id = found_series.get('id')
    logger.info(f"Sonarr: Found series '{found_series.get('title')}' with ID {series_id}. Now checking for S{season_number:02d}E{episode_number:02d}.")

    # Fetch all episodes for the series
    # Sonarr's episode endpoint requires seriesId.
    # We filter by season and episode number client-side.
    logger.debug(f"check_sonarr_episode_exists: About to call _sonarr_api_request('GET', 'episode') for series_id={series_id}")
    episodes_data = _sonarr_api_request('GET', 'episode', params={'seriesId': series_id})
    logger.debug(f"check_sonarr_episode_exists: _sonarr_api_request('GET', 'episode') returned (first 50 chars): {str(episodes_data)[:50] if episodes_data else 'None'}")
    if not episodes_data: # This could be an empty list if series has no episodes, or None on API error
        logger.error(f"Sonarr: Failed to fetch episodes for series ID {series_id} ('{found_series.get('title')}').")
        logger.debug(f"check_sonarr_episode_exists: Returning {False}")
        return False

    if not isinstance(episodes_data, list):
        logger.error(f"Sonarr: Unexpected response format for episodes of series ID {series_id}. Expected list, got {type(episodes_data)}.")
        logger.debug(f"check_sonarr_episode_exists: Returning {False}")
        return False


    target_episode = None
    for episode in episodes_data:
        if episode.get('seasonNumber') == season_number and episode.get('episodeNumber') == episode_number:
            target_episode = episode
            break

    if not target_episode:
        logger.info(f"Sonarr: Episode S{season_number:02d}E{episode_number:02d} for series '{found_series.get('title')}' not found.")
        logger.debug(f"check_sonarr_episode_exists: Returning {False}")
        return False

    # Check if the episode has a file and is not missing
    # 'hasFile' should be true, and 'episodeFileId' > 0 indicates a linked file.
    # Also, the episode should be monitored, and its file should have a positive size.
    if (target_episode.get('hasFile', False) and
        target_episode.get('episodeFileId', 0) > 0 and
        target_episode.get('monitored', False)): # Ensure episode is monitored

        # Optionally, fetch episode file details to check size, though hasFile and episodeFileId are strong indicators.
        # episode_file_details = _sonarr_api_request('GET', f'episodefile/{target_episode.get("episodeFileId")}')
        # if episode_file_details and episode_file_details.get('size', 0) > 0:
        #    logger.info(f"Sonarr: Episode S{season_number:02d}E{episode_number:02d} for '{found_series.get('title')}' exists, is monitored, and has a valid file. File ID: {target_episode.get('episodeFileId')}")
        #    return True
        # else:
        #    logger.warning(f"Sonarr: Episode S{season_number:02d}E{episode_number:02d} for '{found_series.get('title')}' hasFile=True, but file details query failed or size is 0.")
        #    return False

        # Simpler check without fetching episode file details again if not strictly needed by requirements
        episode_has_file = target_episode.get('hasFile', False)
        episode_file_id = target_episode.get('episodeFileId', 0)
        episode_monitored = target_episode.get('monitored', False)

        episode_file_path_obj = target_episode.get('episodeFile', {})
        episode_file_path = episode_file_path_obj.get('path', 'N/A') if episode_file_path_obj else 'N/A'

        logger.debug(f"check_sonarr_episode_exists: Condition for True met. Episode: S{season_number:02d}E{episode_number:02d} for '{found_series.get('title')}', hasFile: {episode_has_file}, episodeFileId: {episode_file_id}, monitored: {episode_monitored}, Path: {episode_file_path}")
        logger.info(f"Sonarr: Episode S{season_number:02d}E{episode_number:02d} for '{found_series.get('title')}' exists with file. Path: {episode_file_path}. Guardrail will consider it PRESENT.")
        return True
    else:
        episode_has_file = target_episode.get('hasFile', False)
        episode_file_id = target_episode.get('episodeFileId', 0)
        episode_monitored = target_episode.get('monitored', False)
        logger.debug(f"check_sonarr_episode_exists: Condition for True NOT met for S{season_number:02d}E{episode_number:02d} of '{found_series.get('title')}': "
                    f"hasFile: {episode_has_file}, episodeFileId: {episode_file_id}, monitored: {episode_monitored}")
        logger.info(f"Sonarr: Episode S{season_number:02d}E{episode_number:02d} for '{found_series.get('title')}' found, but conditions for existing file not met. hasFile: {episode_has_file}, episodeFileId: {episode_file_id}, monitored: {episode_monitored}. Guardrail will consider it ABSENT/MISSING.")
        return False