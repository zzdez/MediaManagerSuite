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
        transport.set_keepalive(30)
        transport.connect(username=sftp_user, password=sftp_password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        current_app.logger.info(f"Staging Processor: Successfully connected to SFTP server: {sftp_host}")
        return sftp, transport
    except paramiko.ssh_exception.AuthenticationException:
        current_app.logger.error(f"Staging Processor: SFTP authentication failed for {sftp_user}@{sftp_host}.")
        return None, None
    except Exception as e:
        current_app.logger.error(f"Staging Processor: SFTP connection failed for {sftp_user}@{sftp_host}:{sftp_port} - {type(e).__name__}: {e}")
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

    if not original_remote_path:
        current_app.logger.error(f"Échec du rapatriement pour '{release_name}': Le chemin 'seedbox_download_path' est manquant dans le mapping.")
        mapping_manager.update_torrent_status_in_map(item.get('torrent_hash'), 'error_missing_path', 'Chemin distant manquant dans le mapping.')
        return False

    remote_path = original_remote_path
    raw_local_path = os.path.join(current_app.config['LOCAL_STAGING_PATH'], folder_name)
    local_path = os.path.normpath(raw_local_path)

    current_app.logger.info(f"Rapatriement de '{release_name}' (dossier: {folder_name}) depuis '{remote_path}' vers '{local_path}'")

    try:
        # Définir un timeout pour les opérations SFTP (ex: 10 minutes pour les gros fichiers)
        sftp_client.get_channel().settimeout(600)

        current_app.logger.debug(f"SFTP_DEBUG: Tentative de sftp.stat sur '{remote_path}'")
        file_attr = sftp_client.stat(remote_path)
        current_app.logger.debug(f"SFTP_DEBUG: sftp.stat réussi.")
        is_directory = stat.S_ISDIR(file_attr.st_mode)

        if is_directory:
            current_app.logger.info(f"'{remote_path}' est un dossier. Téléchargement récursif.")
            os.makedirs(local_path, exist_ok=True)
            _get_r_recursive(sftp_client, remote_path, local_path)
            current_app.logger.info(f"Téléchargement du dossier '{remote_path}' réussi.")
        else:
            current_app.logger.info(f"'{remote_path}' est un fichier. Téléchargement direct.")
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            current_app.logger.debug(f"SFTP_DEBUG: Tentative de sftp.get sur '{remote_path}'")
            sftp_client.get(remote_path, local_path)
            current_app.logger.debug(f"SFTP_DEBUG: sftp.get réussi.")
            current_app.logger.info(f"Téléchargement du fichier '{remote_path}' réussi.")

        return True

    except FileNotFoundError:
        current_app.logger.error(f"Le chemin distant '{remote_path}' n'existe pas.", exc_info=True)
        return False
    except Exception as e:
        current_app.logger.error(f"Échec du rapatriement pour '{remote_path}': {type(e).__name__} - {e}", exc_info=True)
        return False

def _cleanup_staging(item_name):
    """
    Deletes the item from the local staging directory in a robust way.
    Includes a short delay to release file locks and ignores errors during deletion.
    """
    local_staging_path = current_app.config['LOCAL_STAGING_PATH']
    item_path = os.path.join(local_staging_path, item_name)
    current_app.logger.info(f"Lancement du nettoyage robuste pour : {item_path}")

    if not os.path.exists(item_path):
        current_app.logger.info(f"Le chemin '{item_path}' n'existe déjà plus. Nettoyage non requis.")
        return True

    # NOUVEAU: Ajout d'une courte pause pour laisser le temps au système de libérer les verrous
    time.sleep(1)

    try:
        if os.path.isdir(item_path):
            # MODIFIÉ: Utilisation de ignore_errors=True pour forcer la suppression
            shutil.rmtree(item_path, ignore_errors=True)
        elif os.path.isfile(item_path):
            # On encapsule l'os.remove dans un try/except pour le même effet que ignore_errors
            try:
                os.remove(item_path)
            except OSError as e:
                current_app.logger.warning(f"Impossible de supprimer le fichier '{item_path}' durant le nettoyage: {e}")
        
        # Vérification finale
        if not os.path.exists(item_path):
            current_app.logger.info(f"Nettoyage de '{item_path}' réussi.")
            return True
        else:
            current_app.logger.error(f"Échec du nettoyage. Le chemin '{item_path}' existe toujours.")
            return False

    except Exception as e:
        current_app.logger.error(f"Erreur inattendue lors du nettoyage de {item_path}: {e}", exc_info=True)
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
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'completed_auto', f'Import délégué à {arr_type} et réussi.')
        current_app.logger.info("Attente de 15 secondes pour laisser le temps à l'import de se terminer...")
        time.sleep(15) # Ajoute une pause de 15 secondes
        _cleanup_staging(folder_name)
    else:
        current_app.logger.error(f"Failed to trigger {arr_type} import for '{release_name}'.")
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_auto_import', f'Failed to trigger import in {arr_type}.')

def _handle_manual_import(item, folder_name):
    """
    Gère un import manuel via MMS. Gère les cas où l'item est un fichier unique ou un dossier.
    """
    current_app.logger.info(f"MAP_READ_DEBUG: Début du traitement manuel. Données lues du mapping : {item}")
    torrent_hash = item['torrent_hash']
    release_name = item['release_name']
    current_app.logger.info(f"Traitement manuel de '{release_name}' (dossier/fichier: {folder_name}).")

    source_path = os.path.normpath(os.path.join(current_app.config['LOCAL_STAGING_PATH'], folder_name))

    # 1. Trouver le média dans *Arr en utilisant l'ID unique
    target_id_from_map = item.get('target_id')
    media_type = 'tv' if item.get('app_type') == 'sonarr' else 'movie'
    media_info = None

    if not target_id_from_map:
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', "Aucun ID cible (TVDB/TMDb) trouvé dans le mapping.")
        return

    if media_type == 'tv':
        # On utilise la fonction qui cherche par l'ID interne de Sonarr
        media_info = arr_client.get_sonarr_series_by_id(target_id_from_map)
    elif media_type == 'movie':
        # On utilise la fonction qui cherche par l'ID interne de Radarr
        media_info = arr_client.get_radarr_movie_by_id(target_id_from_map)

    target_id = media_info.get('id') if media_info else None
    destination_base_path = media_info.get('path') if media_info else None

    if not target_id or not destination_base_path:
        error_msg = f"Média avec ID '{target_id_from_map}' non trouvé dans {media_type}."
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', error_msg)
        return

    # 2. Logique de déplacement robuste (Copier puis Supprimer)
    video_extensions = ('.mkv', '.mp4', '.avi', '.mov', '.wmv')
    files_to_copy = []

    # --- DÉBUT DE LA LOGIQUE CORRIGÉE ---
    if os.path.isdir(source_path):
        current_app.logger.info(f"'{source_path}' est un dossier. Recherche de fichiers vidéo à l'intérieur.")
        for dirpath, _, filenames in os.walk(source_path):
            for filename in filenames:
                if filename.lower().endswith(video_extensions):
                    files_to_copy.append(os.path.join(dirpath, filename))
    elif os.path.isfile(source_path):
        current_app.logger.info(f"'{source_path}' est un fichier. Vérification de l'extension.")
        if source_path.lower().endswith(video_extensions):
            files_to_copy.append(source_path)
    # --- FIN DE LA LOGIQUE CORRIGÉE ---

    if not files_to_copy:
        mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', "Aucun fichier vidéo trouvé à déplacer.")
        return

    current_app.logger.info(f"Phase 1: Copie de {len(files_to_copy)} fichier(s) vidéo.")
    for source_file in files_to_copy:
        filename = os.path.basename(source_file)
        final_destination_folder = os.path.normpath(destination_base_path)
        if media_type == 'tv':
            season_match = re.search(r'[._-][sS](\d{1,2})', source_file)
            if season_match:
                season_num = int(season_match.group(1))
                final_destination_folder = os.path.join(destination_base_path, f'Season {season_num:02d}')

        os.makedirs(final_destination_folder, exist_ok=True)
        destination_file = os.path.join(final_destination_folder, filename)

        try:
            current_app.logger.info(f"Copie de '{source_file}' vers '{destination_file}'...")
            shutil.copy2(source_file, destination_file)
            current_app.logger.info(f"Copie de '{filename}' réussie.")
        except (shutil.Error, IOError) as e_copy:
            current_app.logger.error(f"Erreur critique lors de la copie de {source_file}: {e_copy}. L'import manuel est interrompu.")
            mapping_manager.update_torrent_status_in_map(torrent_hash, 'error_manual_import', f"Erreur de copie de fichier: {e_copy}")
            return

    # 3. Nettoyage final du dossier/fichier de staging
        _cleanup_staging(folder_name)

        # --- DÉBUT DE LA LOGIQUE DE STATUT FINAL ---
        final_status = 'completed_manual'
        final_message = f"{len(files_to_copy)} fichier(s) déplacé(s) manuellement."

        # On vérifie le label pour déterminer si l'origine était automatique
        torrent_label = item.get('label', '')
        label_sonarr_auto = 'tv-sonarr'
        label_radarr_auto = 'radarr' # Supposition pour Radarr

        if item.get('app_type') == 'sonarr' and torrent_label == label_sonarr_auto:
            final_status = 'completed_auto'
            final_message = f"{len(files_to_copy)} fichier(s) importé(s) automatiquement via MMS."
        elif item.get('app_type') == 'radarr' and torrent_label == label_radarr_auto:
            final_status = 'completed_auto'
            final_message = f"{len(files_to_copy)} fichier(s) importé(s) automatiquement via MMS."

        mapping_manager.update_torrent_status_in_map(torrent_hash, final_status, final_message)
        # --- FIN DE LA LOGIQUE DE STATUT FINAL ---

        # 4. Déclencher un Rescan
        current_app.logger.info(f"Déclenchement d'un Rescan dans {media_type} pour l'ID {target_id}.")
        if media_type == 'tv':
            arr_client.sonarr_post_command({'name': 'RescanSeries', 'seriesId': target_id})
        else:
            arr_client.radarr_post_command({'name': 'RescanMovie', 'movieId': target_id})
def process_pending_staging_items():
    """ Main function for the staging processor with robust connection handling. """
    logger = current_app.logger
    logger.info("Staging Processor: Starting cycle.")

    all_torrents = mapping_manager.get_all_torrents_in_map()
    items_to_process = {h: d for h, d in all_torrents.items() if d.get('status') in ['pending_staging', 'in_staging']}

    if not items_to_process:
        logger.info("Staging Processor: No items pending staging or in staging.")
        return

    sftp_client, transport = None, None
    try:
        # On ne se connecte au SFTP que si c'est nécessaire
        needs_sftp = any(item.get('status') == 'pending_staging' for item in items_to_process.values())
        if needs_sftp:
            sftp_client, transport = _connect_sftp()
            if not sftp_client:
                logger.error("Staging Processor: Could not connect to SFTP. Aborting cycle for pending items.")
                for h, d in items_to_process.items():
                    if d.get('status') == 'pending_staging':
                        mapping_manager.update_torrent_status_in_map(h, 'error_sftp_connection', 'Could not connect to SFTP server.')
                return

        logger.info(f"Staging Processor: Found {len(items_to_process)} items to process.")

        for torrent_hash, item_data in items_to_process.items():
            item_data['torrent_hash'] = torrent_hash
            folder_name = item_data.get('folder_name', item_data['release_name'])
            current_status = item_data.get('status')

            # --- DÉBUT DE LA LOGIQUE D'AIGUILLAGE ---
            if current_status == 'pending_staging':
                logger.info(f"Item '{folder_name}' is pending_staging. Starting rapatriation.")
                if _rapatriate_item(item_data, sftp_client, folder_name):
                    mapping_manager.update_torrent_status_in_map(torrent_hash, 'in_staging', 'Item successfully downloaded to staging.')
                    # Le statut est maintenant 'in_staging', le traitement se fera à la suite
                else:
                    # _rapatriate_item gère déjà le statut d'erreur, on passe au suivant
                    continue
            # --- FIN DE LA LOGIQUE D'AIGUILLAGE ---

            # À ce stade, l'item est soit arrivé avec le statut 'in_staging',
            # soit il vient d'être rapatrié et son statut a été mis à jour.
            # On peut donc procéder au traitement manuel/automatique.

            queue_item_sonarr = arr_client.find_in_arr_queue_by_hash('sonarr', torrent_hash)
            if queue_item_sonarr:
                _handle_automatic_import(item_data, queue_item_sonarr, 'sonarr', folder_name)
                continue

            queue_item_radarr = arr_client.find_in_arr_queue_by_hash('radarr', torrent_hash)
            if queue_item_radarr:
                _handle_automatic_import(item_data, queue_item_radarr, 'radarr', folder_name)
                continue

            _handle_manual_import(item_data, folder_name)

    finally:
        if transport:
            logger.info("Staging Processor: Closing SFTP transport.")
            transport.close()
        logger.info("Staging Processor: Cycle finished.")
