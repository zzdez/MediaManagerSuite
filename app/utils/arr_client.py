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
        re.compile(r"^(?P<title>.+?)(?:[._\s](?P<year>(?:19|20)\d{2}))?(?:[._\s]+(?:DOC|SUBPACK|SEASON|VOL|DISC|DISQUE|PART))?[._\s]*S(?P<season>\d{1,2})(?![E\d])", re.IGNORECASE), # Refined pattern for Season-only releases
        re.compile(r"^(?P<title>.+?)[ ._]?Season[ ._]?(?P<season>\d{1,2})[ ._]?Episode[ ._]?(?P<episode>\d{1,3})", re.IGNORECASE),
        re.compile(r"^(?P<title>.+?)[ ._]?(?P<season>\d{1,2})x(?P<episode>\d{1,3})", re.IGNORECASE), # e.g. Show.Title.1x01
        re.compile(r"^(?P<title>.+?)(?:[._\s]+S(?P<season>\d{1,2}))(?:[._\s]+E(?P<episode>\d{1,3}))",re.IGNORECASE), # General SxxExx with flexible separators - MODIFIED
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

def get_radarr_queue(page=1, page_size=20, include_unknown_movie_items=False):
    """
    Fetches the Radarr queue.
    Can be paginated.
    """
    params = {
        'page': page,
        'pageSize': page_size,
        'includeUnknownMovieItems': str(include_unknown_movie_items).lower()
        # Radarr v3 queue endpoint also supports:
        # 'includeMovie': 'true' / 'false'
    }
    current_app.logger.debug(f"Radarr: Fetching queue with params: {params}")
    return _radarr_api_request('GET', 'queue', params=params)

def get_item_status_from_queue(arr_type: str, release_name: str, torrent_hash: str = None, unique_client_id: str = "MediaManagerSuite_SFTP_Scanner"):
    """
    Checks the status of a specific item in the Sonarr or Radarr queue.

    Args:
        arr_type (str): 'sonarr' or 'radarr'.
        release_name (str): The release name (title) of the item as it would appear in the queue.
                            This is often the folder name or main file name of the download.
        torrent_hash (str, optional): The torrent hash, which might be used as 'downloadId' in the queue.
        unique_client_id (str, optional): The unique client ID that might be part of the downloadId or a specific field.
                                         Defaults to "MediaManagerSuite_SFTP_Scanner".

    Returns:
        dict: A dictionary with "status" and "messages" (list of error/info messages).
              Possible statuses:
              - "completed": Item imported successfully.
              - "importing": Item is currently being imported.
              - "pending": Item is in queue, waiting for import (e.g., "AwaitingImport").
              - "failed": Import failed. Messages will contain details.
              - "not_found_in_queue": Item not found in the queue.
              - "api_error": Error communicating with the API.
              - "unknown": Status could not be determined.
    """
    logger.debug(f"get_item_status_from_queue: Called for {arr_type}, release_name='{release_name}', torrent_hash='{torrent_hash}', client_id='{unique_client_id}'")

    queue_data = None
    if arr_type == 'sonarr':
        # Fetch multiple pages if necessary, though usually recent items are on the first page.
        # For simplicity, starting with the first page (e.g., 20-50 items).
        # Adjust pageSize if a very active queue often pushes items off the first page quickly.
        raw_queue_response = get_sonarr_queue(page=1, page_size=50)
        if raw_queue_response and 'records' in raw_queue_response:
            queue_data = raw_queue_response['records']
    elif arr_type == 'radarr':
        raw_queue_response = get_radarr_queue(page=1, page_size=50)
        if raw_queue_response and 'records' in raw_queue_response: # Radarr's queue is not under 'records' key, it's a direct list.
            queue_data = raw_queue_response # Radarr's queue is a direct list of items
    else:
        logger.error(f"Invalid arr_type: {arr_type}")
        return {"status": "api_error", "messages": ["Invalid arr_type specified."]}

    if queue_data is None:
        logger.warning(f"{arr_type.capitalize()}: Queue data could not be fetched or was empty/invalid.")
        return {"status": "api_error", "messages": [f"Failed to fetch or parse queue from {arr_type.capitalize()}."]}

    logger.debug(f"{arr_type.capitalize()}: Checking {len(queue_data)} items from queue for release '{release_name}' or hash '{torrent_hash}'.")

    for item in queue_data:
        item_title = item.get('title', '').lower()
        item_download_id = item.get('downloadId', '').lower() # This is often the torrent hash or unique ID from download client
        item_status = item.get('status', '').lower()
        # Sonarr specific: item.get('trackedDownloadState') can be 'importPending', 'importFailed'
        # Radarr specific: item.get('trackedDownloadStatus') might be more detailed.

        status_messages = item.get('statusMessages', [])
        error_messages = []

        # Compile error messages from statusMessages array
        if status_messages:
            for msg_group in status_messages:
                if msg_group.get('messages'):
                    error_messages.extend(msg_group.get('messages'))

        # Normalize release_name for comparison (lowercase, replace dots/underscores with spaces)
        normalized_release_name = release_name.lower().replace('.', ' ').replace('_', ' ')
        normalized_item_title = item_title.replace('.', ' ').replace('_', ' ')

        # --- Matching Logic ---
        # Primary match: if torrent_hash is provided and it matches item_download_id
        # Secondary match: if release_name is "similar enough" to item_title.
        # Tertiary match: if unique_client_id is present in item_download_id (less reliable alone)

        matched = False
        if torrent_hash and item_download_id == torrent_hash.lower():
            logger.info(f"{arr_type.capitalize()}: Matched item by torrent_hash: '{torrent_hash}' -> Title: '{item.get('title')}'")
            matched = True
        elif normalized_release_name in normalized_item_title or normalized_item_title in normalized_release_name : # Check for substring inclusion
            logger.info(f"{arr_type.capitalize()}: Matched item by release_name (substring): '{release_name}' -> Title: '{item.get('title')}'")
            matched = True
        # Add more sophisticated matching if needed, e.g., Levenshtein distance or regex.

        if matched:
            logger.info(f"{arr_type.capitalize()}: Found matching item in queue: Title='{item.get('title', 'N/A')}', Status='{item_status}', DownloadID='{item_download_id}'")
            logger.debug(f"Full matched item details: {item}")

            # Interpreting status
            # Sonarr: status: "Completed", "Downloading", "Warning", "Failed", "Queued"
            #         trackedDownloadState: "downloading", "importPending", "importFailed"
            # Radarr: status: "queued", "downloading", "completed", "failed", "warning"

            if item_status == 'completed':
                return {"status": "completed", "messages": ["Item successfully imported."]}
            elif item_status in ['downloading', 'queued']: # Radarr 'queued', Sonarr 'Queued' or 'Downloading' (pre-import phase)
                 # Sonarr specific: 'AwaitingImport' status in 'statusMessages' or 'trackedDownloadState' == 'importPending'
                if arr_type == 'sonarr' and (item.get('trackedDownloadState', '').lower() == 'importpending' or any("awaitingimport" in msg.lower() for msg in error_messages)):
                    return {"status": "pending", "messages": error_messages or ["Item is awaiting import."]}
                return {"status": "pending", "messages": error_messages or ["Item is queued or still downloading."]}
            elif item_status == 'warning': # Often means manual import needed or other issues
                # Check for "No files found are eligible for import"
                no_files_eligible = any("no files found are eligible for import" in msg.lower() for msg in error_messages)
                if no_files_eligible:
                    logger.warning(f"{arr_type.capitalize()}: Item '{item.get('title')}' has 'no files eligible' error.")
                    return {"status": "failed", "messages": error_messages, "reason_code": "NO_FILES_ELIGIBLE"}
                logger.warning(f"{arr_type.capitalize()}: Item '{item.get('title')}' has status 'warning'. Messages: {error_messages}")
                return {"status": "failed", "messages": error_messages, "reason_code": "ARR_WARNING"} # Generic failure for warning
            elif item_status == 'failed':
                logger.warning(f"{arr_type.capitalize()}: Item '{item.get('title')}' has status 'failed'. Messages: {error_messages}")
                # Check for "No files found are eligible for import" specifically for failed status too
                no_files_eligible = any("no files found are eligible for import" in msg.lower() for msg in error_messages)
                if no_files_eligible:
                    return {"status": "failed", "messages": error_messages, "reason_code": "NO_FILES_ELIGIBLE"}
                return {"status": "failed", "messages": error_messages, "reason_code": "ARR_FAILED"}

            # Fallback for statuses not explicitly handled above but indicating an intermediate state
            if arr_type == 'sonarr' and item.get('trackedDownloadState', '').lower() == 'importpending':
                 return {"status": "pending", "messages": error_messages or ["Item is awaiting import."]}

            logger.info(f"Item '{item.get('title')}' found with status '{item_status}', but not explicitly handled. Treating as 'unknown'. Errors: {error_messages}")
            return {"status": "unknown", "messages": error_messages or [f"Unhandled status: {item_status}"]}

    logger.info(f"{arr_type.capitalize()}: Item matching '{release_name}' or hash '{torrent_hash}' not found in the first {len(queue_data)} queue items.")
    return {"status": "not_found_in_queue", "messages": ["Item not found in the current queue view."]}

def trigger_manual_import(arr_type: str, item_id: int, file_path_in_staging: str, release_name: str):
    """
    Triggers a Manual Import command in Sonarr or Radarr.

    Args:
        arr_type (str): 'sonarr' or 'radarr'.
        item_id (int): The seriesId (for Sonarr) or movieId (for Radarr).
        file_path_in_staging (str): Absolute path to the file/folder in the staging directory.
        release_name (str): The original release name, used for logging and potentially
                            extracting additional metadata if needed in the future.

    Returns:
        bool: True if the command was successfully triggered, False otherwise.
    """
    logger.info(f"{arr_type.capitalize()}: Attempting ManualImport for item ID {item_id}, path '{file_path_in_staging}', release '{release_name}'.")

    command_payload = {
        'name': 'ManualImport',
        'path': file_path_in_staging,
        'importMode': 'Move'  # Ensure files are moved
    }

    # Add specific parameters based on arr_type
    if arr_type == 'sonarr':
        command_payload['seriesId'] = item_id
        # Sonarr's ManualImport might also accept:
        # downloadId: str (optional)
        # quality: QualityModel (optional)
        # language: LanguageModel (optional)
        # releaseGroup: str (optional)
        # sceneName: str (optional)
        # TODO: Future enhancement: Extract quality/language from release_name if possible
        # and if the API benefits from it for better matching during manual import.
        # For now, relying on Sonarr to determine these from the files or series defaults.
    elif arr_type == 'radarr':
        command_payload['movieId'] = item_id
        # Radarr's ManualImport might also accept:
        # downloadId: str (optional)
        # quality: QualityModel (optional)
        # language: LanguageModel (optional)
        # releaseGroup: str (optional)
        # TODO: Similar to Sonarr, future enhancement for quality/language.
    else:
        logger.error(f"ManualImport: Invalid arr_type '{arr_type}' specified.")
        return False

    logger.debug(f"{arr_type.capitalize()}: ManualImport payload: {command_payload}")

    response = None
    if arr_type == 'sonarr':
        response = _sonarr_api_request('POST', 'command', json_data=command_payload)
    elif arr_type == 'radarr':
        response = _radarr_api_request('POST', 'command', json_data=command_payload)

    if response and (response.get('status') == 'started' or response.get('state') == 'started' or response.get('status') == 'queued' or response.get('id') is not None):
        logger.info(f"{arr_type.capitalize()}: Successfully triggered ManualImport for ID {item_id}, path '{file_path_in_staging}'. Response: {response}")
        return True
    else:
        logger.error(f"{arr_type.capitalize()}: Failed to trigger ManualImport for ID {item_id}, path '{file_path_in_staging}'. Response: {response}")
        return False

def trigger_rescan(arr_type: str, item_id: int):
    """
    Triggers a Rescan command for a specific series in Sonarr or movie in Radarr.

    Args:
        arr_type (str): 'sonarr' or 'radarr'.
        item_id (int): The seriesId (for Sonarr) or movieId (for Radarr).

    Returns:
        bool: True if the command was successfully triggered, False otherwise.
    """
    logger.info(f"{arr_type.capitalize()}: Attempting Rescan for item ID {item_id}.")

    command_payload = {}
    command_name = ""

    if arr_type == 'sonarr':
        command_name = 'RescanSeries'
        command_payload = {'name': command_name, 'seriesId': item_id}
    elif arr_type == 'radarr':
        command_name = 'RescanMovie'
        command_payload = {'name': command_name, 'movieId': item_id}
    else:
        logger.error(f"Rescan: Invalid arr_type '{arr_type}' specified.")
        return False

    logger.debug(f"{arr_type.capitalize()}: Rescan payload: {command_payload}")
    response = None
    if arr_type == 'sonarr':
        response = _sonarr_api_request('POST', 'command', json_data=command_payload)
    elif arr_type == 'radarr':
        response = _radarr_api_request('POST', 'command', json_data=command_payload)

    if response and (response.get('status') == 'started' or response.get('state') == 'started' or response.get('status') == 'queued' or response.get('id') is not None):
        logger.info(f"{arr_type.capitalize()}: Successfully triggered {command_name} for ID {item_id}. Response: {response}")
        return True
    else:
        logger.error(f"{arr_type.capitalize()}: Failed to trigger {command_name} for ID {item_id}. Response: {response}")
        return False

def get_expected_media_details(arr_type: str, item_id: int):
    """
    Fetches detailed information for a specific movie (Radarr) or series (Sonarr).

    Args:
        arr_type (str): 'sonarr' or 'radarr'.
        item_id (int): The seriesId (for Sonarr) or movieId (for Radarr).

    Returns:
        dict: A dictionary containing the media details from the API, or None if an error occurs.
              For Sonarr, this returns series details. Episode-specific details might require another call.
    """
    logger.info(f"{arr_type.capitalize()}: Fetching details for item ID {item_id}.")

    response = None
    if arr_type == 'sonarr':
        # This fetches series details. For episode naming patterns, further processing might be needed
        # or analysis of the series object structure (e.g., series.path, series.tvShowAlias).
        response = _sonarr_api_request('GET', f'series/{item_id}')
    elif arr_type == 'radarr':
        response = _radarr_api_request('GET', f'movie/{item_id}')
    else:
        logger.error(f"GetMediaDetails: Invalid arr_type '{arr_type}' specified.")
        return None

    if response:
        # The response itself is the dictionary of details.
        # Example details useful for renaming:
        # Radarr: response.get('title'), response.get('year'), response.get('path')
        # Sonarr: response.get('title'), response.get('year'), response.get('path'),
        #         response.get('seasons'), response.get('seriesType'),
        #         how Sonarr formats episode names (e.g. "Series Title - S01E01 - Episode Title.ext")
        #         This might be inferred from 'path' structure or series settings if available via API.
        logger.info(f"{arr_type.capitalize()}: Successfully fetched details for ID {item_id}.")
        logger.debug(f"Details for {item_id}: {str(response)[:200]}...") # Log a snippet
        return response
    else:
        logger.error(f"{arr_type.capitalize()}: Failed to fetch details for ID {item_id}.")
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

def get_sonarr_queue(page=1, page_size=20, include_unknown_series_items=False):
    """
    Fetches the Sonarr queue.
    Can be paginated.
    """
    params = {
        'page': page,
        'pageSize': page_size,
        'includeUnknownSeriesItems': str(include_unknown_series_items).lower()
        # Sonarr v3 queue endpoint also supports:
        # 'includeSeries': 'true' / 'false'
        # 'includeEpisode': 'true' / 'false'
    }
    current_app.logger.debug(f"Sonarr: Fetching queue with params: {params}")
    return _sonarr_api_request('GET', 'queue', params=params)

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