import requests
from flask import current_app

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
    if response and (response.get('status') == 'started' or response.get('state') == 'started' or response.get('status') == 'success'):
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
    if response and (response.get('status') == 'started' or response.get('state') == 'started' or response.get('status') == 'success'): # Sonarr API can be inconsistent here
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