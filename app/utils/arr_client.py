import requests
from flask import current_app

def _radarr_api_request(method, endpoint, params=None, json_data=None):
    """Helper function to make requests to the Radarr API."""
    config = current_app.config
    headers = {'X-Api-Key': config['RADARR_API_KEY']}
    url = f"{config['RADARR_URL'].rstrip('/')}/api/v3/{endpoint.lstrip('/')}"
    
    try:
        response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Radarr API request failed: {e}")
        return None

def get_radarr_tag_id(tag_label):
    """Finds a tag by its label in Radarr and returns its ID. Creates it if not found."""
    # 1. Get all existing tags
    all_tags = _radarr_api_request('GET', 'tag')
    if all_tags is None:
        return None # API request failed

    # 2. Check if the tag already exists
    for tag in all_tags:
        if tag.get('label', '').lower() == tag_label.lower():
            current_app.logger.info(f"Found existing tag '{tag_label}' with ID {tag['id']}.")
            return tag['id']

    # 3. If not found, create it
    current_app.logger.info(f"Tag '{tag_label}' not found in Radarr. Creating it...")
    try:
        new_tag = _radarr_api_request('POST', 'tag', json_data={'label': tag_label})
        if new_tag and 'id' in new_tag:
            current_app.logger.info(f"Successfully created tag '{tag_label}' with ID {new_tag['id']}.")
            return new_tag['id']
        else:
            current_app.logger.error(f"Failed to create tag '{tag_label}'. Response: {new_tag}")
            return None
    except Exception as e:
        current_app.logger.error(f"Exception while creating tag in Radarr: {e}")
        return None

def get_radarr_movie_by_guid(plex_guid):
    """Finds a movie in Radarr using a Plex GUID (e.g., 'imdb://tt1234567')."""
    if 'imdb' in plex_guid:
        id_key = 'imdbId'
        id_value = plex_guid.split('//')[-1]
    elif 'tmdb' in plex_guid:
        id_key = 'tmdbId'
        id_value = plex_guid.split('//')[-1]
    else:
        return None # Unsupported GUID type for Radarr lookup

    movies = _radarr_api_request('GET', 'movie')
    if movies:
        for movie in movies:
            if movie.get(id_key) == id_value:
                return movie
    return None

def update_radarr_movie(movie_data):
    """Updates a movie in Radarr using its full data object."""
    return _radarr_api_request('PUT', f"movie/{movie_data['id']}", json_data=movie_data)