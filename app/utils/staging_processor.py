# app/utils/staging_processor.py
from flask import current_app
from . import mapping_manager, arr_client
import os
import shutil
import pysftp
from pathlib import Path

def _connect_sftp():
    """Establishes an SFTP connection using settings from current_app.config."""
    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None  # Consider security implications
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
        current_app.logger.info(f"Staging Processor: Successfully connected to SFTP server: {sftp_host}")
        return sftp
    except Exception as e:
        current_app.logger.error(f"Staging Processor: SFTP connection failed for {sftp_user}@{sftp_host}:{sftp_port} - {e}")
        return None

def _rapatriate_item(sftp, remote_path, release_name):
    """
    Downloads an item (file or directory) from the seedbox to the local staging directory.
    Returns True on success, False on failure.
    """
    local_staging_path = current_app.config['LOCAL_STAGING_PATH']
    local_item_path = Path(local_staging_path) / release_name
    # The remote_path from the mapping manager is the base directory of the torrent.
    # The release_name is the name of the file/folder within that directory.
    remote_item_path = f"{remote_path.rstrip('/')}/{release_name}"

    current_app.logger.info(f"Staging Processor: Repatriating '{release_name}' from '{remote_item_path}' to '{local_item_path}'")

    try:
        if not sftp.exists(remote_item_path):
            current_app.logger.error(f"Staging Processor: Remote item does not exist: {remote_item_path}")
            return False

        if sftp.isfile(remote_item_path):
            current_app.logger.info(f"Downloading file: {remote_item_path} to {local_item_path}")
            sftp.get(remote_item_path, str(local_item_path), preserve_mtime=True)
            current_app.logger.info(f"Successfully downloaded file: {release_name}")
            return True

        elif sftp.isdir(remote_item_path):
            current_app.logger.info(f"Starting robust directory download for: {remote_item_path}")
            os.makedirs(local_item_path, exist_ok=True)

            def file_callback(remotefile):
                relative_path = os.path.relpath(remotefile, start=remote_item_path).replace('\\', '/')
                local_file = local_item_path / Path(relative_path)
                os.makedirs(local_file.parent, exist_ok=True)
                current_app.logger.debug(f"Copying remote file '{remotefile}' to '{local_file}'")
                sftp.get(remotefile, str(local_file), preserve_mtime=True)

            def dir_callback(remotedir):
                relative_path = os.path.relpath(remotedir, start=remote_item_path).replace('\\', '/')
                if relative_path != '.':
                    local_dir = local_item_path / Path(relative_path)
                    os.makedirs(local_dir, exist_ok=True)

            def unknown_callback(remote_unknown):
                current_app.logger.warning(f"Skipping unknown item type during walktree: {remote_unknown}")

            sftp.walktree(remote_item_path, file_callback, dir_callback, unknown_callback)
            current_app.logger.info(f"Successfully downloaded directory '{release_name}' using walktree method.")
            return True
        else:
            current_app.logger.warning(f"Item {remote_item_path} is not a file or directory. Skipping.")
            return False

    except Exception as e:
        current_app.logger.error(f"FATAL error during download of {remote_item_path}: {e}", exc_info=True)
        if local_item_path.exists():
            current_app.logger.warning(f"Attempting to cleanup partially downloaded item: {local_item_path}")
            try:
                if local_item_path.is_dir():
                    shutil.rmtree(local_item_path)
                else:
                    os.remove(local_item_path)
                current_app.logger.info(f"Cleanup successful for {local_item_path}")
            except Exception as cleanup_e:
                current_app.logger.error(f"Error during cleanup of {local_item_path}: {cleanup_e}")
        return False

def _cleanup_staging(item_name):
    """Cleans up a directory/file from the staging directory."""
    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')
    if not local_staging_path:
        current_app.logger.error("Staging Processor: LOCAL_STAGING_PATH is not configured. Cannot perform cleanup.")
        return

    path_to_clean = os.path.join(local_staging_path, item_name)
    try:
        if os.path.isdir(path_to_clean):
            shutil.rmtree(path_to_clean)
        elif os.path.isfile(path_to_clean):
            os.remove(path_to_clean)
        current_app.logger.info(f"Staging cleanup successful for '{item_name}'.")
    except Exception as e:
        current_app.logger.error(f"Staging cleanup failed for '{item_name}': {e}")

def _handle_automatic_import(item, queue_item, arr_type):
    """Delegates the import to Sonarr/Radarr."""
    release_name = item['release_name']
    torrent_hash = item['torrent_hash']

    current_app.logger.info(f"'{release_name}' is an automatic import. Delegating to {arr_type}.")

    local_item_path = os.path.join(current_app.config['LOCAL_STAGING_PATH'], release_name)
    trigger_func = arr_client.sonarr_trigger_import if arr_type == 'sonarr' else arr_client.radarr_trigger_import

    # The trigger function takes the path of the downloaded item
    if trigger_func(local_item_path):
        current_app.logger.info(f"Import for '{release_name}' triggered successfully in {arr_type}. Cleaning up staging.")
        _cleanup_staging(release_name)
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'completed_automatic')
        return True
    else:
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_import_delegation', f"The API call to trigger the import failed for {release_name}.")
        raise Exception(f"The API call to trigger the import failed for {release_name}.")

def _handle_manual_import(item, arr_type):
    """Handles a manual import via MMS for an item not found in the queue."""
    release_name = item['release_name']
    torrent_hash = item['torrent_hash']
    current_app.logger.info(f"Processing manual import for '{release_name}' for {arr_type}.")

    parsed_info = arr_client.parse_media_name(release_name)
    title_to_search = parsed_info.get('title')
    if not title_to_search:
        raise Exception("Parser could not extract a title from the release name.")

    target_id = None
    if arr_type == 'sonarr':
        series_info = arr_client.find_sonarr_series_by_title(title_to_search)
        if series_info:
            target_id = series_info.get('id')
    else: # radarr
        movie_info = arr_client.find_radarr_movie_by_title(title_to_search)
        if movie_info:
            target_id = movie_info.get('id')

    if not target_id:
        raise Exception(f"Media '{title_to_search}' not found in {arr_type} library.")

    source_path = os.path.join(current_app.config['LOCAL_STAGING_PATH'], release_name)
    current_app.logger.info(f"Manual import: '{source_path}' needs to be moved to its final destination. This logic is a placeholder.")

    # Placeholder for file moving logic.
    # In a real scenario, you would determine the final path from the *Arr item details.
    # e.g., final_path = os.path.join(series_info.get('path'), f"Season {parsed_info['season']}")
    # shutil.move(source_path, final_path)

    _cleanup_staging(release_name)
    mapping_manager.update_torrent_status_in_map(torrent_hash, 'completed_manual_placeholder')

    if arr_type == 'sonarr':
        arr_client.sonarr_post_command({'name': 'RescanSeries', 'seriesId': target_id})
    else:
        arr_client.radarr_post_command({'name': 'RescanMovie', 'movieId': target_id})

    return True

def process_pending_staging_items():
    """The main function that orchestrates the staging process."""
    current_app.logger.info("Staging Processor: Starting processing cycle.")

    items_to_process = mapping_manager.get_torrents_by_status('pending_staging')
    if not items_to_process:
        current_app.logger.info("Staging Processor: No items pending staging.")
        return

    sftp = None
    try:
        sftp = _connect_sftp()
        if not sftp:
            current_app.logger.error("Staging Processor: Could not connect to SFTP. Aborting cycle.")
            return

        for item in items_to_process:
            release_name = item.get('release_name')
            torrent_hash = item.get('torrent_hash')
            remote_path = item.get('seedbox_download_path')

            if not all([release_name, torrent_hash, remote_path]) or remote_path == "unknown":
                current_app.logger.error(f"Staging Processor: Skipping item due to missing data (e.g., download path): {item}")
                mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_missing_data', 'Item is missing critical data in map.')
                continue

            try:
                if not _rapatriate_item(sftp, remote_path, release_name):
                    mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_repatriation', 'Failed to download from seedbox')
                    continue

                mapping_manager.update_torrent_status_in_map(torrent_hash, 'in_staging')

                arr_type = mapping_manager.guess_arr_type_from_item(item)
                queue_item = arr_client.find_in_arr_queue_by_hash(arr_type, item['torrent_hash'])

                if queue_item:
                    _handle_automatic_import(item, queue_item, arr_type)
                else:
                    _handle_manual_import(item, arr_type)

            except Exception as e:
                current_app.logger.error(f"Staging Processor: Unhandled error while processing '{release_name}': {e}", exc_info=True)
                mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_staging', str(e))

    finally:
        if sftp:
            sftp.close()
            current_app.logger.info("Staging Processor: SFTP connection closed.")
        current_app.logger.info("Staging Processor: Processing cycle finished.")
