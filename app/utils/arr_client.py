import os
import time
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
        # More specific patterns first
        re.compile(r"^(?P<title>.+?)[._\s](?P<year>(?:19|20)\d{2})[._\s]S(?P<season>\d{1,2})[._\s]?[E.]?(?P<episode>\d{1,3})", re.IGNORECASE), # Title.Year.S01.E01
        re.compile(r"^(?P<title>.+?)[._\s]S(?P<season>\d{1,2})[._\s]?[E.]?(?P<episode>\d{1,3})[._\s](?P<year>(?:19|20)\d{2})", re.IGNORECASE), # Title.S01.E01.Year
        re.compile(r"^(?P<title>.+?)[._\s]Season[._\s]?(?P<season>\d{1,2})[._\s]?Episode[._\s]?(?P<episode>\d{1,3})", re.IGNORECASE), # Title.Season.01.Episode.01
        re.compile(r"^(?P<title>.+?)[._\s]?(?P<season>\d{1,2})x(?P<episode>\d{1,3})", re.IGNORECASE), # Title.1x01
        # Generic SxxExx
        re.compile(r"^(?P<title>.+?)[._\s]S(?P<season>\d{1,2})[._\s]?[E.]?(?P<episode>\d{1,3})", re.IGNORECASE),
        # Season pack
        re.compile(r"^(?P<title>.+?)(?:[._\s](?P<year>(?:19|20)\d{2}))?(?:[._\s]+(?:DOC|SUBPACK|SEASON|VOL|DISC|DISQUE|PART))?[._\s]*S(?P<season>\d{1,2})(?![E\d])", re.IGNORECASE),
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
    base_name, _ = os.path.splitext(item_name)
    cleaned_title = re.sub(r'[\._]', ' ', base_name) # Replace dots/underscores with spaces
    cleaned_title = re.sub(r'\s{2,}', ' ', cleaned_title).strip() # Remove multiple spaces
    # Try to remove common tags like 1080p, WEB-DL etc. for a cleaner unknown title
    common_tags_pattern = r'(1080p|720p|4K|WEB-DL|WEBRip|BluRay|x264|x265|AAC|DTS|HDRip|HDTV|XviD|DivX).*$'
    cleaned_title = re.sub(common_tags_pattern, '', cleaned_title, flags=re.IGNORECASE).strip()
    result["title"] = cleaned_title if cleaned_title else base_name

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
    """Finds a movie in Radarr using a Plex GUID (e.g., 'imdb://tt1234567', 'tmdb:12345')."""
    id_key = None
    id_value = None
    try:
        if 'imdb' in plex_guid:
            id_key = 'imdbId'
            # Handles imdb://tt1234567
            id_value = re.split(r'[:/]+', plex_guid)[-1]
        elif 'tmdb' in plex_guid:
            id_key = 'tmdbId'
            # Handles tmdb://12345 and tmdb:12345
            id_value = int(re.split(r'[:/]+', plex_guid)[-1])
        else:
            return None
    except (ValueError, IndexError):
        current_app.logger.error(f"Could not parse ID from Radarr GUID: {plex_guid}")
        return None

    movies = _radarr_api_request('GET', 'movie')
    if movies:
        # --- START DEBUG LOGGING ---
        if id_key == 'tmdbId':
            all_tmdb_ids = [m.get('tmdbId') for m in movies if m.get('tmdbId')]
            current_app.logger.info(f"DEBUG: Searching for tmdbId: {id_value}")
            current_app.logger.info(f"DEBUG: All tmdbIds found in Radarr: {all_tmdb_ids}")
        # --- END DEBUG LOGGING ---
        for movie in movies:
            if movie.get(id_key) and str(movie.get(id_key)) == str(id_value):
                return movie
    return None

def get_radarr_movie_by_id(movie_id):
    """Fetches a single movie from Radarr by its internal ID."""
    return _radarr_api_request('GET', f'movie/{movie_id}')

def update_radarr_movie(movie_data):
    """Updates a movie in Radarr using its full data object."""
    return _radarr_api_request('PUT', f"movie/{movie_data['id']}", json_data=movie_data)

def search_radarr_by_title(title):
    """Searches for movies in Radarr by title using the lookup endpoint."""
    return _radarr_api_request('GET', 'movie/lookup', params={'term': title})

def find_radarr_movie_by_title(title, retries=3, delay=5):
    """
    Recherche un film dans la bibliothèque Radarr par son titre avec des tentatives multiples.
    Retourne le dictionnaire du film si trouvé, sinon None.
    """
    attempt = 0
    while attempt < retries:
        try:
            all_movies = _radarr_api_request('GET', 'movie')
            if not all_movies:
                attempt += 1
                if attempt < retries:
                    current_app.logger.info(f"Radarr: Tentative {attempt}/{retries} - La liste des films est vide, nouvelle tentative dans {delay}s...")
                    time.sleep(delay)
                continue

            for movie in all_movies:
                if movie.get('title', '').lower() == title.lower():
                    current_app.logger.info(f"Radarr: Found matching movie '{title}' in library (ID: {movie.get('id')}).")
                    return movie

            current_app.logger.warning(f"Radarr: Movie '{title}' not found in library after full scan.")
            return None # Exit after successful scan

        except Exception as e:
            current_app.logger.error(f"Error on attempt {attempt + 1} for Radarr movie by title '{title}': {e}", exc_info=True)
            attempt += 1
            if attempt < retries:
                time.sleep(delay)

    current_app.logger.error(f"Radarr: Movie '{title}' not found after {retries} attempts.")
    return None

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

    movie_has_file_flag = target_movie.get('hasFile', False)
    size_on_disk = target_movie.get('sizeOnDisk', 0)
    movie_file_obj = target_movie.get('movieFile') # Get the movieFile object

    # Initialize path for logging, default to problematic values
    movie_file_path = "N/A"

    if movie_file_obj:
        movie_file_path = movie_file_obj.get('path', 'N/A') # Path might still be None or empty

    # Stricter condition
    if (movie_has_file_flag and
        size_on_disk > 0 and
        movie_file_obj and # Ensure movieFile object exists
        movie_file_path and movie_file_path != "N/A" and len(movie_file_path.strip()) > 0): # Ensure path is valid and non-empty

        logger.debug(f"check_radarr_movie_exists: Condition for True met. Movie: '{target_movie.get('title')}', Year: {target_movie.get('year')}, hasFile: {movie_has_file_flag}, sizeOnDisk: {size_on_disk}, movieFile_exists: True, Path: {movie_file_path}")
        logger.info(f"Radarr: Movie '{target_movie.get('title')}' ({target_movie.get('year')}) exists with valid file. Path: {movie_file_path}, Size: {size_on_disk}B. Guardrail will consider it PRESENT.")
        return True
    else:
        logger.debug(f"check_radarr_movie_exists: Condition for True NOT met. Movie: '{target_movie.get('title')}', Year: {target_movie.get('year')}, hasFile: {movie_has_file_flag}, sizeOnDisk: {size_on_disk}, movieFile_exists: {movie_file_obj is not None}, Path: {movie_file_path}")
        logger.info(f"Radarr: Movie '{target_movie.get('title')}' ({target_movie.get('year')}) found, but conditions for existing valid file not met. "
                    f"hasFile: {movie_has_file_flag}, sizeOnDisk: {size_on_disk}B, Path: {movie_file_path}. Guardrail will consider it ABSENT/MISSING.")
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
    """Finds a series in Sonarr using a Plex GUID (e.g., 'tvdb://12345', 'tvdb:12345')."""
    id_key = None
    id_value = None
    try:
        if 'tvdb' in plex_guid:
            id_key = 'tvdbId'
            # Handles tvdb://12345 and tvdb:12345
            id_value = int(re.split(r'[:/]+', plex_guid)[-1])
        elif 'imdb' in plex_guid:
            id_key = 'imdbId'
            # Handles imdb://tt1234567
            id_value = re.split(r'[:/]+', plex_guid)[-1]
        else:
            return None
    except (ValueError, IndexError):
        current_app.logger.error(f"Could not parse ID from Sonarr GUID: {plex_guid}")
        return None

    all_series = _sonarr_api_request('GET', 'series')
    if all_series:
        for series in all_series:
            if series.get(id_key) and str(series.get(id_key)) == str(id_value):
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

def search_sonarr_by_title(title):
    """Searches for series in Sonarr by title."""
    # L'endpoint de lookup de Sonarr est différent de celui de Radarr
    return _sonarr_api_request('GET', 'series/lookup', params={'term': title})

def search_sonarr_series_by_title_and_year(title, year=None):
    """
    Searches for series in Sonarr's library by title, with an optional year for better matching.
    This function searches within series already present in Sonarr.
    """
    logger.info(f"Sonarr: Searching library for title='{title}', year={year}")
    all_series = get_all_sonarr_series()
    if not all_series:
        logger.error("Sonarr: Could not get series list for title search.")
        return None

    # Normalize search title for robust matching
    normalized_search_title = re.sub(r'[^\w\s]', '', title).lower()

    possible_matches = []
    for series in all_series:
        normalized_api_title = re.sub(r'[^\w\s]', '', series.get('title', '')).lower()
        if normalized_api_title == normalized_search_title:
            possible_matches.append(series)

    if not possible_matches:
        logger.warning(f"Sonarr: No library match found for title '{title}'.")
        return None

    if len(possible_matches) == 1:
        logger.info(f"Sonarr: Found unique match for '{title}': ID {possible_matches[0].get('id')}")
        return possible_matches[0]

    # If multiple matches, use year to disambiguate
    if year:
        for series in possible_matches:
            if series.get('year') == year:
                logger.info(f"Sonarr: Found exact match for '{title}' ({year}): ID {series.get('id')}")
                return series

    logger.warning(f"Sonarr: Found {len(possible_matches)} matches for '{title}' but could not disambiguate with year {year}. Returning first match.")
    return possible_matches[0]

# ... (après les autres fonctions sonarr)

def get_all_sonarr_series():
    """Fetches all series from Sonarr."""
    current_app.logger.info("Récupération de toutes les séries depuis l'API Sonarr.")
    return _sonarr_api_request('GET', 'series')

def get_all_radarr_movies():
    """Fetches all movies from Radarr."""
    current_app.logger.info("Récupération de tous les films depuis l'API Radarr.")
    return _radarr_api_request('GET', 'movie')
    
def find_sonarr_series_by_title(title, retries=3, delay=5):
    """
    Recherche une série dans la bibliothèque Sonarr par son titre avec des tentatives multiples.
    Retourne le dictionnaire de la série si trouvée, sinon None.
    """
    attempt = 0
    while attempt < retries:
        try:
            all_series = get_all_sonarr_series()
            if not all_series:
                attempt += 1
                if attempt < retries:
                    current_app.logger.info(f"Sonarr: Tentative {attempt}/{retries} - La liste des séries est vide, nouvelle tentative dans {delay}s...")
                    time.sleep(delay)
                continue

            for series in all_series:
                if series.get('title', '').lower() == title.lower():
                    current_app.logger.info(f"Sonarr: Found matching series '{title}' in library (ID: {series.get('id')}).")
                    return series

            # If loop completes, series is not found
            current_app.logger.warning(f"Sonarr: Series '{title}' not found in library after full scan.")
            return None # Exit after successful scan, no need to retry if not found

        except Exception as e:
            current_app.logger.error(f"Error on attempt {attempt + 1} for Sonarr series by title '{title}': {e}", exc_info=True)
            attempt += 1
            if attempt < retries:
                time.sleep(delay)

    current_app.logger.error(f"Sonarr: Series '{title}' not found after {retries} attempts.")
    return None

def find_sonarr_series_by_release_name(release_name):
    """
    Trouve une série dans Sonarr en se basant sur le nom d'une release,
    en utilisant l'endpoint 'lookup' pour plus de fiabilité.
    Cette version gère intelligemment les titres avec une année.
    """
    logger.info(f"Recherche de la série Sonarr pour la release : '{release_name}'")
    parsed_info = parse_media_name(release_name)
    
    if not parsed_info or not parsed_info.get('title'):
        logger.warning(f"Impossible d'extraire un titre de '{release_name}'.")
        return None

    # --- DÉBUT DE LA CORRECTION ---
    # On construit un titre de recherche intelligent.
    title = parsed_info.get('title')
    year = parsed_info.get('year')
    
    # Tentative 1 : Recherche avec le titre et l'année (ex: "Invasion (2021)")
    if year:
        title_with_year = f"{title} ({year})"
        logger.info(f"Tentative de recherche avec titre et année : '{title_with_year}'")
        candidates = search_sonarr_by_title(title_with_year)
        
        # On vérifie si on a un résultat pertinent qui est déjà dans la bibliothèque
        if candidates and candidates[0].get('id', 0) > 0:
            best_match = candidates[0]
            logger.info(f"Série trouvée (avec année) et déjà dans Sonarr : '{best_match.get('title')}' (ID: {best_match.get('id')})")
            return best_match
        else:
            logger.info(f"Aucune série existante trouvée pour '{title_with_year}'. Tentative avec le titre seul.")
    
    # Tentative 2 (Fallback) : Recherche avec le titre seul (comportement original)
    logger.info(f"Tentative de recherche avec le titre seul : '{title}'")
    candidates = search_sonarr_by_title(title)
    # --- FIN DE LA CORRECTION ---

    if not candidates:
        logger.warning(f"Aucun candidat trouvé via lookup pour le titre '{title}'.")
        return None

    best_match = candidates[0]
    if best_match and best_match.get('id') and best_match.get('id') > 0:
        logger.info(f"Série trouvée (titre seul) et déjà dans Sonarr : '{best_match.get('title')}' (ID: {best_match.get('id')})")
        return best_match
    else:
        logger.warning(f"Série trouvée via lookup pour '{title}', mais elle ne semble pas être dans la bibliothèque Sonarr. Ignoré.")
        return None


def find_radarr_movie_by_release_name(release_name):
    """
    Trouve un film dans Radarr en se basant sur le nom d'une release,
    en utilisant l'endpoint 'lookup'.
    Cette version gère intelligemment les titres avec une année.
    """
    logger.info(f"Recherche du film Radarr pour la release : '{release_name}'")
    parsed_info = parse_media_name(release_name)

    if not parsed_info or not parsed_info.get('title'):
        logger.warning(f"Impossible d'extraire un titre de '{release_name}'.")
        return None

    # --- DÉBUT DE LA CORRECTION ---
    # On construit un titre de recherche intelligent.
    title = parsed_info.get('title')
    year = parsed_info.get('year')

    # Pour les films, la recherche avec l'année est la norme. On privilégie donc cette approche.
    # La fonction search_radarr_by_title devrait déjà bien gérer cela, mais on s'assure
    # que le titre envoyé est le plus simple possible pour ne pas perturber la recherche.
    # Le comportement original est probablement déjà correct pour Radarr, mais on clarifie.
    title_to_search = title 
    # --- FIN DE LA CORRECTION ---

    candidates = search_radarr_by_title(title_to_search)
    if not candidates:
        logger.warning(f"Aucun candidat trouvé via lookup pour le titre '{title_to_search}'.")
        return None

    best_match = candidates[0]
    if best_match and best_match.get('id') and best_match.get('id') > 0:
        logger.info(f"Film trouvé via lookup et déjà dans Radarr : '{best_match.get('title')}' (ID: {best_match.get('id')})")
        return best_match
    else:
        logger.warning(f"Film trouvé via lookup pour '{title_to_search}', mais il ne semble pas être dans la bibliothèque Radarr. Ignoré.")
        return None

def check_sonarr_episode_exists(series_title: str, season_number: int, episode_number: int) -> bool:
    """
    Checks if a specific TV show episode OR ANY EPISODE in a season exists in Sonarr and has a file.
    If 'episode_number' is None, it checks for the presence of the whole season.
    """
    logger.debug(f"check_sonarr_episode_exists: Called with series='{series_title}', S{season_number}E{episode_number}")
    
    # --- DÉBUT DU NOUVEAU BLOC DE LOGIQUE ---
    if episode_number is None:
        # This is a season pack check
        logger.info(f"Sonarr: Checking season pack S{season_number:02d} for series '{series_title}'.")
        # For a season pack, Presence = Not all episodes of the season have a file.
        # Absence = All episodes of the season are missing files.
        # This logic is complex. For now, a simplified check: does the series exist and is the season monitored?
        # A simple proxy for "do we want this season pack?"
        all_series = get_all_sonarr_series()
        if not all_series:
            logger.error(f"Sonarr: Could not get series list for season pack check of '{series_title}'.")
            return False # Cannot determine, assume absent to allow download.

        found_series = None
        normalized_search_title = re.sub(r'[^\w\s]', '', series_title).lower()
        for series in all_series:
            normalized_api_title = re.sub(r'[^\w\s]', '', series.get('title', '')).lower()
            if normalized_api_title == normalized_search_title:
                found_series = series
                break
        
        if not found_series:
            logger.info(f"Sonarr: Series '{series_title}' not in Sonarr. Guardrail considers season ABSENT.")
            return False # Series not even added, so we want the pack.

        # Check if the specific season is monitored
        for season_data in found_series.get('seasons', []):
            if season_data.get('seasonNumber') == season_number:
                if season_data.get('monitored', False):
                    # Season is monitored, which implies we want episodes from it.
                    # A more complex check could see if 'statistics.percentOfEpisodes' is 100
                    # but for Guardrail, if it's monitored, we assume a new pack is potentially useful.
                    logger.info(f"Sonarr: S{season_number:02d} of '{series_title}' is Monitored. Guardrail will assume it could be incomplete and considers it ABSENT to allow download.")
                    return False # Treat as "missing" to allow the download
                else:
                    logger.info(f"Sonarr: S{season_number:02d} of '{series_title}' is NOT Monitored. Guardrail will consider it PRESENT to block download.")
                    return True # Treat as "present" to block download of an unmonitored season.
        
        logger.info(f"Sonarr: S{season_number:02d} not found in season list for '{series_title}'. Guardrail considers it ABSENT.")
        return False # Season number doesn't exist for the series
    # --- FIN DU NOUVEAU BLOC DE LOGIQUE ---

    # Le reste du code de la fonction (pour les épisodes individuels) est inchangé
    logger.info(f"Sonarr: Checking if episode exists: {series_title} S{season_number:02d}E{episode_number:02d}")

    logger.debug("check_sonarr_episode_exists: About to call get_all_sonarr_series()")
    all_series = get_all_sonarr_series()
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
        logger.debug(f"check_sonarr_episode_exists: Returning {False} (failed to fetch episodes)")
        return False

    if not isinstance(episodes_data, list):
        logger.error(f"Sonarr: Unexpected response format for episodes of series ID {series_id}. Expected list, got {type(episodes_data)}.")
        logger.debug(f"check_sonarr_episode_exists: Returning {False} (unexpected episode data format)")
        return False

    if episode_number is not None:
        # Logic for checking a specific episode
        target_episode = None
        for episode_obj in episodes_data: # Renamed loop var
            if episode_obj.get('seasonNumber') == season_number and episode_obj.get('episodeNumber') == episode_number:
                target_episode = episode_obj
                break

        if not target_episode:
            logger.info(f"Sonarr: Specific episode S{season_number:02d}E{episode_number:02d} for series '{found_series.get('title')}' not found in fetched episode list.")
            logger.debug(f"check_sonarr_episode_exists: Returning {False} (specific episode not in list)")
            return False

        # Perform strict file check on target_episode
        episode_has_file_flag = target_episode.get('hasFile', False)
        episode_file_id = target_episode.get('episodeFileId', 0)
        episode_monitored = target_episode.get('monitored', False)
        episode_file_obj = target_episode.get('episodeFile')
        episode_file_path = "N/A"; episode_file_size = 0
        if episode_file_obj:
            episode_file_path = episode_file_obj.get('path', 'N/A')
            episode_file_size = episode_file_obj.get('size', 0)

        if (episode_has_file_flag and episode_file_id > 0 and episode_monitored and
            episode_file_obj and episode_file_path and episode_file_path != "N/A" and len(episode_file_path.strip()) > 0 and
            episode_file_size > 0):
            logger.debug(f"check_sonarr_episode_exists: Condition for True met for specific episode. Episode: S{season_number:02d}E{episode_number:02d} for '{found_series.get('title')}', hasFile: {episode_has_file_flag}, episodeFileId: {episode_file_id}, monitored: {episode_monitored}, Path: {episode_file_path}, Size: {episode_file_size}")
            logger.info(f"Sonarr: Episode S{season_number:02d}E{episode_number:02d} for '{found_series.get('title')}' exists with valid file. Path: {episode_file_path}, Size: {episode_file_size}B. Guardrail will consider it PRESENT.")
            return True
        else:
            logger.debug(f"check_sonarr_episode_exists: Condition for True NOT met for specific episode S{season_number:02d}E{episode_number:02d} of '{found_series.get('title')}': "
                        f"hasFile_flag: {episode_has_file_flag}, episodeFileId: {episode_file_id}, monitored: {episode_monitored}, episodeFile_obj_exists: {episode_file_obj is not None}, Path: {episode_file_path}, Size: {episode_file_size}")
            logger.info(f"Sonarr: Episode S{season_number:02d}E{episode_number:02d} for '{found_series.get('title')}' found, but conditions for existing valid file not met. "
                        f"hasFile: {episode_has_file_flag}, monitored: {episode_monitored}, Path: {episode_file_path}, Size: {episode_file_size}B. Guardrail will consider it ABSENT/MISSING.")
            return False

    else: # episode_number is None, checking for season pack (any valid file in season)
        logger.info(f"Sonarr: Checking for any valid files in S{season_number:02d} for series '{found_series.get('title')}' (season pack check).")
        for episode_in_season in episodes_data:
            if episode_in_season.get('seasonNumber') == season_number:
                # Perform the full strict file presence check on episode_in_season
                ep_has_file = episode_in_season.get('hasFile', False)
                ep_file_id = episode_in_season.get('episodeFileId', 0)
                ep_monitored = episode_in_season.get('monitored', False)
                ep_file_obj = episode_in_season.get('episodeFile')
                ep_file_path = "N/A"; ep_file_size = 0
                if ep_file_obj:
                    ep_file_path = ep_file_obj.get('path', 'N/A')
                    ep_file_size = ep_file_obj.get('size', 0)

                if (ep_has_file and ep_file_id > 0 and ep_monitored and
                    ep_file_obj and ep_file_path and ep_file_path != "N/A" and len(ep_file_path.strip()) > 0 and
                    ep_file_size > 0):
                    logger.debug(f"check_sonarr_episode_exists: Valid file found for S{season_number:02d}E{episode_in_season.get('episodeNumber')} in season pack check. Path: {ep_file_path}, Size: {ep_file_size}")
                    logger.info(f"Sonarr: Found at least one valid file in S{season_number:02d} (e.g., E{episode_in_season.get('episodeNumber')}) for '{found_series.get('title')}'. Guardrail will consider season PRESENT.")
                    return True # Found a valid file in the season

        logger.info(f"Sonarr: No valid files found for any episode in S{season_number:02d} for series '{found_series.get('title')}'. Guardrail will consider season ABSENT/MISSING.")
        logger.debug(f"check_sonarr_episode_exists: Returning {False} (no valid files in season pack)")
        return False

# ==============================================================================
# --- SONARR/RADARR - ADD NEW MEDIA FUNCTIONS ---
# ==============================================================================

def add_new_series_to_sonarr(tvdb_id: int, title: str, quality_profile_id: int, language_profile_id: int, root_folder_path: str, season_folder: bool = True, monitored: bool = True, search_for_missing_episodes: bool = False):
    """
    Adds a new series to Sonarr.
    Returns the new series object from Sonarr API if successful, else None.
    """
    logger.info(f"SONARR_CLIENT: Attempting to add new series: '{title}' (TVDB ID: {tvdb_id})")

    # Construct the payload as per Sonarr API v3 documentation
    # https://sonarr.tv/docs/api/#/Series/post_series
    payload = {
        "tvdbId": tvdb_id,
        "title": title, # Sonarr usually gets this from tvdbId, but good to provide
        "qualityProfileId": quality_profile_id,
        "languageProfileId": language_profile_id,
        "rootFolderPath": root_folder_path,
        "seasonFolder": season_folder,
        "monitored": monitored,
        "addOptions": {
            "searchForMissingEpisodes": False,
            # "monitor": "all" or "future" etc. can be specified if needed,
            # but 'monitored' at series level usually suffices.
        }
        # You might need to pass 'seasons' array if you want specific monitoring per season initially
        # For example: "seasons": [{ "seasonNumber": 1, "monitored": True }, ...]
        # If not provided, Sonarr typically monitors all seasons by default if series is monitored.
    }

    # The series endpoint for adding is just /api/v3/series
    response_data = _sonarr_api_request('POST', 'series', json_data=payload)

    if response_data and isinstance(response_data, dict) and response_data.get("id"):
        logger.info(f"SONARR_CLIENT: Series '{title}' added successfully. Sonarr ID: {response_data.get('id')}")
        return response_data # Return the full series object from Sonarr
    else:
        error_details = "Unknown error or invalid response from Sonarr."
        if isinstance(response_data, list) and response_data: # Sonarr can return a list of error messages
            try:
                error_details = ", ".join([err.get('errorMessage', str(err)) for err in response_data])
            except: # Fallback if parsing fails
                 error_details = str(response_data)
        elif isinstance(response_data, dict) and response_data.get('message'): # Single error message
            error_details = response_data.get('message')
        elif response_data is None: # _sonarr_api_request returned None due to connection/HTTP error
            error_details = "Failed to communicate with Sonarr API or API key issue."

        logger.error(f"SONARR_CLIENT: Failed to add series '{title}'. Response/Error: {error_details}")
        # You could raise an exception here or return a more specific error object
        return None


def add_new_movie_to_radarr(tmdb_id: int, title: str, quality_profile_id: int, root_folder_path: str, minimum_availability: str = "announced", monitored: bool = True, search_for_movie: bool = False):
    """
    Adds a new movie to Radarr.
    Returns the new movie object from Radarr API if successful, else None.
    """
    logger.info(f"RADARR_CLIENT: Attempting to add new movie: '{title}' (TMDB ID: {tmdb_id})")

    # Construct the payload as per Radarr API v3 documentation
    # https://radarr.video/docs/api/#/Movie/post_movie
    payload = {
        "tmdbId": tmdb_id,
        "title": title, # Radarr usually gets this from tmdbId
        "qualityProfileId": quality_profile_id,
        "rootFolderPath": root_folder_path,
        "minimumAvailability": minimum_availability, # e.g., "announced", "inCinemas", "released"
        "monitored": monitored,
        "addOptions": {
            "searchForMovie": False
        }
    }

    # The movie endpoint for adding is /api/v3/movie
    response_data = _radarr_api_request('POST', 'movie', json_data=payload)

    if response_data and isinstance(response_data, dict) and response_data.get("id"):
        logger.info(f"RADARR_CLIENT: Movie '{title}' added successfully. Radarr ID: {response_data.get('id')}")
        return response_data # Return the full movie object from Radarr
    else:
        error_details = "Unknown error or invalid response from Radarr."
        if isinstance(response_data, list) and response_data: # Radarr can return a list of error messages
            try:
                error_details = ", ".join([err.get('errorMessage', str(err)) for err in response_data])
            except:
                error_details = str(response_data)

        elif isinstance(response_data, dict) and response_data.get('message'):
            error_details = response_data.get('message')
        elif response_data is None:
             error_details = "Failed to communicate with Radarr API or API key issue."

        logger.error(f"RADARR_CLIENT: Failed to add movie '{title}'. Response/Error: {error_details}")
        return None

def get_arr_media_details(search_title: str, media_type_from_guessit: str, year_from_guessit: int = None):
    """
    Searches Sonarr/Radarr for a media item by title and returns enriched details including
    canonical title, alternative titles, and external IDs.
    """
    if not search_title or not media_type_from_guessit:
        logger.warn("get_arr_media_details: search_title or media_type_from_guessit is missing.")
        return None

    logger.info(f"get_arr_media_details: Searching for '{search_title}' (Type: {media_type_from_guessit}, Year: {year_from_guessit})")

    initial_search_results = []
    arr_item_id = None
    arr_item_details = None

    if media_type_from_guessit == 'episode': # Sonarr
        initial_search_results = search_sonarr_by_title(search_title)
        if initial_search_results:
            # Try to find an exact title match or a year match if Sonarr lookup provides series year
            best_match = None
            for item in initial_search_results:
                if item.get('title','').lower() == search_title.lower():
                    if year_from_guessit and item.get('year') and item.get('year') == year_from_guessit:
                        best_match = item # Perfect match with year
                        break
                    elif not year_from_guessit and not best_match : # If no year to match, first exact title match
                        best_match = item
            if not best_match and initial_search_results : best_match = initial_search_results[0] # Fallback to first result

            if best_match:
                arr_item_id = best_match.get('id') # Sonarr's internal ID if already added
                if not arr_item_id: # Not yet in Sonarr, use tvdbId for fetching details if possible from lookup
                    # Sonarr's lookup usually gives enough details directly without needing a second call by tvdbId
                    arr_item_details = best_match
                else: # Already in Sonarr, fetch full details by its Sonarr ID
                    arr_item_details = get_sonarr_series_by_id(arr_item_id)
            else:
                logger.info(f"get_arr_media_details: No suitable match found in Sonarr lookup for '{search_title}'.")
                return None
        else:
            logger.info(f"get_arr_media_details: Sonarr lookup returned no results for '{search_title}'.")
            return None

    elif media_type_from_guessit == 'movie': # Radarr
        initial_search_results = search_radarr_by_title(search_title)
        if initial_search_results:
            best_match = None
            # Radarr's lookup often returns multiple versions/qualities if movie is already added.
            # We prefer a match with the correct year.
            if year_from_guessit:
                for item in initial_search_results:
                    if item.get('year') == year_from_guessit and item.get('title','').lower() == search_title.lower():
                        best_match = item
                        break
            if not best_match: # If no year match or no year_from_guessit
                 for item in initial_search_results: # Try title match without year
                    if item.get('title','').lower() == search_title.lower():
                        best_match = item
                        break
            if not best_match and initial_search_results: best_match = initial_search_results[0] # Fallback

            if best_match:
                arr_item_id = best_match.get('id') # Radarr's internal ID if already added
                if not arr_item_id: # Not yet in Radarr
                    arr_item_details = best_match # Lookup result is usually detailed enough
                else: # Already in Radarr, fetch full details
                    arr_item_details = _radarr_api_request('GET', f'movie/{arr_item_id}')
            else:
                logger.info(f"get_arr_media_details: No suitable match found in Radarr lookup for '{search_title}'.")
                return None
        else:
            logger.info(f"get_arr_media_details: Radarr lookup returned no results for '{search_title}'.")
            return None
    else:
        logger.warn(f"get_arr_media_details: Unknown media_type_from_guessit '{media_type_from_guessit}'.")
        return None

    if not arr_item_details:
        logger.warn(f"get_arr_media_details: Could not retrieve full details for '{search_title}' from {media_type_from_guessit}.")
        return None

    # Extract information
    # Sonarr: title, alternateTitles (list of dicts with title), tvdbId, imdbId (sometimes)
    # Radarr: title, alternativeTitles (list of dicts with title), tmdbId, imdbId

    canonical_title = arr_item_details.get('title')
    alternate_titles_raw = []
    if media_type_from_guessit == 'episode': # Sonarr
        alternate_titles_raw = arr_item_details.get('alternateTitles', [])
    elif media_type_from_guessit == 'movie': # Radarr
        # Radarr V3 uses 'alternativeTitles', V4+ might use 'alternateTitles'. Check both.
        alternate_titles_raw = arr_item_details.get('alternativeTitles') or arr_item_details.get('alternateTitles', [])


    alternate_titles_list = [alt.get('title') for alt in alternate_titles_raw if alt.get('title')]

    # Remove duplicates and the canonical title from alternate titles if present
    unique_alternate_titles = list(set(alternate_titles_list))
    if canonical_title and canonical_title in unique_alternate_titles:
        unique_alternate_titles.remove(canonical_title)

    details = {
        'canonical_title': canonical_title,
        'alternate_titles': unique_alternate_titles,
        'tvdb_id': arr_item_details.get('tvdbId') if media_type_from_guessit == 'episode' else None,
        'tmdb_id': arr_item_details.get('tmdbId') if media_type_from_guessit == 'movie' else None,
        'imdb_id': arr_item_details.get('imdbId'), # Both Sonarr & Radarr might have imdbId
        'arr_item_id': arr_item_id, # Internal Sonarr/Radarr ID (None if not yet added)
        'arr_item_monitored': arr_item_details.get('monitored', False), # Monitored status
        'year': arr_item_details.get('year'), # Year from Arr, often more reliable
        'raw_arr_response': arr_item_details # For debugging or further use
    }

    logger.info(f"get_arr_media_details: Successfully fetched details for '{search_title}': TVDB ID: {details['tvdb_id']}, TMDB ID: {details['tmdb_id']}, IMDb ID: {details['imdb_id']}, Arr ID: {details['arr_item_id']}")
    return details


def add_series_by_title_to_sonarr(series_title: str, series_year: int = None):
    """
    Searches for a series by title (and optionally year) in Sonarr,
    then adds it if found and not already in Sonarr.
    Uses default root folder and quality profile from config.
    Returns the new series object from Sonarr API if successful, else raises ValueError.
    """
    logger.info(f"Attempting to search and add series: '{series_title}' (Year: {series_year}) to Sonarr.")

    candidates = search_sonarr_by_title(series_title)
    if not candidates:
        raise ValueError(f"Sonarr: No series found matching title '{series_title}'.")

    best_match = None
    for series in candidates:
        # Prefer an item not already added (no 'id' or id is 0)
        if not series.get('id') or series.get('id') == 0:
            # Title matching (case-insensitive, simple normalization)
            normalized_api_title = re.sub(r'[^\w\s]', '', series.get('title', '')).lower()
            normalized_search_title = re.sub(r'[^\w\s]', '', series_title).lower()

            if normalized_api_title == normalized_search_title:
                if series_year:
                    if series.get('year') == series_year:
                        best_match = series
                        break
                else: # No year provided, first title match is good enough for now
                    best_match = series
                    break

    if not best_match: # Fallback if no exact match on unadded item, try first result if any
        logger.warning(f"Sonarr: No exact unadded match for '{series_title}' (Year: {series_year}). Considering first lookup result if available.")
        # This part could be refined: what if the first result is already added?
        # For now, we prioritize unadded. If all are added or no good match, this will remain None.
        # Or, if we want to be more aggressive, take candidates[0] if it has a tvdbId.
        # However, add_new_series_to_sonarr expects an unadded item.
        # If best_match is still None here, it means no suitable *unadded* candidate was found.
        raise ValueError(f"Sonarr: No suitable *unadded* series found for '{series_title}' (Year: {series_year}) via lookup.")


    tvdb_id = best_match.get('tvdbId')
    if not tvdb_id:
        raise ValueError(f"Sonarr: Could not find TVDB ID for '{series.get('title', series_title)}' from search results.")

    # Get default Sonarr configurations
    default_root_folder = current_app.config.get('DEFAULT_SONARR_ROOT_FOLDER')
    default_quality_profile_id = current_app.config.get('DEFAULT_SONARR_PROFILE_ID')
    default_language_profile_id = current_app.config.get('DEFAULT_SONARR_LANGUAGE_PROFILE_ID', 1) # Sonarr specific

    if not default_root_folder or not default_quality_profile_id:
        missing_configs = []
        if not default_root_folder: missing_configs.append("DEFAULT_SONARR_ROOT_FOLDER")
        if not default_quality_profile_id: missing_configs.append("DEFAULT_SONARR_PROFILE_ID")
        raise ValueError(f"Sonarr: Missing default configuration: {', '.join(missing_configs)}.")

    logger.info(f"Sonarr: Found TVDB ID {tvdb_id} for '{series_title}'. Proceeding to add with defaults.")

    # Use the existing add_new_series_to_sonarr function
    added_series_details = add_new_series_to_sonarr(
        tvdb_id=tvdb_id,
        title=best_match.get('title'), # Use title from Sonarr's lookup result for consistency
        quality_profile_id=default_quality_profile_id,
        language_profile_id=default_language_profile_id,
        root_folder_path=default_root_folder
        # season_folder, monitored, search_for_missing_episodes use defaults from add_new_series_to_sonarr
    )

    if not added_series_details or not added_series_details.get('id'):
        # add_new_series_to_sonarr already logs errors, so just raise generic here
        raise ValueError(f"Sonarr: Failed to add series '{series_title}' using TVDB ID {tvdb_id}.")

    logger.info(f"Sonarr: Successfully added series '{added_series_details.get('title')}' with Sonarr ID {added_series_details.get('id')}.")
    return added_series_details


def add_movie_by_title_to_radarr(movie_title: str, movie_year: int = None):
    """
    Searches for a movie by title (and optionally year) in Radarr,
    then adds it if found and not already in Radarr.
    Uses default root folder and quality profile from config.
    Returns the new movie object from Radarr API if successful, else raises ValueError.
    """
    logger.info(f"Attempting to search and add movie: '{movie_title}' (Year: {movie_year}) to Radarr.")

    candidates = search_radarr_by_title(movie_title)
    if not candidates:
        raise ValueError(f"Radarr: No movies found matching title '{movie_title}'.")

    best_match = None
    for movie in candidates:
        if not movie.get('id') or movie.get('id') == 0: # Prefer unadded
            normalized_api_title = re.sub(r'[^\w\s]', '', movie.get('title', '')).lower()
            normalized_search_title = re.sub(r'[^\w\s]', '', movie_title).lower()

            if normalized_api_title == normalized_search_title:
                if movie_year:
                    if movie.get('year') == movie_year:
                        best_match = movie
                        break
                else:
                    best_match = movie
                    break

    if not best_match:
        raise ValueError(f"Radarr: No suitable *unadded* movie found for '{movie_title}' (Year: {movie_year}) via lookup.")

    tmdb_id = best_match.get('tmdbId')
    if not tmdb_id:
        raise ValueError(f"Radarr: Could not find TMDB ID for '{best_match.get('title', movie_title)}' from search results.")

    # Get default Radarr configurations
    default_root_folder = current_app.config.get('DEFAULT_RADARR_ROOT_FOLDER')
    default_quality_profile_id = current_app.config.get('DEFAULT_RADARR_PROFILE_ID')
    # Radarr also uses 'minimumAvailability', defaults in add_new_movie_to_radarr function

    if not default_root_folder or not default_quality_profile_id:
        missing_configs = []
        if not default_root_folder: missing_configs.append("DEFAULT_RADARR_ROOT_FOLDER")
        if not default_quality_profile_id: missing_configs.append("DEFAULT_RADARR_PROFILE_ID")
        raise ValueError(f"Radarr: Missing default configuration: {', '.join(missing_configs)}.")

    logger.info(f"Radarr: Found TMDB ID {tmdb_id} for '{movie_title}'. Proceeding to add with defaults.")

    added_movie_details = add_new_movie_to_radarr(
        tmdb_id=tmdb_id,
        title=best_match.get('title'), # Use title from Radarr's lookup result
        quality_profile_id=default_quality_profile_id,
        root_folder_path=default_root_folder
        # minimum_availability, monitored, search_for_movie use defaults from add_new_movie_to_radarr
    )

    if not added_movie_details or not added_movie_details.get('id'):
        raise ValueError(f"Radarr: Failed to add movie '{movie_title}' using TMDB ID {tmdb_id}.")

    logger.info(f"Radarr: Successfully added movie '{added_movie_details.get('title')}' with Radarr ID {added_movie_details.get('id')}.")
    return added_movie_details

def get_sonarr_episodes_by_series_id(series_id):
    """Récupère TOUS les épisodes d'une série depuis Sonarr, pas seulement ceux avec des fichiers."""
    if not series_id:
        return None
    try:
        # L'endpoint 'episode' retourne tous les épisodes d'une série
        return _sonarr_api_request("GET", "episode", params={'seriesId': series_id})
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la récupération des épisodes pour la série Sonarr ID {series_id}: {e}", exc_info=True)
        return None

# Dans app/utils/arr_client.py

def sonarr_delete_episode_files_bulk(episode_file_ids):
    """
    Supprime une liste de fichiers d'épisodes dans Sonarr en utilisant leurs episodeFileId.
    """
    if not episode_file_ids:
        return False
    try:
        # L'API Sonarr v3 attend un payload JSON avec les IDs
        payload = {"episodeFileIds": episode_file_ids}
        # L'endpoint pour la suppression en masse est 'episodefile/bulk' avec la méthode DELETE
        response = _sonarr_api_request("DELETE", "episodefile/bulk", json_data=payload)

        # L'API renvoie une liste vide en cas de succès
        if response is not None:
            current_app.logger.info(f"Sonarr a confirmé la suppression de {len(episode_file_ids)} fichier(s).")
            return True
        else:
            current_app.logger.error(f"La suppression en masse via Sonarr a échoué. Réponse invalide: {response}")
            return False
    except Exception as e:
        current_app.logger.error(f"Exception lors de la suppression en masse des épisodes Sonarr: {e}", exc_info=True)
        return False

def sonarr_update_episode_monitoring(episode_id, monitored_status):
    """Met à jour le statut de monitoring d'un seul épisode dans Sonarr."""
    try:
        episode_data = _sonarr_api_request("GET", f"episode/{episode_id}")
        if not episode_data:
            current_app.logger.error(f"Impossible de récupérer les détails de l_épisode ID {episode_id} de Sonarr.")
            return False

        episode_data['monitored'] = monitored_status

        # L'API attend une modification sur l'endpoint spécifique de l'épisode
        response = _sonarr_api_request("PUT", f"episode/{episode_id}", json_data=episode_data)

        if response and response.get('id'):
            return True
        return False
    except Exception as e:
        current_app.logger.error(f"Exception lors de la mise à jour du monitoring pour l_épisode {episode_id}: {e}", exc_info=True)
        return False

def sonarr_update_season_monitoring(series_id, season_number, monitored_status):
    """Met à jour le statut de monitoring pour une saison spécifique."""
    try:
        # On doit récupérer l'objet série complet
        series_data = get_sonarr_series_by_id(series_id)
        if not series_data:
            return False

        # On trouve la bonne saison et on modifie son statut
        season_found = False
        for season in series_data.get('seasons', []):
            if season.get('seasonNumber') == int(season_number):
                season['monitored'] = monitored_status
                season_found = True
                break

        if not season_found: return False # La saison n'existe pas dans Sonarr

        # On renvoie l'objet série complet modifié
        return update_sonarr_series(series_data)
    except Exception as e:
        current_app.logger.error(f"Exception lors de la mise à jour du monitoring pour la saison {season_number} de la série {series_id}: {e}", exc_info=True)
        return False
        
def get_sonarr_episode_file_ids_for_season(series_id, season_number):
    """
    Récupère une liste d'ID de fichiers d'épisodes pour une saison spécifique d'une série.
    """
    try:
        all_episode_files = get_sonarr_episode_files(series_id) or []
        file_ids_for_season = [
            file_info['id']
            for file_info in all_episode_files
            if file_info.get('seasonNumber') == int(season_number)
        ]
        return file_ids_for_season
    except (TypeError, ValueError) as e:
        current_app.logger.error(f"Erreur lors du filtrage des fichiers d'épisodes pour la saison {season_number} de la série {series_id}: {e}")
        return []

def sonarr_post_command(payload):
    """Posts a command to Sonarr."""
    return _sonarr_api_request('POST', 'command', json_data=payload)

def sonarr_trigger_series_rename(series_id, season_number=None):
    """
    Déclenche une commande de renommage dans Sonarr.
    Si 'season_number' est fourni, utilise 'RenameFiles' pour cette saison.
    Sinon, utilise 'RenameSeries' pour la série entière.
    """
    # Si on cible une saison spécifique, on doit trouver les IDs des fichiers
    if season_number is not None:
        current_app.logger.info(f"Ciblage du renommage pour la saison {season_number} de la série {series_id}.")

        all_episode_files = get_sonarr_episode_files(series_id)
        if all_episode_files is None:
            current_app.logger.error("Impossible de récupérer la liste des fichiers d'épisodes pour le renommage.")
            return False

        file_ids_to_rename = [
            ep_file['id'] for ep_file in all_episode_files
            if ep_file.get('seasonNumber') == season_number
        ]

        if not file_ids_to_rename:
            current_app.logger.warning(f"Aucun fichier trouvé pour la saison {season_number} à renommer.")
            return True

        payload = {
            'name': 'RenameFiles',
            'seriesId': series_id, # seriesId est requis par RenameFiles
            'files': file_ids_to_rename
        }
        current_app.logger.info(f"Envoi de la commande 'RenameFiles' pour {len(file_ids_to_rename)} fichier(s).")
        return sonarr_post_command(payload)
    else:
        # Si aucune saison n'est spécifiée, on renomme toute la série
        current_app.logger.info(f"Envoi de la commande 'RenameSeries' pour la série {series_id}.")
        payload = {
            'name': 'RenameSeries',
            'seriesIds': [series_id]
        }
        # Note: L'API peut aussi utiliser 'RenameFiles' avec tous les fichiers de la série,
        # mais 'RenameSeries' est plus direct.
        return sonarr_post_command(payload)

def radarr_post_command(payload):
    """Posts a command to Radarr."""
    return _radarr_api_request('POST', 'command', json_data=payload)

def find_in_arr_queue_by_hash(arr_type, torrent_hash):
    """
    Finds an item in the Sonarr or Radarr queue by its torrent hash.
    The 'downloadId' in the *Arr queue should correspond to the torrent hash.
    """
    logger.info(f"Searching {arr_type} queue for hash: {torrent_hash}")
    queue = None
    if arr_type == 'sonarr':
        queue_response = _sonarr_api_request('GET', 'queue')
        if queue_response and 'records' in queue_response:
            queue = queue_response['records']
    elif arr_type == 'radarr':
        queue_response = _radarr_api_request('GET', 'queue')
        if queue_response and 'records' in queue_response:
            queue = queue_response['records']
    else:
        logger.error(f"Unknown arr_type '{arr_type}' for queue search.")
        return None

    if queue is None:
        logger.error(f"Failed to fetch queue from {arr_type}.")
        return None

    for item in queue:
        # The downloadId in Sonarr/Radarr should be the uppercase torrent hash
        if item.get('downloadId', '').upper() == torrent_hash.upper():
            logger.info(f"Found item in {arr_type} queue with hash {torrent_hash}: {item.get('title')}")
            return item

    logger.info(f"No item found in {arr_type} queue with hash {torrent_hash}.")
    return None

def sonarr_trigger_import(download_id):
    """Triggers an import in Sonarr for a specific downloadId (torrent hash)."""
    payload = {'name': 'DownloadedEpisodesScan', 'downloadId': download_id, 'importMode': 'Move'}
    return sonarr_post_command(payload)

def radarr_trigger_import(download_id):
    """Triggers an import in Radarr for a specific downloadId (torrent hash)."""
    payload = {'name': 'DownloadedMoviesScan', 'downloadId': download_id, 'importMode': 'Move'}
    return radarr_post_command(payload)

def move_sonarr_series(series_id, new_root_folder_path):
    """
    Moves a Sonarr series to a new root folder by editing the series object.
    Returns True on success, False on failure.
    """
    logger.info(f"Sonarr: Initiating move for series ID {series_id} to '{new_root_folder_path}'.")
    try:
        series_id_int = int(series_id)
    except (ValueError, TypeError):
        logger.error(f"L'ID de la série '{series_id}' n'est pas un entier valide.")
        return False, f"L'ID de la série '{series_id}' est invalide."

    series_data = get_sonarr_series_by_id(series_id_int)
    if not series_data:
        logger.error(f"Sonarr: Impossible de récupérer la série {series_id_int} pour la déplacer.")
        return False, "Série non trouvée."

    series_data['rootFolderPath'] = new_root_folder_path
    # Mettre à jour le chemin de la série pour refléter le nouveau dossier racine
    series_folder = os.path.basename(series_data['path'])
    series_data['path'] = os.path.join(new_root_folder_path, series_folder)

    params = {'moveFiles': 'true'}
    response = _sonarr_api_request('PUT', f"series/{series_id_int}", params=params, json_data=series_data)

    if response and response.get('id'):
        logger.info(f"Sonarr: Déplacement pour la série ID {series_id_int} accepté. L'opération se poursuit en arrière-plan.")
        return True, None

    error_msg = "Échec de l'initiation du déplacement via l'édition de la série."
    if isinstance(response, list) and response:
        error_msg = response[0].get('errorMessage', str(response))
    logger.error(f"Sonarr: Échec du déplacement de la série {series_id_int}. Réponse: {response}")
    return False, error_msg

def move_radarr_movie(movie_id, new_root_folder_path):
    """
    Déplace un film Radarr en utilisant la commande 'MoveMovies'.
    Cette méthode retourne un ID de commande pour le suivi.
    Retourne (True, command_id) en cas de succès, (False, error_message) en cas d'échec.
    """
    logger.info(f"Radarr: Initiating 'MoveMovies' command for movie ID {movie_id} to '{new_root_folder_path}'.")
    try:
        movie_id_int = int(movie_id)
    except (ValueError, TypeError):
        error_msg = f"L'ID du film '{movie_id}' est invalide."
        logger.error(error_msg)
        return False, error_msg

    command_payload = {
        "name": "MoveMovies",
        "movieIds": [movie_id_int],
        "rootFolderPath": new_root_folder_path,
        "moveFiles": True # S'assurer que les fichiers sont bien déplacés
    }

    command_response = radarr_post_command(command_payload)

    if command_response and command_response.get('id'):
        command_id = command_response['id']
        logger.info(f"Radarr: Commande 'MoveMovies' envoyée avec succès. Command ID: {command_id}")
        return True, command_id
    else:
        error_msg = "Échec de l'envoi de la commande 'MoveMovies' à Radarr."
        logger.error(f"Radarr: {error_msg} Réponse: {command_response}")
        # Essayer de trouver un message d'erreur plus précis dans la réponse
        if isinstance(command_response, list) and command_response:
             error_details = command_response[0].get('errorMessage', str(command_response))
             error_msg = f"Radarr a retourné une erreur : {error_details}"
        return False, error_msg

def get_arr_command_status(arr_type, command_id):
    """
    Fetches the status of a specific command from Sonarr or Radarr.
    """
    logger.debug(f"Fetching command status for command ID {command_id} from {arr_type}.")
    if arr_type == 'sonarr':
        return _sonarr_api_request('GET', f'command/{command_id}')
    elif arr_type == 'radarr':
        return _radarr_api_request('GET', f'command/{command_id}')
    return None

def _format_bytes(size_bytes):
    """Converts bytes to a human-readable string (KB, MB, GB, TB)."""
    if size_bytes is None:
        return "N/A"
    if size_bytes == 0:
        return "0 B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size_bytes >= power and n < len(power_labels):
        size_bytes /= power
        n += 1
    return f"{size_bytes:.2f} {power_labels[n]}B"

def get_sonarr_root_folders():
    """Fetches all root folders from Sonarr and adds formatted free space."""
    logger.info("Sonarr: Fetching root folders.")
    folders = _sonarr_api_request('GET', 'rootfolder')
    if folders and isinstance(folders, list):
        for folder in folders:
            free_space = folder.get('freeSpace')
            folder['freeSpace_formatted'] = _format_bytes(free_space)
    return folders

def get_radarr_root_folders():
    """Fetches all root folders from Radarr and adds formatted free space."""
    logger.info("Radarr: Fetching root folders.")
    folders = _radarr_api_request('GET', 'rootfolder')
    if folders and isinstance(folders, list):
        for folder in folders:
            free_space = folder.get('freeSpace')
            folder['freeSpace_formatted'] = _format_bytes(free_space)
    return folders