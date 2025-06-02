# app/utils/mapping_manager.py
import json
import os
from flask import current_app # To get config for the JSON file path and logger

# Name of the JSON file, to be configured in Flask app
# Example: PENDING_TORRENTS_MAP_FILE = 'data/pending_torrents_map.json'

def _get_map_file_path():
    """Returns the absolute path to the mapping file."""
    map_file_name = current_app.config.get('PENDING_TORRENTS_MAP_FILE')
    if not map_file_name:
        current_app.logger.error("PENDING_TORRENTS_MAP_FILE not set in Flask config.")
        return None
    # Assuming map_file_name is relative to the app's instance folder or a predefined 'data' directory
    # For simplicity, let's assume it's stored in the instance folder if not absolute
    # A better approach might be to ensure the path is absolute or define a data directory
    # For now, let's create it in the main app directory if it's just a filename.
    # This should ideally be in an instance folder or a data folder.
    # If current_app.instance_path is available and desired:
    # return os.path.join(current_app.instance_path, map_file_name)

    # Let's place it in the root of the project for now for simplicity,
    # but this should be refined (e.g., in an 'instance' or 'data' folder).
    # We'll ensure the directory exists.
    map_file_path = os.path.join(current_app.root_path, '..', map_file_name) # Goes one level up from app dir to project root
    map_file_path = os.path.abspath(map_file_path)

    try:
        os.makedirs(os.path.dirname(map_file_path), exist_ok=True)
    except OSError as e:
        current_app.logger.error(f"Error creating directory for mapping file {os.path.dirname(map_file_path)}: {e}")
        return None
    return map_file_path

def _load_map():
    """Loads the entire mapping from the JSON file."""
    map_file_path = _get_map_file_path()
    if not map_file_path:
        return {} # Return empty dict if path is not configured

    if not os.path.exists(map_file_path):
        return {} # Return empty dict if file doesn't exist

    try:
        with open(map_file_path, 'r', encoding='utf-8') as f:
            # Handle empty file case
            content = f.read()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        current_app.logger.error(f"Error decoding JSON from {map_file_path}. Returning empty map.")
        # Optionally, create a backup of the corrupted file here
        return {}
    except Exception as e:
        current_app.logger.error(f"Error loading mapping file {map_file_path}: {e}")
        return {}

def _save_map(data_map):
    """Saves the entire mapping to the JSON file."""
    map_file_path = _get_map_file_path()
    if not map_file_path:
        current_app.logger.error("Cannot save map, file path not configured.")
        return False

    try:
        with open(map_file_path, 'w', encoding='utf-8') as f:
            json.dump(data_map, f, indent=4)
        return True
    except Exception as e:
        current_app.logger.error(f"Error saving mapping file {map_file_path}: {e}")
        return False

def add_pending_association(torrent_identifier, app_type, target_id, label, original_name):
    """
    Adds or updates a pending association.
    torrent_identifier: Typically the torrent hash or magnet link (must be unique).
    app_type: 'sonarr' or 'radarr'.
    target_id: The seriesId (Sonarr) or movieId (Radarr).
    label: The label used for rTorrent (e.g., 'sonarr', 'radarr').
    original_name: The original name of the torrent/release (for matching later).
    """
    if not all([torrent_identifier, app_type, target_id, label, original_name]):
        current_app.logger.warning("Missing data for add_pending_association.")
        return False

    current_map = _load_map()
    current_map[str(torrent_identifier)] = {
        "app_type": app_type,
        "target_id": target_id,
        "label": label,
        "original_name": original_name,
        "timestamp": current_app.config.get('APP_START_TIME', '') # Or use datetime.now().isoformat()
    }
    if _save_map(current_map):
        current_app.logger.info(f"Added/Updated pending association for '{torrent_identifier}' -> '{original_name}'.")
        return True
    else:
        current_app.logger.error(f"Failed to save map after adding association for '{torrent_identifier}'.")
        return False

def get_pending_association(release_name_from_staging):
    """
    Tries to find a pending association based on the release name found in staging.
    This requires matching release_name_from_staging (e.g., 'My.Show.S01E01.1080p')
    with the 'original_name' stored in the map.

    Returns the association dict if found, else None.
    The torrent_identifier (key in the map) is also added to the returned dict.
    """
    if not release_name_from_staging:
        return None

    current_map = _load_map()
    # Iterate through the map to find a match based on original_name.
    # This could be slow for very large maps, but for a few hundred entries it's fine.
    # For more robustness, consider cleaning/normalizing both names before comparison.

    # Simple direct match for now
    for torrent_id, assoc_data in current_map.items():
        if assoc_data.get("original_name") == release_name_from_staging:
            current_app.logger.info(f"Found pending association for release '{release_name_from_staging}' (ID: {torrent_id}).")
            # Add the torrent_id to the returned data for convenience
            assoc_data_with_id = assoc_data.copy()
            assoc_data_with_id['torrent_identifier'] = torrent_id
            return assoc_data_with_id

    current_app.logger.info(f"No pending association found for release name '{release_name_from_staging}'.")
    return None

def remove_pending_association(torrent_identifier):
    """Removes a pending association by its identifier (hash or magnet)."""
    current_map = _load_map()
    identifier_str = str(torrent_identifier) # Ensure key is string

    if identifier_str in current_map:
        del current_map[identifier_str]
        if _save_map(current_map):
            current_app.logger.info(f"Removed pending association for '{identifier_str}'.")
            return True
        else:
            current_app.logger.error(f"Failed to save map after removing association for '{identifier_str}'.")
            # Re-add to map in memory if save failed, to avoid inconsistent state?
            # For now, log and return False.
            return False
    else:
        current_app.logger.info(f"No association found to remove for identifier '{identifier_str}'.")
        return False # Or True, as the state is "not present"

def get_all_pending_associations():
    """Returns the entire map of pending associations."""
    return _load_map()
