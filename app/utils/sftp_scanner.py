# app/utils/sftp_scanner.py
import os
import json
from pathlib import Path
import pysftp # Assuming pysftp, may need to install or change later
from flask import current_app
from . import arr_client
# Removed: from app import sftp_scan_lock

# Configuration constants (placeholders, will be replaced by current_app.config)
# SEEDBOX_SFTP_HOST = "sftp.example.com"
# SEEDBOX_SFTP_PORT = 22
# SEEDBOX_SFTP_USER = "user"
# SEEDBOX_SFTP_PASSWORD = "password"
# SEEDBOX_SCANNER_TARGET_SONARR_PATH = "/remote/sonarr" # Renamed
# SEEDBOX_SCANNER_TARGET_RADARR_PATH = "/remote/radarr" # Renamed
# LOCAL_STAGING_PATH = "/local/staging"
# PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT = "processed_sftp_items.json"

# FOLDERS_TO_SCAN_CONFIG = {
# "sonarr_finished": {
# "sftp_path_config_key": "SEEDBOX_SCANNER_TARGET_SONARR_PATH", # Renamed
# "arr_type": "sonarr"
#     },
# "radarr_finished": {
# "sftp_path_config_key": "SEEDBOX_SCANNER_TARGET_RADARR_PATH", # Renamed
# "arr_type": "radarr"
#     }
# }

def _load_processed_items(log_file_path):
    """Loads the set of processed item paths from the log file."""
    try:
        with open(log_file_path, 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()
    except json.JSONDecodeError:
        current_app.logger.error(f"Error decoding JSON from {log_file_path}. Starting with an empty set of processed items.")
        return set()

def _save_processed_items(log_file_path, processed_items):
    """Saves the set of processed item paths to the log file."""
    try:
        with open(log_file_path, 'w') as f:
            json.dump(list(processed_items), f, indent=4)
    except IOError as e:
        current_app.logger.error(f"Error saving processed items to {log_file_path}: {e}")

def _connect_sftp():
    """Establishes an SFTP connection using settings from current_app.config."""
    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None # Disable host key checking, consider security implications
    sftp_host = current_app.config['SEEDBOX_SFTP_HOST']
    sftp_port = current_app.config['SEEDBOX_SFTP_PORT']
    sftp_user = current_app.config['SEEDBOX_SFTP_USER']
    sftp_password = current_app.config['SEEDBOX_SFTP_PASSWORD']

    try:
        sftp = pysftp.Connection(
            host=sftp_host,
            username=sftp_user,
            password=sftp_password,
            port=sftp_port,
            cnopts=cnopts
        )
        current_app.logger.info(f"Successfully connected to SFTP server: {sftp_host}")
        return sftp
    except Exception as e:
        current_app.logger.error(f"SFTP connection failed for {sftp_user}@{sftp_host}:{sftp_port} - {e}")
        return None

def _list_remote_files(sftp, remote_path):
    """Lists files and directories in a remote path, excluding '.' and '..'."""
    items = []
    try:
        if sftp.exists(remote_path) and sftp.isdir(remote_path):
            current_app.logger.info(f"Scanning remote path: {remote_path}")
            for item_attr in sftp.listdir_attr(remote_path):
                if item_attr.filename not in ['.', '..']:
                    items.append(item_attr) # item_attr contains filename, st_mtime, st_size, etc.
        else:
            current_app.logger.warning(f"Remote path not found or not a directory: {remote_path}")
    except Exception as e:
        current_app.logger.error(f"Error listing files in {remote_path}: {e}")
    return items

def _download_item(sftp, remote_item_path, local_staging_path, item_name):
    """
    Downloads an item (file or directory) from SFTP server to local staging.
    Uses a robust manual recursive download for directories to avoid pysftp bugs.
    Returns True if download was successful, False otherwise.
    """
    local_item_path = Path(local_staging_path) / item_name

    try:
        # La logique pour les fichiers uniques est correcte et reste inchangée
        if sftp.isfile(remote_item_path):
            current_app.logger.info(f"Downloading file: {remote_item_path} to {local_item_path}")
            sftp.get(remote_item_path, str(local_item_path))
            current_app.logger.info(f"Successfully downloaded file: {item_name}")
            return True

        # === NOUVELLE LOGIQUE DE COPIE DE DOSSIER VIA WALKTREE CORRECTEMENT UTILISÉ ===
        elif sftp.isdir(remote_item_path):
            current_app.logger.info(f"Starting robust directory download for: {remote_item_path}")

            # On s'assure que le dossier de destination racine existe
            os.makedirs(local_item_path, exist_ok=True)

            # --- Définition des fonctions de rappel (callbacks) ---
            def file_callback(remotefile):
                # On calcule le chemin relatif pour préserver la structure
                relative_path = os.path.relpath(remotefile, start=remote_item_path).replace('\\', '/')
                local_file = local_item_path / Path(relative_path)
                
                # On s'assure que le dossier parent local existe
                os.makedirs(local_file.parent, exist_ok=True)

                current_app.logger.debug(f"Copying remote file '{remotefile}' to '{local_file}'")
                sftp.get(remotefile, str(local_file), preserve_mtime=True)

            def dir_callback(remotedir):
                # Optionnel : on peut créer les dossiers ici aussi
                relative_path = os.path.relpath(remotedir, start=remote_item_path).replace('\\', '/')
                if relative_path != '.':
                    local_dir = local_item_path / Path(relative_path)
                    os.makedirs(local_dir, exist_ok=True)

            def unknown_callback(remote_unknown):
                current_app.logger.warning(f"Skipping unknown item type during walktree: {remote_unknown}")
            # --- Fin de la définition des callbacks ---

            # On appelle walktree avec la bonne syntaxe
            sftp.walktree(remote_item_path, file_callback, dir_callback, unknown_callback)
            
            current_app.logger.info(f"Successfully downloaded directory '{item_name}' using walktree method.")
            return True

        else:
            current_app.logger.warning(f"Item {remote_item_path} is not a file or directory. Skipping.")
            return False
            
    except Exception as e:
        current_app.logger.error(f"FATAL error during download of {remote_item_path}: {e}", exc_info=True)
        # Nettoyage en cas d'erreur
        if local_item_path.exists() and local_item_path.is_dir():
            current_app.logger.warning(f"Attempting to cleanup partially downloaded item: {local_item_path}")
            try:
                import shutil
                shutil.rmtree(local_item_path)
                current_app.logger.info(f"Cleanup successful for {local_item_path}")
            except Exception as cleanup_e:
                current_app.logger.error(f"Error during cleanup of {local_item_path}: {cleanup_e}")
        return False

def _notify_arr_instance(arr_type, downloaded_item_name, local_staging_dir):
    """Notifies Sonarr or Radarr about the newly downloaded item."""
    # This function will call the new methods in arr_client
    # from . import arr_client # Ensure this is imported at the top level or passed in # This line is already handled by the import at the top of the file

    # The path passed to Sonarr/Radarr should be the path of the item *within* the staging directory.
    # Sonarr/Radarr will then move it from there.
    item_path_in_staging = Path(local_staging_dir) / downloaded_item_name

    current_app.logger.info(f"Notifying {arr_type} for item: {item_path_in_staging}")
    success = False
    if arr_type == "sonarr":
        success = arr_client.trigger_sonarr_scan(str(item_path_in_staging))
    elif arr_type == "radarr":
        success = arr_client.trigger_radarr_scan(str(item_path_in_staging))

    # Placeholder until arr_client is updated - REMOVED
    # current_app.logger.warning(f"ARR notification for {arr_type} item {item_path_in_staging} is currently a placeholder.")
    # success = True # Assume success for now - REMOVED

    if success:
        current_app.logger.info(f"Successfully notified {arr_type} for item: {downloaded_item_name}")
    else:
        current_app.logger.error(f"Failed to notify {arr_type} for item: {downloaded_item_name}")
    return success

import logging # Ajout de l'import logging

def scan_sftp_and_process_items():
    """Main function for the SFTP scanning task."""
    logger = logging.getLogger(__name__) # Utiliser le logger standard au lieu de current_app.logger au début
    config = current_app.config
    required_vars = [
        'LOCAL_STAGING_PATH', 'SEEDBOX_SFTP_HOST', 'SEEDBOX_SFTP_USER',
        'SEEDBOX_SFTP_PASSWORD', 'LOCAL_PROCESSED_LOG_PATH',
        'SEEDBOX_SCANNER_TARGET_SONARR_PATH', 'SEEDBOX_SCANNER_TARGET_RADARR_PATH'
    ]

    missing_vars = [var for var in required_vars if not config.get(var)]
    if missing_vars:
        logger.error(f"Scan SFTP annulé. Variables manquantes dans .env: {', '.join(missing_vars)}")
        # Pas besoin de libérer le verrou ici car on ne l'a pas encore acquis
        return

    if not current_app.sftp_scan_lock.acquire(blocking=False): # Use current_app.sftp_scan_lock
        current_app.logger.info("SFTP Scan deferred: Another scan is already in progress (lock not acquired).") # current_app.logger est ok ici
        return

    # À partir d'ici, on peut utiliser current_app.logger car on est dans le contexte de l'app et le verrou est acquis
    try:
        current_app.logger.info("SFTP Scanner Task: Lock acquired, starting scan and process cycle.")

        sftp_config = current_app.config # Peut être remplacé par config déjà défini
        staging_dir = Path(config['LOCAL_STAGING_PATH']) # Utiliser config
        log_file = config['LOCAL_PROCESSED_LOG_PATH'] # Utiliser config

        if not staging_dir.exists():
            try:
                staging_dir.mkdir(parents=True, exist_ok=True)
                current_app.logger.info(f"Created staging directory: {staging_dir}")
            except OSError as e:
                current_app.logger.error(f"Could not create staging directory {staging_dir}: {e}. Aborting SFTP scan.")
                return

        processed_items = _load_processed_items(log_file)

        sftp = _connect_sftp()
        if not sftp:
            current_app.logger.error("SFTP Scanner Task: Could not connect to SFTP server. Aborting.")
            return

        # Define folders to scan using MMS config directly
        folders_to_scan = {
            "sonarr": sftp_config.get('SEEDBOX_SCANNER_TARGET_SONARR_PATH'),
            "radarr": sftp_config.get('SEEDBOX_SCANNER_TARGET_RADARR_PATH'),
        }

        new_items_processed_this_run = False

        for arr_type, remote_base_path in folders_to_scan.items():
            if not remote_base_path:
                current_app.logger.warning(f"SFTP Scanner Task: Remote path for {arr_type} is not configured. Skipping.")
                continue

            current_app.logger.info(f"SFTP Scanner Task: Scanning {arr_type} remote path: {remote_base_path}")
            remote_items = _list_remote_files(sftp, remote_base_path)

            for item_attr in remote_items:
                item_name = item_attr.filename
                remote_item_full_path = f"{remote_base_path.rstrip('/')}/{item_name}"

                if remote_item_full_path in processed_items:
                    continue

                current_app.logger.info(f"SFTP Scanner Task: Found new item '{item_name}' in {remote_base_path} for {arr_type}.")

                guardrail_enabled = current_app.config.get('SFTP_SCANNER_GUARDFRAIL_ENABLED', True)
                media_exists_in_arr = False
                parsed_media = None

                if guardrail_enabled:
                    current_app.logger.info(f"SFTP Scanner Task: Guardrail enabled. Parsing '{item_name}'.")
                    current_app.logger.info(f"SFTP Scanner Task: PRE-CALL arr_client.parse_media_name for item '{item_name}'")
                    parsed_media = arr_client.parse_media_name(item_name)
                    current_app.logger.info(f"SFTP Scanner Task: POST-CALL arr_client.parse_media_name. Result type: {parsed_media.get('type')}, Title: {parsed_media.get('title')}")
                    current_app.logger.info(f"SFTP Scanner Task: Parsed '{item_name}' as: {parsed_media}")

                    if parsed_media['type'] == 'tv' and parsed_media['title'] and parsed_media['season'] is not None: # Condition changed here
                        episode_log_str = f"E{parsed_media.get('episode'):02d}" if parsed_media.get('episode') is not None else "(Season Check)"
                        current_app.logger.info(f"SFTP Scanner Task: Checking Sonarr for {parsed_media['title']} S{parsed_media['season']:02d}{episode_log_str}.")
                        try:
                            current_app.logger.info(f"SFTP Scanner Task: PRE-CALL arr_client.check_sonarr_episode_exists for {parsed_media.get('title')} S{parsed_media['season']:02d}{episode_log_str}") # Log updated
                            media_exists_in_arr = arr_client.check_sonarr_episode_exists(
                                parsed_media['title'],
                                parsed_media['season'],
                                parsed_media.get('episode') # Use .get() for episode
                            )
                            current_app.logger.info(f"SFTP Scanner Task: POST-CALL arr_client.check_sonarr_episode_exists for {parsed_media.get('title')} S{parsed_media['season']:02d}{episode_log_str}. Result: {media_exists_in_arr}") # Log updated
                        except Exception as e:
                            current_app.logger.error(f"SFTP Scanner Task: Error checking Sonarr for '{item_name}': {e}. Assuming media does not exist locally.")
                            media_exists_in_arr = False
                    elif parsed_media['type'] == 'movie' and parsed_media['title']:
                        current_app.logger.info(f"SFTP Scanner Task: Checking Radarr for {parsed_media['title']} ({parsed_media.get('year', 'N/A')}).")
                        try:
                            current_app.logger.info(f"SFTP Scanner Task: PRE-CALL arr_client.check_radarr_movie_exists for {parsed_media.get('title')}")
                            media_exists_in_arr = arr_client.check_radarr_movie_exists(
                                parsed_media['title'],
                                parsed_media.get('year')
                            )
                            current_app.logger.info(f"SFTP Scanner Task: POST-CALL arr_client.check_radarr_movie_exists. Result: {media_exists_in_arr}")
                        except Exception as e:
                            current_app.logger.error(f"SFTP Scanner Task: Error checking Radarr for '{item_name}': {e}. Assuming media does not exist locally.")
                            media_exists_in_arr = False
                    else:
                        current_app.logger.info(f"SFTP Scanner Task: Could not reliably parse '{item_name}' for {arr_type} type or type unknown. Proceeding with download process as fallback.")
                else:
                    current_app.logger.info("SFTP Scanner Task: Guardrail disabled. Proceeding with download.")

                if guardrail_enabled and media_exists_in_arr:
                    log_arr_type = "Sonarr" if parsed_media and parsed_media['type'] == 'tv' else "Radarr" if parsed_media and parsed_media['type'] == 'movie' else arr_type.capitalize()
                    current_app.logger.info(f"SFTP Scanner Task: Guardrail - Item '{item_name}' (path: {remote_item_full_path}) found in {log_arr_type} library. Skipping download and marking as processed.")
                    processed_items.add(remote_item_full_path)
                    new_items_processed_this_run = True
                    continue
                else:
                    if guardrail_enabled:
                        log_arr_type_else = "Sonarr" if parsed_media and parsed_media['type'] == 'tv' else "Radarr" if parsed_media and parsed_media['type'] == 'movie' else arr_type.capitalize()
                        if parsed_media and parsed_media['type'] != 'unknown':
                            current_app.logger.info(f"SFTP Scanner Task: Guardrail - Item '{item_name}' not found in {log_arr_type_else} library. Proceeding with download.")
                        elif not parsed_media or parsed_media['type'] == 'unknown':
                             current_app.logger.info(f"SFTP Scanner Task: Guardrail - Parsing insufficient for '{item_name}'. Proceeding with download.")

                if _download_item(sftp, remote_item_full_path, staging_dir, item_name):
                    if _notify_arr_instance(arr_type, item_name, staging_dir):
                        processed_items.add(remote_item_full_path)
                        new_items_processed_this_run = True
                        current_app.logger.info(f"SFTP Scanner Task: Successfully processed and logged '{item_name}'.")
                    else:
                        current_app.logger.error(f"SFTP Scanner Task: Failed to notify {arr_type} for '{item_name}'. Item will be re-processed next cycle.")
                else:
                    current_app.logger.error(f"SFTP Scanner Task: Failed to download '{item_name}'. It will be retried next cycle.")

        if sftp:
            sftp.close()
            current_app.logger.info("SFTP connection closed.")

        if new_items_processed_this_run:
            _save_processed_items(log_file, processed_items)
            current_app.logger.info("SFTP Scanner Task: Scan and process cycle finished (before lock release).")
    finally:
        current_app.sftp_scan_lock.release() # Use current_app.sftp_scan_lock
        current_app.logger.info("SFTP Scanner Task: Lock released after scan cycle.")

if __name__ == '__main__':
    # This section is for local testing if you run this script directly.
    # It requires a mock Flask app context or similar setup for current_app.
    print("This script is intended to be run within the Flask application context.")
    # Example of how you might mock current_app for standalone testing (simplified):
    # class MockConfig(dict):
    #     pass
    # class MockLogger:
    #     def info(self, msg): print(f"INFO: {msg}")
    #     def error(self, msg): print(f"ERROR: {msg}")
    #     def warning(self, msg): print(f"WARNING: {msg}")
    #     def debug(self, msg): print(f"DEBUG: {msg}")
    # class MockApp:
    #     def __init__(self):
    #         self.config = MockConfig({
    #             'SEEDBOX_SFTP_HOST': 'localhost', # Replace with your test SFTP server
    #             'SEEDBOX_SFTP_PORT': 2222,        # Replace with your test SFTP server port
    #             'SEEDBOX_SFTP_USER': 'testuser',  # Replace with your test SFTP user
    #             'SEEDBOX_SFTP_PASSWORD': 'testpassword', # Replace
    #             'SEEDBOX_SCANNER_TARGET_SONARR_PATH': '/upload/sonarr_completed', # Test path
    #             'SEEDBOX_SCANNER_TARGET_RADARR_PATH': '/upload/radarr_completed', # Test path
    #             'LOCAL_STAGING_PATH': './staging_test', # Local test staging dir
    #             'LOCAL_PROCESSED_LOG_PATH': './processed_sftp_test.json',
    #             # SONARR_URL, SONARR_API_KEY, RADARR_URL, RADARR_API_KEY for _notify_arr_instance if testing that part
    #         })
    #         self.logger = MockLogger()
    #
    # current_app = MockApp()
    # # Ensure staging_test directory exists
    # if not os.path.exists(current_app.config['LOCAL_STAGING_PATH']):
    #    os.makedirs(current_app.config['LOCAL_STAGING_PATH'])
    # scan_sftp_and_process_items()
