# app/utils/staging_processor.py
import os
import stat
import shutil
import paramiko
from flask import current_app
from pathlib import Path

from . import mapping_manager, arr_client
from app.utils.arr_client import parse_media_name

def _connect_sftp():
    """Establishes an SFTP connection using settings from current_app.config."""
    sftp_host = current_app.config['SEEDBOX_SFTP_HOST']
    sftp_port = current_app.config['SEEDBOX_SFTP_PORT']
    sftp_user = current_app.config['SEEDBOX_SFTP_USER']
    sftp_password = current_app.config['SEEDBOX_SFTP_PASSWORD']

    try:
        transport = paramiko.Transport((sftp_host, sftp_port))
        transport.connect(username=sftp_user, password=sftp_password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        current_app.logger.info(f"Staging Processor: Successfully connected to SFTP server: {sftp_host}")
        return sftp, transport
    except Exception as e:
        current_app.logger.error(f"Staging Processor: SFTP connection failed for {sftp_user}@{sftp_host}:{sftp_port} - {e}")
        return None, None

def _get_r_recursive(sftp_client, remotedir, localdir):
    """
    Recursively download a directory from a remote SFTP server.
    """
    for item_attr in sftp_client.listdir_attr(remotedir):
        remote_path = os.path.join(remotedir, item_attr.filename).replace('\\', '/')
        local_path = os.path.join(localdir, item_attr.filename)
        if stat.S_ISDIR(item_attr.st_mode):
            os.makedirs(local_path, exist_ok=True)
            _get_r_recursive(sftp_client, remote_path, local_path)
        else:
            sftp_client.get(remote_path, local_path)

def _rapatriate_item(item, sftp_client):
    release_name = item.get('release_name')
    remote_path = item.get('seedbox_download_path')
    local_path = os.path.join(current_app.config['LOCAL_STAGING_PATH'], release_name)

    current_app.logger.info(f"Rapatriement de '{release_name}' depuis '{remote_path}' vers '{local_path}'")

    try:
        # STRATÉGIE N°1 : On suppose que c'est un DOSSIER et on tente un téléchargement récursif.
        current_app.logger.info(f"Tentative de téléchargement de '{remote_path}' comme un dossier.")
        os.makedirs(local_path, exist_ok=True)
        _get_r_recursive(sftp_client, remote_path, local_path)
        current_app.logger.info(f"Téléchargement du dossier '{remote_path}' réussi.")
        return True
    except Exception as e_dir:
        current_app.logger.warning(f"Échec du téléchargement comme un dossier : {e_dir}. Tentative comme un fichier.")

        try:
            # STRATÉGIE N°2 (FALLBACK) : On suppose que c'est un FICHIER.
            # On s'assure que le dossier parent existe localement.
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            sftp_client.get(remote_path, local_path)
            current_app.logger.info(f"Téléchargement du fichier '{remote_path}' réussi.")
            return True
        except Exception as e_file:
            current_app.logger.error(f"Échec final du rapatriement. Ni un dossier, ni un fichier valide à l'emplacement '{remote_path}': {e_file}", exc_info=True)
            # On nettoie le dossier local potentiellement vide qui a été créé
            if os.path.isdir(local_path) and not os.listdir(local_path):
                shutil.rmtree(local_path)
            return False

def _cleanup_staging(item_name):
    """Deletes the item from the local staging directory."""
    local_staging_path = current_app.config['LOCAL_STAGING_PATH']
    item_path = os.path.join(local_staging_path, item_name)
    current_app.logger.info(f"Cleaning up staging for: {item_path}")
    try:
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        elif os.path.isfile(item_path):
            os.remove(item_path)
        current_app.logger.info(f"Successfully cleaned up {item_path}.")
        return True
    except Exception as e:
        current_app.logger.error(f"Error cleaning up staging for {item_path}: {e}", exc_info=True)
        return False

def _handle_automatic_import(item, queue_item, arr_type):
    """
    Handles the import process when the item is found in Sonarr/Radarr's queue.
    """
    torrent_hash = item['torrent_hash']
    release_name = item['release_name']
    current_app.logger.info(f"Handling automatic import for '{release_name}' (hash: {torrent_hash}) for {arr_type}.")

    import_triggered = False
    if arr_type == 'sonarr':
        import_result = arr_client.sonarr_trigger_import(torrent_hash)
        if import_result:
            import_triggered = True
    elif arr_type == 'radarr':
        import_result = arr_client.radarr_trigger_import(torrent_hash)
        if import_result:
            import_triggered = True

    if import_triggered:
        current_app.logger.info(f"Successfully triggered {arr_type} import for '{release_name}'.")
        mapping_manager.update_torrent_status_in_map(torrent_hash, f'imported_by_{arr_type}', f'Import triggered in {arr_type}.')
        _cleanup_staging(release_name)
    else:
        current_app.logger.error(f"Failed to trigger {arr_type} import for '{release_name}'.")
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_auto_import', f'Failed to trigger import in {arr_type}.')

def _handle_manual_import(item):
    """
    Handles the import process when the item is NOT in Sonarr/Radarr's queue.
    This implies it was a manual download.
    """
    torrent_hash = item['torrent_hash']
    release_name = item['release_name']
    current_app.logger.info(f"Handling manual import for '{release_name}'.")

    parsed_info = parse_media_name(release_name)
    media_type = parsed_info.get('type')
    title = parsed_info.get('title')

    local_staging_path = current_app.config['LOCAL_STAGING_PATH']
    item_path_in_staging = Path(local_staging_path) / release_name

    if media_type == 'tv':
        series_list = arr_client.search_sonarr_by_title(title)
        if series_list:
            arr_client.trigger_sonarr_scan(str(item_path_in_staging))
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'imported_by_sonarr_manual', f'Manual import scan triggered for series {series_list[0]["title"]}.')
            _cleanup_staging(release_name)
        else:
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', f'Could not find Sonarr series for title "{title}".')
    elif media_type == 'movie':
        movie_list = arr_client.search_radarr_by_title(title)
        if movie_list:
            arr_client.trigger_radarr_scan(str(item_path_in_staging))
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'imported_by_radarr_manual', f'Manual import scan triggered for movie {movie_list[0]["title"]}.')
            _cleanup_staging(release_name)
        else:
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', f'Could not find Radarr movie for title "{title}".')
    else:
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', f'Could not determine media type for "{release_name}".')

def process_pending_staging_items():
    """
    Main function for the staging processor.
    """
    current_app.logger.info("Staging Processor: Starting cycle.")

    all_torrents = mapping_manager.get_all_torrents_in_map()
    pending_items = {h: d for h, d in all_torrents.items() if d.get('status') == 'pending_staging'}

    if not pending_items:
        current_app.logger.info("Staging Processor: No items pending staging.")
        return

    sftp_client, transport = _connect_sftp()
    if not sftp_client:
        current_app.logger.error("Staging Processor: Could not connect to SFTP. Aborting cycle.")
        for torrent_hash in pending_items.keys():
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_sftp_connection', 'Could not connect to SFTP server.')
        return

    current_app.logger.info(f"Staging Processor: Found {len(pending_items)} items to process.")

    for torrent_hash, item_data in pending_items.items():
        item_data['torrent_hash'] = torrent_hash

        if _rapatriate_item(item_data, sftp_client):
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'in_staging', 'Item successfully downloaded to staging.')

            queue_item_sonarr = arr_client.find_in_arr_queue_by_hash('sonarr', torrent_hash)
            if queue_item_sonarr:
                _handle_automatic_import(item_data, queue_item_sonarr, 'sonarr')
                continue

            queue_item_radarr = arr_client.find_in_arr_queue_by_hash('radarr', torrent_hash)
            if queue_item_radarr:
                _handle_automatic_import(item_data, queue_item_radarr, 'radarr')
                continue

            _handle_manual_import(item_data)
        else:
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_rapatriation', 'Failed to download item from seedbox.')

    if transport:
        transport.close()
    current_app.logger.info("Staging Processor: Cycle finished.")
