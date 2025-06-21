# app/utils/sftp_scanner.py
import os
import json
from pathlib import Path
import pysftp # Assuming pysftp, may need to install or change later
import time
from flask import current_app
from . import arr_client, mapping_manager
import shutil # Ajout pour shutil.rmtree dans _download_item

# Configure logging
logger = current_app.logger # Utiliser le logger de Flask directement si possible, sinon logging.getLogger(__name__)

def _load_processed_items(log_file_path):
    try:
        with open(log_file_path, 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {log_file_path}. Starting with an empty set of processed items.")
        return set()

def _save_processed_items(log_file_path, processed_items):
    try:
        with open(log_file_path, 'w') as f:
            json.dump(list(processed_items), f, indent=4)
    except IOError as e:
        logger.error(f"Error saving processed items to {log_file_path}: {e}")

def _connect_sftp():
    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None
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
        logger.info(f"Successfully connected to SFTP server: {sftp_host}")
        return sftp
    except Exception as e:
        logger.error(f"SFTP connection failed for {sftp_user}@{sftp_host}:{sftp_port} - {e}")
        return None

def _list_remote_files(sftp, remote_path):
    items = []
    try:
        if sftp.exists(remote_path) and sftp.isdir(remote_path):
            logger.info(f"Scanning remote path: {remote_path}")
            for item_attr in sftp.listdir_attr(remote_path):
                if item_attr.filename not in ['.', '..']:
                    items.append(item_attr)
        else:
            logger.warning(f"Remote path not found or not a directory: {remote_path}")
    except Exception as e:
        logger.error(f"Error listing files in {remote_path}: {e}")
    return items

def _download_item(sftp, remote_item_path, local_staging_path, item_name_on_sftp_listing):
    local_item_path = Path(local_staging_path) / item_name_on_sftp_listing
    try:
        if sftp.isfile(remote_item_path):
            logger.info(f"Downloading file: {remote_item_path} to {local_item_path}")
            sftp.get(remote_item_path, str(local_item_path))
            logger.info(f"Successfully downloaded file: {item_name_on_sftp_listing}")
            return True
        elif sftp.isdir(remote_item_path):
            logger.info(f"Attempting to download directory: {remote_item_path} to {local_item_path}")
            try:
                os.makedirs(local_item_path, exist_ok=True)
                logger.info(f"Ensured local directory exists for item '{item_name_on_sftp_listing}': {local_item_path}")

                # Utilisation de la fonction get_r de pysftp pour les dossiers
                sftp.get_r(remote_item_path, str(local_item_path), preserve_mtime=True)

                logger.info(f"Successfully downloaded directory '{item_name_on_sftp_listing}' from '{remote_item_path}' to '{local_item_path}'.")
                return True
            except Exception as e_dir_download:
                logger.error(f"Error during directory download for '{item_name_on_sftp_listing}' from '{remote_item_path}' to '{local_item_path}': {e_dir_download}")
                if local_item_path.exists():
                    logger.warning(f"Attempting to cleanup partially downloaded directory: {local_item_path}")
                    try:
                        shutil.rmtree(local_item_path)
                        logger.info(f"Successfully cleaned up directory: {local_item_path}")
                    except Exception as cleanup_e:
                        logger.error(f"Error cleaning up directory {local_item_path}: {cleanup_e}")
                return False
        else:
            logger.warning(f"Item {remote_item_path} is not a file or directory. Skipping.")
            return False
    except Exception as e:
        logger.error(f"Error downloading {remote_item_path} to {local_item_path}: {e}")
        if local_item_path.exists():
            try:
                if local_item_path.is_file(): local_item_path.unlink()
                elif local_item_path.is_dir(): shutil.rmtree(local_item_path) # Nettoyage dossier si échec global
            except Exception as cleanup_e:
                logger.error(f"Error cleaning up {local_item_path}: {cleanup_e}")
        return False

def _notify_arr_instance(arr_type, item_name_for_arr, local_staging_dir):
    item_path_in_staging = Path(local_staging_dir) / item_name_for_arr
    logger.info(f"Notifying {arr_type} for item: {item_path_in_staging}")
    success = False
    if arr_type == "sonarr":
        success = arr_client.trigger_sonarr_scan(str(item_path_in_staging))
    elif arr_type == "radarr":
        success = arr_client.trigger_radarr_scan(str(item_path_in_staging))
    if success:
        logger.info(f"Successfully notified {arr_type} for item: {item_name_for_arr}")
    else:
        logger.error(f"Failed to notify {arr_type} for item: {item_name_for_arr}")
    return success

def scan_sftp_and_process_items():
    if not current_app.sftp_scan_lock.acquire(blocking=False):
        logger.info("SFTP Scan deferred: Another scan is already in progress.")
        return
    try:
        logger.info("SFTP Scanner Task: Lock acquired, starting scan and process cycle.")
        config = current_app.config # Accès direct à config
        staging_dir = Path(config['STAGING_DIR'])
        log_file = config['PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT']

        if not staging_dir.exists():
            try:
                staging_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created staging directory: {staging_dir}")
            except OSError as e:
                logger.error(f"Could not create staging directory {staging_dir}: {e}. Aborting SFTP scan.")
                return

        processed_items_sftp_log = _load_processed_items(log_file)
        sftp = _connect_sftp()
        if not sftp:
            logger.error("SFTP Scanner Task: Could not connect to SFTP server. Aborting.")
            return

        folders_to_scan = {
            "sonarr": config.get('SEEDBOX_SONARR_FINISHED_PATH'),
            "radarr": config.get('SEEDBOX_RADARR_FINISHED_PATH'),
        }
        new_items_processed_this_run = False

        for arr_type, remote_base_path in folders_to_scan.items():
            if not remote_base_path:
                logger.warning(f"SFTP Scanner Task: Remote path for {arr_type} is not configured. Skipping.")
                continue
            logger.info(f"SFTP Scanner Task: Scanning {arr_type} remote path: {remote_base_path}")
            remote_items = _list_remote_files(sftp, remote_base_path)

            for item_attr in remote_items:
                item_name_on_sftp = item_attr.filename
                remote_item_full_path = f"{remote_base_path.rstrip('/')}/{item_name_on_sftp}"

                if remote_item_full_path in processed_items_sftp_log:
                    continue
                logger.info(f"SFTP Scanner Task: Found new item '{item_name_on_sftp}' in {remote_base_path} for {arr_type}.")

                # --- Guardrail Logic ---
                guardrail_enabled = config.get('SFTP_SCANNER_GUARDFRAIL_ENABLED', True)
                media_exists_in_arr = False
                parsed_media = None
                if guardrail_enabled:
                    logger.info(f"SFTP Scanner Task: Guardrail enabled. Parsing '{item_name_on_sftp}'.")
                    parsed_media = arr_client.parse_media_name(item_name_on_sftp)
                    logger.info(f"SFTP Scanner Task: Parsed '{item_name_on_sftp}' as: {parsed_media}")
                    if parsed_media and parsed_media['type'] != 'unknown':
                        if parsed_media['type'] == 'tv' and parsed_media['title'] and parsed_media['season'] is not None:
                            try:
                                media_exists_in_arr = arr_client.check_sonarr_episode_exists(parsed_media['title'], parsed_media['season'], parsed_media.get('episode'))
                                logger.info(f"SFTP Scanner Task: Sonarr check for '{item_name_on_sftp}' result: {media_exists_in_arr}")
                            except Exception as e: logger.error(f"SFTP Scanner Task: Error checking Sonarr: {e}")
                        elif parsed_media['type'] == 'movie' and parsed_media['title']:
                            try:
                                media_exists_in_arr = arr_client.check_radarr_movie_exists(parsed_media['title'], parsed_media.get('year'))
                                logger.info(f"SFTP Scanner Task: Radarr check for '{item_name_on_sftp}' result: {media_exists_in_arr}")
                            except Exception as e: logger.error(f"SFTP Scanner Task: Error checking Radarr: {e}")
                    else: logger.info(f"SFTP Scanner Task: Could not reliably parse '{item_name_on_sftp}'. Proceeding.")
                else: logger.info("SFTP Scanner Task: Guardrail disabled.")

                if guardrail_enabled and media_exists_in_arr:
                    logger.info(f"SFTP Scanner Task: Guardrail - Item '{item_name_on_sftp}' found in {arr_type} library. Skipping.")
                    processed_items_sftp_log.add(remote_item_full_path)
                    new_items_processed_this_run = True
                    continue
                # --- End Guardrail ---

                if _download_item(sftp, remote_item_full_path, staging_dir, item_name_on_sftp):
                    item_path_in_staging = staging_dir / item_name_on_sftp
                    item_name_for_arr_processing = item_name_on_sftp

                    if item_path_in_staging.is_file():
                        logger.info(f"SFTP Scanner: '{item_name_on_sftp}' is a file. Wrapping in directory.")
                        new_folder_name = item_path_in_staging.stem
                        new_folder_path_in_staging = staging_dir / new_folder_name
                        if not new_folder_name: # Should not happen for valid files
                             logger.warning(f"SFTP Scanner: Could not derive folder name from '{item_name_on_sftp}'. Using original file for Arr (may fail).")
                        else:
                            if not new_folder_path_in_staging.exists(): new_folder_path_in_staging.mkdir()
                            if new_folder_path_in_staging.is_dir():
                                try:
                                    item_path_in_staging.rename(new_folder_path_in_staging / item_name_on_sftp)
                                    item_name_for_arr_processing = new_folder_name # Update to use folder name
                                    logger.info(f"SFTP Scanner: File '{item_name_on_sftp}' moved to '{new_folder_path_in_staging / item_name_on_sftp}'. Processing as '{item_name_for_arr_processing}'.")
                                except Exception as e_mv:
                                    logger.error(f"SFTP Scanner: Failed to move file to wrapper dir: {e_mv}. Using original file path.")
                            else: # Conflict: a file exists with the target folder name
                                logger.error(f"SFTP Scanner: Cannot create wrapper dir '{new_folder_path_in_staging}', a file exists. Using original file path.")

                    notification_successful = _notify_arr_instance(arr_type, item_name_for_arr_processing, staging_dir)

                    if notification_successful:
                        logger.info(f"SFTP Scanner Task: Notification sent for '{item_name_for_arr_processing}'. Monitoring if enabled.")
                        monitoring_enabled = config.get('MMS_IMPORT_MONITORING_ENABLED', True)
                        torrent_hash_map_entry, media_map_info = mapping_manager.find_torrent_by_release_name(item_name_on_sftp)

                        if not media_map_info:
                            logger.warning(f"SFTP Scanner Task: No pre-association for '{item_name_on_sftp}'. Skipping monitoring.")
                            if torrent_hash_map_entry: mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "processed_sftp_no_map_for_monitor", f"Notified {arr_type}, but no map entry for monitoring.")
                        elif monitoring_enabled:
                            target_id = media_map_info.get('target_id')
                            logger.info(f"SFTP Scanner: Monitoring import of '{item_name_for_arr_processing}' (original: '{item_name_on_sftp}') for {media_map_info['app_type']} ID {target_id} for {config.get('MMS_IMPORT_MONITORING_DURATION_MINUTES')} min.")
                            mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "monitoring_arr_import", f"Awaiting import by {media_map_info['app_type']}.")

                            start_time = time.time()
                            processed_successfully_or_intervention_attempted = False
                            manual_import_enabled = config.get('MMS_MANUAL_IMPORT_ATTEMPT_ENABLED', True)

                            # Helper function for verification and unmonitoring
                            def _verify_and_unmonitor(app_type_check, item_id_check, arr_item_name_check, map_hash_check):
                                logger.info(f"POST_CHECK: Verifying file for {app_type_check} ID {item_id_check} ('{arr_item_name_check}').")
                                details = arr_client.get_expected_media_details(app_type_check, item_id_check)
                                file_ok = False
                                if details:
                                    if app_type_check == 'radarr' and details.get('hasFile') and details.get('movieFile',{}).get('sizeOnDisk',0) > 0: file_ok = True
                                    elif app_type_check == 'sonarr' and details.get('statistics',{}).get('episodeFileCount',0) > 0: file_ok = True # Basic check

                                if file_ok:
                                    logger.info(f"POST_CHECK: File CONFIRMED for {app_type_check} ID {item_id_check}.")
                                    mapping_manager.update_torrent_status_in_map(map_hash_check, "imported_verified_file_present", f"File verified for {arr_item_name_check}.")
                                    if config.get('MMS_SET_UNMONITORED_AFTER_IMPORT', True):
                                        details['monitored'] = False
                                        if app_type_check == 'sonarr' and details.get('seasons'):
                                            for s in details['seasons']: s['monitored'] = False
                                        update_func = arr_client.update_radarr_movie if app_type_check == 'radarr' else arr_client.update_sonarr_series
                                        if update_func(details):
                                            logger.info(f"POST_CHECK: {app_type_check} ID {item_id_check} set UNMONITORED.")
                                            mapping_manager.update_torrent_status_in_map(map_hash_check, "imported_verified_unmonitored", f"File verified; {app_type_check} ID {item_id_check} unmonitored.")
                                        else: logger.warning(f"POST_CHECK: FAILED to set {app_type_check} ID {item_id_to_check} unmonitored.")
                                    return True
                                else:
                                    logger.warning(f"POST_CHECK: File NOT CONFIRMED for {app_type_check} ID {item_id_check} ('{arr_item_name_check}').")
                                    mapping_manager.update_torrent_status_in_map(map_hash_check, "imported_api_file_still_missing", f"File missing for {arr_item_name_check} after API check.")
                                    return False

                            while time.time() - start_time < config.get('MMS_IMPORT_MONITORING_DURATION_MINUTES', 5) * 60:
                                q_res = arr_client.get_item_status_from_queue(media_map_info['app_type'], item_name_for_arr_processing, torrent_hash_map_entry)
                                status, msgs, reason = q_res.get("status"), q_res.get("messages",[]), q_res.get("reason_code")
                                logger.debug(f"SFTP Q_Check for '{item_name_for_arr_processing}': Status='{status}', Reason='{reason}'")

                                if status == "completed":
                                    logger.info(f"SFTP: Import of '{item_name_for_arr_processing}' reported COMPLETED. Verifying file...")
                                    if not _verify_and_unmonitor(media_map_info['app_type'], target_id, item_name_for_arr_processing, torrent_hash_map_entry):
                                        status, reason = "failed", "NO_FILES_ELIGIBLE" # Override to trigger intervention
                                        msgs.append("MMS: File missing post-completion.")
                                    else: processed_successfully_or_intervention_attempted = True; break

                                if status == "pending" or status == "importing":
                                    logger.info(f"SFTP: Import of '{item_name_for_arr_processing}' is '{status}'. Waiting...")
                                    mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, f"arr_import_{status}", f"{media_map_info['app_type']} import is {status}.")
                                elif status == "failed" and reason == "NO_FILES_ELIGIBLE":
                                    logger.warning(f"SFTP: Import of '{item_name_for_arr_processing}' FAILED (NO_FILES_ELIGIBLE). Msgs: {msgs}")
                                    mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_failed_no_files", "; ".join(msgs))
                                    if manual_import_enabled:
                                        logger.info(f"SFTP: Attempting manual import for '{item_name_for_arr_processing}' to ID {target_id}.")
                                        if arr_client.trigger_manual_import(media_map_info['app_type'], target_id, str(staging_dir / item_name_for_arr_processing), item_name_for_arr_processing):
                                            logger.info(f"SFTP: Manual import for '{item_name_for_arr_processing}' sent. Verifying after delay.")
                                            time.sleep(config.get('MMS_IMPORT_MONITORING_INTERVAL_SECONDS', 30))
                                            _verify_and_unmonitor(media_map_info['app_type'], target_id, item_name_for_arr_processing, torrent_hash_map_entry)
                                        else: logger.error(f"SFTP: Manual import command for '{item_name_for_arr_processing}' FAILED to send."); mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "mms_manual_import_cmd_failed", "Cmd send fail")
                                    else: logger.info("SFTP: Manual import disabled."); mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_failed_no_intervention", "Manual import off.")
                                    processed_successfully_or_intervention_attempted = True; break
                                elif status == "failed":
                                    logger.error(f"SFTP: Import of '{item_name_for_arr_processing}' FAILED. Reason: {reason}, Msgs: {msgs}")
                                    mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, f"arr_import_failed_{reason or 'other'}", "; ".join(msgs)); processed_successfully_or_intervention_attempted = True; break
                                elif status == "not_found_in_queue":
                                    logger.warning(f"SFTP: '{item_name_for_arr_processing}' not in queue. Waiting {config.get('MMS_POST_NOTIFY_FAST_QUEUE_CHECK_DELAY_SECONDS')}s then verifying/intervening.")
                                    time.sleep(config.get('MMS_POST_NOTIFY_FAST_QUEUE_CHECK_DELAY_SECONDS', 15))
                                    if not _verify_and_unmonitor(media_map_info['app_type'], target_id, item_name_for_arr_processing, torrent_hash_map_entry):
                                        if manual_import_enabled:
                                            logger.info(f"SFTP (from not_found): Attempting manual import for '{item_name_for_arr_processing}' to ID {target_id}.")
                                            if arr_client.trigger_manual_import(media_map_info['app_type'], target_id, str(staging_dir / item_name_for_arr_processing), item_name_for_arr_processing):
                                                logger.info(f"SFTP (from not_found): Manual import for '{item_name_for_arr_processing}' sent. Verifying after delay.")
                                                time.sleep(config.get('MMS_IMPORT_MONITORING_INTERVAL_SECONDS', 30))
                                                _verify_and_unmonitor(media_map_info['app_type'], target_id, item_name_for_arr_processing, torrent_hash_map_entry)
                                            else: logger.error(f"SFTP (from not_found): Manual import cmd FAILED for '{item_name_for_arr_processing}'."); mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "mms_manual_import_cmd_failed_nf", "Cmd send fail (nf).")
                                        else: logger.info("SFTP (from not_found): Manual import disabled."); mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_failed_nf_no_intervention", "Not in Q, file miss, manual off.")
                                    processed_successfully_or_intervention_attempted = True; break
                                elif status == "api_error" or status == "unknown":
                                    logger.error(f"SFTP: API error/unknown status for '{item_name_for_arr_processing}'. Msgs: {msgs}"); mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_monitoring_error", "; ".join(msgs)); processed_successfully_or_intervention_attempted = True; break
                                time.sleep(config.get('MMS_IMPORT_MONITORING_INTERVAL_SECONDS', 30))

                            if not processed_successfully_or_intervention_attempted: # Timeout
                                logger.warning(f"SFTP: Monitoring for '{item_name_for_arr_processing}' timed out. Final check.")
                                if not _verify_and_unmonitor(media_map_info['app_type'], target_id, item_name_for_arr_processing, torrent_hash_map_entry):
                                     mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_import_monitoring_timeout_file_missing", "Monitor timeout, file not verified.")

                        processed_items_sftp_log.add(remote_item_full_path)
                        new_items_processed_this_run = True
                        logger.info(f"SFTP Scanner Task: Finished processing for '{item_name_on_sftp}'. Marked as processed for SFTP.")
                    else: # Notification failed
                        logger.error(f"SFTP Scanner Task: Failed to notify {arr_type} for '{item_name_for_arr_processing}'. Will retry.")
                        if torrent_hash_map_entry: mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "arr_notification_failed", f"Failed to notify {arr_type}.")
                else: # Download failed
                    logger.error(f"SFTP Scanner Task: Failed to download '{item_name_on_sftp}'. Will retry.")
                    if torrent_hash_map_entry: mapping_manager.update_torrent_status_in_map(torrent_hash_map_entry, "sftp_download_failed", f"Failed to download {item_name_on_sftp} from SFTP.")
        if sftp: sftp.close(); logger.info("SFTP connection closed.")
        if new_items_processed_this_run: _save_processed_items(log_file, processed_items_sftp_log); logger.info("SFTP Scanner Task: Scan cycle finished (before lock release).")
    finally:
        current_app.sftp_scan_lock.release()
        logger.info("SFTP Scanner Task: Lock released after scan cycle.")

if __name__ == '__main__':
    print("This script is intended to be run within the Flask application context.")
