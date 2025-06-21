# app/utils/sftp_scanner.py
import os
import json
from pathlib import Path
import pysftp # Assuming pysftp, may need to install or change later
import time
from flask import current_app
from . import arr_client, mapping_manager # Added mapping_manager
# Removed: from app import sftp_scan_lock

# Configuration constants (placeholders, will be replaced by current_app.config)
# SEEDBOX_SFTP_HOST = "sftp.example.com"
# SEEDBOX_SFTP_PORT = 22
# SEEDBOX_SFTP_USER = "user"
# SEEDBOX_SFTP_PASSWORD = "password"
# SEEDBOX_SONARR_FINISHED_PATH = "/remote/sonarr"
# SEEDBOX_RADARR_FINISHED_PATH = "/remote/radarr"
# STAGING_DIR = "/local/staging"
# PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT = "processed_sftp_items.json"

# FOLDERS_TO_SCAN_CONFIG = {
# "sonarr_finished": {
# "sftp_path_config_key": "SEEDBOX_SONARR_FINISHED_PATH",
# "arr_type": "sonarr"
#     },
# "radarr_finished": {
# "sftp_path_config_key": "SEEDBOX_RADARR_FINISHED_PATH",
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
    Returns True if download was successful, False otherwise.
    """
    local_item_path = Path(local_staging_path) / item_name
    try:
        if sftp.isfile(remote_item_path):
            current_app.logger.info(f"Downloading file: {remote_item_path} to {local_item_path}")
            sftp.get(remote_item_path, str(local_item_path))
            current_app.logger.info(f"Successfully downloaded file: {item_name}")
            return True
        elif sftp.isdir(remote_item_path):
            current_app.logger.info(f"Attempting to download directory: {remote_item_path} to {local_item_path}")
            try:
                # Ensure the local target directory exists
                os.makedirs(local_item_path, exist_ok=True)
                current_app.logger.info(f"Ensured local directory exists for item '{item_name}': {local_item_path}")

                original_cwd = sftp.pwd

                # Calculate remote parent path and ensure it uses forward slashes
                remote_item_path_obj = Path(remote_item_path) # Assuming remote_item_path is initially a string with server's separators (usually /)
                remote_parent_path_obj = remote_item_path_obj.parent

                # Convert to string and ensure forward slashes for SFTP server
                # The remote_item_path string (e.g. '/downloads/Termines/sonarr_downloads/item') should already be using forward slashes
                # if it comes directly from sftp.listdir_attr or similar. Path().parent should preserve this.
                # The key is that the SFTP server expects forward slashes.
                # Let's ensure the path given to sftp.cwd is in posix format.
                remote_parent_dir_for_sftp = remote_parent_path_obj.as_posix()

                item_basename = remote_item_path_obj.name # Get name from Path object

                current_app.logger.info(f"Attempting to download directory '{item_basename}'. Remote original CWD: {original_cwd}. Target remote parent for SFTP: '{remote_parent_dir_for_sftp}'.")

                sftp.cwd(remote_parent_dir_for_sftp) # Use the posix-style path
                current_app.logger.info(f"Changed remote CWD to: {sftp.pwd}. Downloading item (basename): '{item_basename}'")

                # Perform the recursive get using the item's basename relative to the new CWD
                sftp.get_r(item_basename, str(local_item_path), preserve_mtime=True)

                if original_cwd: # Restore original CWD
                    sftp.cwd(original_cwd)
                current_app.logger.info(f"Restored remote CWD to: {sftp.pwd if original_cwd else 'not changed'}")

                current_app.logger.info(f"Successfully downloaded directory '{item_name}' from '{remote_item_path}' to '{local_item_path}' using CWD strategy.")
                return True
            except Exception as e_dir_download:
                current_app.logger.error(f"Error during directory download for '{item_name}' from '{remote_item_path}' to '{local_item_path}': {e_dir_download}")
                # Attempt to clean up partially created local directory if download failed
                if local_item_path.exists(): # Check if directory was created by makedirs or partially by get_r
                    current_app.logger.warning(f"Attempting to cleanup partially downloaded directory: {local_item_path}")
                    try:
                        import shutil
                        shutil.rmtree(local_item_path)
                        current_app.logger.info(f"Successfully cleaned up directory: {local_item_path}")
                    except Exception as cleanup_e:
                        current_app.logger.error(f"Error cleaning up directory {local_item_path}: {cleanup_e}")
                else:
                    current_app.logger.info(f"Local item path {local_item_path} does not exist, no cleanup needed for this path.")
                return False
        else:
            current_app.logger.warning(f"Item {remote_item_path} is not a file or directory. Skipping.")
            return False
    except Exception as e:
        current_app.logger.error(f"Error downloading {remote_item_path} to {local_item_path}: {e}")
        # Clean up partially downloaded item if it exists
        if local_item_path.exists():
            try:
                if local_item_path.is_file():
                    local_item_path.unlink()
                elif local_item_path.is_dir():
                    # shutil.rmtree(local_item_path) # Requires import shutil - This is now handled in the directory download specific exception block
                    # For now, just log, or implement recursive delete if necessary for atomicity
                    current_app.logger.warning(f"Partial download cleanup for directory {local_item_path} might be needed (this path should ideally not be hit if dir download fails).")
            except Exception as cleanup_e:
                current_app.logger.error(f"Error cleaning up {local_item_path}: {cleanup_e}")
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

def scan_sftp_and_process_items():
    """Main function for the SFTP scanning task."""
    if not current_app.sftp_scan_lock.acquire(blocking=False): # Use current_app.sftp_scan_lock
        current_app.logger.info("SFTP Scan deferred: Another scan is already in progress (lock not acquired).")
        return
    try:
        current_app.logger.info("SFTP Scanner Task: Lock acquired, starting scan and process cycle.")

        sftp_config = current_app.config
        staging_dir = Path(sftp_config['STAGING_DIR'])
        log_file = sftp_config['PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT']

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
            "sonarr": sftp_config.get('SEEDBOX_SONARR_FINISHED_PATH'),
            "radarr": sftp_config.get('SEEDBOX_RADARR_FINISHED_PATH'),
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
                    notification_successful = _notify_arr_instance(arr_type, item_name, staging_dir)

                    if notification_successful:
                        current_app.logger.info(f"SFTP Scanner Task: Notification sent to {arr_type} for '{item_name}'. Beginning import monitoring if enabled.")

                        # --- Import Monitoring and Intervention Logic ---
                        config = current_app.config
                        monitoring_enabled = config.get('MMS_IMPORT_MONITORING_ENABLED', True)
                        monitoring_duration_minutes = config.get('MMS_IMPORT_MONITORING_DURATION_MINUTES', 5)
                        monitoring_interval_seconds = config.get('MMS_IMPORT_MONITORING_INTERVAL_SECONDS', 30)
                        manual_import_enabled = config.get('MMS_MANUAL_IMPORT_ATTEMPT_ENABLED', True)
                        set_unmonitored_enabled = config.get('MMS_SET_UNMONITORED_AFTER_IMPORT', True)

                        torrent_hash_map_entry, media_map_info = mapping_manager.find_torrent_by_release_name(item_name)

                        # --- Helper function for post-import verification and unmonitoring ---
                        def _verify_file_and_set_unmonitored(app_type_to_check, item_id_to_check, release_name_for_log, thash_for_map):
                            current_app.logger.info(f"POST_IMPORT_CHECK: Verifying file for {app_type_to_check} ID {item_id_to_check} ('{release_name_for_log}').")
                            media_details_api = arr_client.get_expected_media_details(app_type_to_check, item_id_to_check)
                            file_is_present = False

                            if media_details_api:
                                if app_type_to_check == 'radarr':
                                    if media_details_api.get('hasFile', False) and media_details_api.get('movieFile', {}).get('sizeOnDisk', 0) > 0:
                                        file_is_present = True
                                elif app_type_to_check == 'sonarr':
                                    # Check based on series statistics or specific episode files if logic is enhanced later
                                    stats = media_details_api.get('statistics')
                                    if stats and stats.get('episodeFileCount', 0) > 0 and stats.get('percentOfEpisodes', 0) > 0 : # Ensure some episodes are present
                                        # A more robust check would involve parsing release_name_for_log for season/episode
                                        # and checking those specific episodes. For now, episodeFileCount > 0 is a basic check.
                                        current_app.logger.debug(f"Sonarr series {item_id_to_check} stats: {stats}")
                                        file_is_present = True
                                        # If percentOfEpisodes is 100, it's even better.
                                        # If it's a season pack, this check might not be enough to confirm *this specific pack* was imported.

                            if file_is_present:
                                current_app.logger.info(f"POST_IMPORT_CHECK: File CONFIRMED present for {app_type_to_check} ID {item_id_to_check} ('{release_name_for_log}').")
                                mapping_manager.update_torrent_status_in_map(thash_for_map, f"imported_verified_file_present", f"File presence verified for {release_name_for_log}.")

                                if set_unmonitored_enabled:
                                    current_app.logger.info(f"POST_IMPORT_CHECK: Attempting to set item {app_type_to_check} ID {item_id_to_check} to UNMONITORED.")
                                    original_monitored_status = media_details_api.get('monitored', True) # Default to True if not found

                                    if app_type_to_check == 'radarr':
                                        if original_monitored_status: # Only update if it's currently monitored
                                            media_details_api['monitored'] = False
                                            if arr_client.update_radarr_movie(media_details_api):
                                                current_app.logger.info(f"POST_IMPORT_CHECK: Radarr movie ID {item_id_to_check} successfully set to UNMONITORED.")
                                                mapping_manager.update_torrent_status_in_map(thash_for_map, f"imported_verified_unmonitored", f"File present; Radarr movie ID {item_id_to_check} set unmonitored.")
                                            else:
                                                current_app.logger.warning(f"POST_IMPORT_CHECK: FAILED to set Radarr movie ID {item_id_to_check} to unmonitored.")
                                        else:
                                            current_app.logger.info(f"POST_IMPORT_CHECK: Radarr movie ID {item_id_to_check} was already unmonitored.")
                                            mapping_manager.update_torrent_status_in_map(thash_for_map, f"imported_verified_already_unmonitored", f"File present; Radarr movie ID {item_id_to_check} already unmonitored.")

                                    elif app_type_to_check == 'sonarr':
                                        series_monitored_changed = False
                                        if original_monitored_status: # Check series monitored status
                                            media_details_api['monitored'] = False
                                            series_monitored_changed = True

                                        # Set seasons to unmonitored - this is how Sonarr API expects it for series PUT
                                        # if they were monitored.
                                        seasons_monitored_changed = False
                                        if media_details_api.get('seasons'):
                                            for season_api in media_details_api['seasons']:
                                                if season_api.get('monitored', False): # Only change if it was true
                                                    season_api['monitored'] = False
                                                    seasons_monitored_changed = True

                                        if series_monitored_changed or seasons_monitored_changed:
                                            if arr_client.update_sonarr_series(media_details_api):
                                                current_app.logger.info(f"POST_IMPORT_CHECK: Sonarr series ID {item_id_to_check} (and/or its seasons) successfully set to UNMONITORED.")
                                                mapping_manager.update_torrent_status_in_map(thash_for_map, f"imported_verified_unmonitored", f"File present; Sonarr series ID {item_id_to_check} set unmonitored.")
                                            else:
                                                current_app.logger.warning(f"POST_IMPORT_CHECK: FAILED to set Sonarr series ID {item_id_to_check} to unmonitored.")
                                        else:
                                            current_app.logger.info(f"POST_IMPORT_CHECK: Sonarr series ID {item_id_to_check} (and its seasons) were already unmonitored.")
                                            mapping_manager.update_torrent_status_in_map(thash_for_map, f"imported_verified_already_unmonitored", f"File present; Sonarr series ID {item_id_to_check} already unmonitored.")
                                return True # File is present
                            else: # File not present
                                current_app.logger.warning(f"POST_IMPORT_CHECK: File NOT CONFIRMED present for {app_type_to_check} ID {item_id_to_check} ('{release_name_for_log}') after API check.")
                                mapping_manager.update_torrent_status_in_map(thash_for_map, f"imported_api_file_still_missing", f"File still missing for {release_name_for_log} after API check.")
                                return False
                        # --- End Helper ---

                        if not media_map_info:
                            current_app.logger.warning(f"SFTP Scanner Task: No pre-association found in mapping_manager for release '{item_name}'. Skipping import monitoring and intervention.")
                            # Mark as processed to avoid re-download, but status in map won't be updated beyond initial.
                            processed_items.add(remote_item_full_path)
                            new_items_processed_this_run = True
                            mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "processed_sftp_no_map_for_monitor", f"Notified {arr_type}, but no map entry for monitoring.")
                        elif monitoring_enabled and media_map_info:
                            target_id = media_map_info.get('target_id')
                            current_app.logger.info(f"SFTP Scanner Task: Monitoring import of '{item_name}' for {arr_type} (ID: {target_id}), monitoring for {monitoring_duration_minutes} min.")
                            mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "monitoring_arr_import", f"Awaiting import by {arr_type}.")

                            start_time = time.time()
                            processed_successfully_or_intervention_attempted = False

                            while time.time() - start_time < monitoring_duration_minutes * 60:
                                queue_status_result = arr_client.get_item_status_from_queue(
                                    arr_type=media_map_info['app_type'], # Use app_type from map
                                    release_name=item_name,
                                    torrent_hash=torrent_hash_map_entry
                                )
                                status = queue_status_result.get("status")
                                messages = queue_status_result.get("messages", [])
                                reason_code = queue_status_result.get("reason_code") # e.g. NO_FILES_ELIGIBLE

                                current_app.logger.debug(f"SFTP Scanner Task: Queue check for '{item_name}': Status='{status}', Reason='{reason_code}', Msgs='{messages}'")

                                if status == "completed":
                                    current_app.logger.info(f"SFTP Scanner Task: Import of '{item_name}' reported as COMPLETED by {media_map_info['app_type']}. Verifying file presence...")
                                    file_really_present = _verify_file_and_set_unmonitored(
                                        media_map_info['app_type'],
                                        target_id,
                                        item_name, # release_name
                                        torrent_hash_map_entry
                                    )
                                    if not file_really_present:
                                        current_app.logger.warning(f"SFTP Scanner Task: '{item_name}' reported COMPLETED by queue, but file not found/verified. Simulating 'NO_FILES_ELIGIBLE' to trigger intervention.")
                                        status = "failed"
                                        reason_code = "NO_FILES_ELIGIBLE"
                                        messages.append("MMS: Item reported completed by queue, but file presence verification failed.")
                                        # Fall through to the 'failed' and 'NO_FILES_ELIGIBLE' logic
                                    else: # File is present and verified
                                        processed_successfully_or_intervention_attempted = True
                                        break # Genuine success

                                # This 'if' must be separate from the one above, because 'status' might have been changed
                                if status == "pending" or status == "importing":
                                    current_app.logger.info(f"SFTP Scanner Task: Import of '{item_name}' is '{status}'. Waiting...")
                                    mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, f"arr_import_{status}", f"{media_map_info['app_type']} import is {status}.")

                                elif status == "failed" and reason_code == "NO_FILES_ELIGIBLE":
                                    current_app.logger.warning(f"SFTP Scanner Task: Import of '{item_name}' FAILED in {media_map_info['app_type']} with NO_FILES_ELIGIBLE. Messages: {messages}")
                                    mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_failed_no_files", "; ".join(messages))

                                    if manual_import_enabled:
                                        current_app.logger.info(f"SFTP Scanner Task: Attempting manual import for '{item_name}' into {media_map_info['app_type']} ID {target_id}.")
                                        manual_import_success = arr_client.trigger_manual_import(
                                            arr_type=media_map_info['app_type'],
                                            item_id=target_id,
                                            file_path_in_staging=str(staging_dir / item_name),
                                            release_name=item_name
                                        )
                                        if manual_import_success:
                                            current_app.logger.info(f"SFTP Scanner Task: Manual import command for '{item_name}' sent. Verifying file and setting unmonitored after short delay.")
                                            time.sleep(config.get('MMS_IMPORT_MONITORING_INTERVAL_SECONDS', 30) / 2) # Wait a bit for import to process

                                            file_present_after_manual = _verify_file_and_set_unmonitored(
                                                media_map_info['app_type'],
                                                target_id,
                                                item_name,
                                                torrent_hash_map_entry
                                            )
                                            if file_present_after_manual:
                                                # Status already updated by _verify_file_and_set_unmonitored to "imported_verified_file_present" or "imported_verified_unmonitored"
                                                current_app.logger.info(f"SFTP Scanner Task: Manual import for '{item_name}' appears successful and file verified.")
                                            else:
                                                current_app.logger.warning(f"SFTP Scanner Task: Manual import command for '{item_name}' sent, but file still not verified.")
                                                # Status "imported_api_file_still_missing" set by helper
                                        else: # Manual import command failed to send
                                            current_app.logger.error(f"SFTP Scanner Task: Manual import command for '{item_name}' FAILED to send.")
                                            mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "mms_manual_import_failed_to_send", f"Failed to send manual import command to {media_map_info['app_type']}.")
                                    else: # Manual import disabled
                                        current_app.logger.info(f"SFTP Scanner Task: Manual import disabled. '{item_name}' remains failed in {media_map_info['app_type']}.")
                                        mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_failed_no_intervention", "Manual import disabled.")
                                    processed_successfully_or_intervention_attempted = True
                                    break

                                elif status == "failed": # Other failure reason
                                    current_app.logger.error(f"SFTP Scanner Task: Import of '{item_name}' FAILED in {media_map_info['app_type']}. Reason: {reason_code}, Msgs: {messages}")
                                    mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, f"arr_import_failed_{reason_code or 'other'}", "; ".join(messages))
                                    processed_successfully_or_intervention_attempted = True
                                    break

                                elif status == "not_found_in_queue":
                                    current_app.logger.warning(f"SFTP Scanner Task: '{item_name}' not found in {media_map_info['app_type']} queue. Attempting final file verification.")
                                    # If not found, it might have processed very fast or there's a matching issue.
                                    # Perform a final verification.
                                    file_present_after_notfound = _verify_file_and_set_unmonitored(
                                        media_map_info['app_type'],
                                        target_id,
                                        item_name,
                                        torrent_hash_map_entry
                                    )
                                    if file_present_after_notfound:
                                        current_app.logger.info(f"SFTP Scanner Task: '{item_name}' was not in queue, but file IS present. Assuming successful import.")
                                    else:
                                        current_app.logger.warning(f"SFTP Scanner Task: '{item_name}' was not in queue AND file is NOT present. Import likely failed silently or name mismatch.")
                                        # Status updated by helper if file still missing
                                    processed_successfully_or_intervention_attempted = True
                                    break

                                elif status == "api_error" or status == "unknown":
                                    current_app.logger.error(f"SFTP Scanner Task: API error or unknown status for '{item_name}' from {media_map_info['app_type']} queue. Msgs: {messages}")
                                    mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_monitoring_error", "; ".join(messages))
                                    processed_successfully_or_intervention_attempted = True
                                    break

                                time.sleep(monitoring_interval_seconds)

                            if not processed_successfully_or_intervention_attempted: # Loop timed out
                                current_app.logger.warning(f"SFTP Scanner Task: Import monitoring for '{item_name}' timed out after {monitoring_duration_minutes} minutes. Performing final file check.")
                                final_file_check_after_timeout = _verify_file_and_set_unmonitored(
                                    media_map_info['app_type'],
                                    target_id,
                                    item_name,
                                    torrent_hash_map_entry
                                )
                                if not final_file_check_after_timeout:
                                     mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_monitoring_timeout_file_missing", f"Monitoring timed out for {media_map_info['app_type']}, file not verified.")
                                # Else, status updated by helper if file was found.

                        # Regardless of monitoring outcome, if initial notification was ok, mark sftp item as processed
                        processed_items.add(remote_item_full_path)
                        new_items_processed_this_run = True
                        current_app.logger.info(f"SFTP Scanner Task: Finished processing (including monitoring/intervention if any) for '{item_name}'. Marked as processed for SFTP.")

                    else: # Notification failed
                        current_app.logger.error(f"SFTP Scanner Task: Failed to notify {arr_type} for '{item_name}'. Item will be re-processed next cycle.")
                        # Do not add to processed_items, it will be picked up again.
                        if torrent_hash_map_entry: # If we found it in map
                             mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_notification_failed", f"Failed to notify {arr_type}.")
                else: # Download failed
                    current_app.logger.error(f"SFTP Scanner Task: Failed to download '{item_name}'. It will be retried next cycle.")
                    if torrent_hash_map_entry: # If we found it in map, update status
                        mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "sftp_download_failed", f"Failed to download {item_name} from SFTP.")

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
    #             'SEEDBOX_SONARR_FINISHED_PATH': '/upload/sonarr_completed', # Test path
    #             'SEEDBOX_RADARR_FINISHED_PATH': '/upload/radarr_completed', # Test path
    #             'STAGING_DIR': './staging_test', # Local test staging dir
    #             'PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT': './processed_sftp_test.json',
    #             # SONARR_URL, SONARR_API_KEY, RADARR_URL, RADARR_API_KEY for _notify_arr_instance if testing that part
    #         })
    #         self.logger = MockLogger()
    #
    # current_app = MockApp()
    # # Ensure staging_test directory exists
    # if not os.path.exists(current_app.config['STAGING_DIR']):
    #    os.makedirs(current_app.config['STAGING_DIR'])
    # scan_sftp_and_process_items()
