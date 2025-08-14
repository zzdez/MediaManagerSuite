# app/utils/staging_processor.py
import os
import stat
import shutil
import paramiko
import time
import re
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

def _apply_path_mapping(original_path):
    """Applies the remote path mapping from config if it exists."""
    mapping_str = current_app.config.get('SEEDBOX_SFTP_REMOTE_PATH_MAPPING')
    if mapping_str:
        parts = mapping_str.split(',')
        if len(parts) == 2:
            to_remove = parts[0].strip()
            to_add = parts[1].strip()
            if original_path.startswith(to_remove):
                # Replace only the first occurrence
                new_path = original_path.replace(to_remove, to_add, 1)
                current_app.logger.info(f"Path mapping applied: '{original_path}' -> '{new_path}'")
                return new_path
    return original_path

def _rapatriate_item(item, sftp_client, folder_name):
    release_name = item.get('release_name')
    original_remote_path = item.get('seedbox_download_path')
    remote_path = _apply_path_mapping(original_remote_path)

    # Le chemin local utilise maintenant le vrai nom de dossier
    raw_local_path = os.path.join(current_app.config['LOCAL_STAGING_PATH'], folder_name)
    local_path = os.path.normpath(raw_local_path)

    current_app.logger.info(f"Rapatriement de '{release_name}' (dossier: {folder_name}) depuis '{remote_path}' vers '{local_path}'")

    try:
        # On vérifie si le chemin distant est un dossier ou un fichier
        file_attr = sftp_client.stat(remote_path)
        is_directory = stat.S_ISDIR(file_attr.st_mode)

        if is_directory:
            # C'est un dossier, on télécharge récursivement
            current_app.logger.info(f"'{remote_path}' est un dossier. Téléchargement récursif.")
            os.makedirs(local_path, exist_ok=True)
            _get_r_recursive(sftp_client, remote_path, local_path)
            current_app.logger.info(f"Téléchargement du dossier '{remote_path}' réussi.")
        else:
            # C'est un fichier, on télécharge directement
            current_app.logger.info(f"'{remote_path}' est un fichier. Téléchargement direct.")
            # On s'assure que le dossier parent du fichier local existe
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            sftp_client.get(remote_path, local_path)
            current_app.logger.info(f"Téléchargement du fichier '{remote_path}' réussi.")

        return True

    except FileNotFoundError:
        current_app.logger.error(f"Le chemin distant '{remote_path}' n'existe pas.", exc_info=True)
        return False
    except Exception as e:
        current_app.logger.error(f"Échec du rapatriement pour '{remote_path}': {e}", exc_info=True)
        # Nettoyage si un dossier a été créé pour un téléchargement de dossier qui a échoué
        if 'is_directory' in locals() and is_directory and os.path.isdir(local_path) and not os.listdir(local_path):
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

def _handle_automatic_import(item, queue_item, arr_type, folder_name):
    """
    Handles the import process when the item is found in Sonarr/Radarr's queue.
    """
    torrent_hash = item['torrent_hash']
    release_name = item['release_name']
    current_app.logger.info(f"Handling automatic import for '{release_name}' (folder: {folder_name}) for {arr_type}.")

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
        mapping_manager.update_torrent_status_in_map(torrent_hash, f'completed_by_{arr_type}', f'Import délégué à {arr_type} et réussi.')
        current_app.logger.info("Attente de 15 secondes pour laisser le temps à l'import de se terminer...")
        time.sleep(15) # Ajoute une pause de 15 secondes
        _cleanup_staging(folder_name)
    else:
        current_app.logger.error(f"Failed to trigger {arr_type} import for '{release_name}'.")
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_auto_import', f'Failed to trigger import in {arr_type}.')

def _handle_manual_import(item, folder_name):
    """
    Gère un import manuel via MMS, en déplaçant les fichiers lui-même.
    """
    torrent_hash = item['torrent_hash']
    release_name = item['release_name']
    current_app.logger.info(f"Traitement manuel de '{release_name}' (dossier: {folder_name}).")

    source_path = os.path.normpath(os.path.join(current_app.config['LOCAL_STAGING_PATH'], folder_name))
    
    # 1. Déterminer le type et trouver le média dans *Arr pour obtenir le chemin de destination
    parsed_info = arr_client.parse_media_name(release_name)
    media_type = parsed_info.get('type')
    title_to_search = parsed_info.get('title')

    if not title_to_search:
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', "Le parseur n'a pas pu extraire de titre.")
        return

    target_id = None
    destination_base_path = None # Chemin racine de la série/film

    if media_type == 'tv':
        series_info = arr_client.find_sonarr_series_by_title(title_to_search)
        if series_info:
            target_id = series_info.get('id')
            destination_base_path = series_info.get('path')
    elif media_type == 'movie':
        movie_info = arr_client.find_radarr_movie_by_title(title_to_search)
        if movie_info:
            target_id = movie_info.get('id')
            destination_base_path = movie_info.get('path')
    
    if not target_id or not destination_base_path:
        error_msg = f"Média '{title_to_search}' non trouvé dans {media_type}."
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', error_msg)
        return

    # 2. Logique de Déplacement Robuste (avec gestion des sous-dossiers)
    video_extensions = ('.mkv', '.mp4', '.avi', '.mov')
    files_moved_count = 0
    
    for dirpath, _, filenames in os.walk(source_path):
        for filename in filenames:
            if filename.lower().endswith(video_extensions):
                source_file = os.path.join(dirpath, filename)
                
                # Pour les séries, on tente de créer un dossier de saison
                final_destination_folder = os.path.normpath(destination_base_path)
                if media_type == 'tv':
                    # Essaye de deviner la saison depuis le nom du fichier ou du dossier parent
                    season_match = re.search(r'[._-][sS](\d{1,2})', source_file)
                    if season_match:
                        season_num = int(season_match.group(1))
                        final_destination_folder = os.path.join(destination_base_path, f'Season {season_num:02d}')
                
                os.makedirs(final_destination_folder, exist_ok=True)
                destination_file = os.path.join(final_destination_folder, filename)
                
                try:
                    shutil.move(source_file, destination_file)
                    current_app.logger.info(f"Fichier déplacé par MMS : {source_file} -> {destination_file}")
                    files_moved_count += 1
                except Exception as e_move:
                    current_app.logger.error(f"Erreur lors du déplacement de {source_file}: {e_move}")
                    # On ne lève pas d'exception pour continuer à traiter les autres fichiers
    
    if files_moved_count == 0:
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', "Aucun fichier vidéo trouvé à déplacer.")
        return

    # 3. Nettoyage du dossier de staging
    _cleanup_staging(folder_name)
    mapping_manager.update_torrent_status_in_map(torrent_hash, 'completed_manual', f'{files_moved_count} fichier(s) déplacé(s) manuellement.')
    
    # 4. Déclencher un Rescan pour que *Arr détecte les nouveaux fichiers
    current_app.logger.info(f"Déclenchement d'un Rescan dans {media_type} pour l'ID {target_id}.")
    if media_type == 'tv':
        arr_client.sonarr_post_command({'name': 'RescanSeries', 'seriesId': target_id})
    else:
        arr_client.radarr_post_command({'name': 'RescanMovie', 'movieId': target_id})

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
        folder_name = item_data.get('folder_name', item_data['release_name'])

        if _rapatriate_item(item_data, sftp_client, folder_name):
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'in_staging', 'Item successfully downloaded to staging.')

            queue_item_sonarr = arr_client.find_in_arr_queue_by_hash('sonarr', torrent_hash)
            if queue_item_sonarr:
                _handle_automatic_import(item_data, queue_item_sonarr, 'sonarr', folder_name)
                continue

            queue_item_radarr = arr_client.find_in_arr_queue_by_hash('radarr', torrent_hash)
            if queue_item_radarr:
                _handle_automatic_import(item_data, queue_item_radarr, 'radarr', folder_name)
                continue

            _handle_manual_import(item_data, folder_name)
        else:
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_rapatriation', 'Failed to download item from seedbox.')

    if transport:
        transport.close()
    current_app.logger.info("Staging Processor: Cycle finished.")
