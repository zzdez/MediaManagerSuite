import os
from flask import current_app
from . import rtorrent_client, mapping_manager, arr_client

def scan_and_map_torrents():
    logger = current_app.logger
    logger.info("rTorrent Scanner (Robust Path): Starting scan.")
    try:
        completed_torrents = rtorrent_client.get_completed_torrents()
        if not completed_torrents:
            return

        torrent_map = mapping_manager.load_torrent_map()
        ignored_hashes = mapping_manager.load_ignored_hashes()
        
        label_sonarr_manual = current_app.config.get('RTORRENT_LABEL_SONARR', 'sonarr')
        label_sonarr_auto = 'tv-sonarr'
        label_radarr_manual = current_app.config.get('RTORRENT_LABEL_RADARR', 'radarr')
        label_radarr_auto = 'radarr'

        for torrent in completed_torrents:
            torrent_hash = torrent.get('hash')
            release_name = torrent.get('name')

            if not all([torrent_hash, release_name]) or torrent_hash in ignored_hashes:
                continue

            if torrent_hash in torrent_map:
                entry = torrent_map[torrent_hash]
                if entry.get('status') == 'pending_download':
                    logger.info(f"Scanner: Manual torrent '{release_name}' is complete. Marking as 'pending_staging'.")
                    mapping_manager.update_torrent_status_in_map(torrent_hash, 'pending_staging')
                continue

            torrent_label = torrent.get('label')
            
            if torrent_label in [label_sonarr_manual, label_sonarr_auto]:
                series_info = arr_client.find_sonarr_series_by_release_name(release_name)
                if series_info and series_info.get('id'):
                    logger.info(f"Scanner: Identified '{release_name}' as '{series_info.get('title')}'.")
                    
                    # --- DÉBUT DE LA CORRECTION DE CHEMIN ---
                    finished_path_base = current_app.config.get('SEEDBOX_RTORRENT_FINISHED_SONARR_PATH')
                    if not finished_path_base:
                        logger.error("SEEDBOX_RTORRENT_FINISHED_SONARR_PATH is not configured. Cannot map auto-download.")
                        continue
                    
                    correct_download_path = str(Path(finished_path_base.rstrip('/')) / release_name).replace('\\', '/')
                    # --- FIN DE LA CORRECTION DE CHEMIN ---

                    mapping_manager.add_or_update_torrent_in_map(
                        release_name=release_name,
                        torrent_hash=torrent_hash,
                        status='pending_staging',
                        seedbox_download_path=correct_download_path, # Utilise le chemin corrigé
                        folder_name=release_name,
                        app_type='sonarr',
                        target_id=series_info.get('id'),
                        label=torrent_label
                    )
                else:
                    logger.warning(f"Scanner: Could not find a matching series for '{release_name}'. Ignoring.")

            elif torrent_label in [label_radarr_manual, label_radarr_auto]:
                movie_info = arr_client.find_radarr_movie_by_release_name(release_name)
                if movie_info and movie_info.get('id'):
                    logger.info(f"Scanner: Identified '{release_name}' as '{movie_info.get('title')}'.")

                    finished_path_base = current_app.config.get('SEEDBOX_RTORRENT_FINISHED_RADARR_PATH')
                    if not finished_path_base:
                        logger.error("SEEDBOX_RTORRENT_FINISHED_RADARR_PATH is not configured. Cannot map auto-download.")
                        continue

                    correct_download_path = str(Path(finished_path_base.rstrip('/')) / release_name).replace('\\', '/')

                    mapping_manager.add_or_update_torrent_in_map(
                        release_name=release_name,
                        torrent_hash=torrent_hash,
                        status='pending_staging',
                        seedbox_download_path=correct_download_path,
                        folder_name=release_name,
                        app_type='radarr',
                        target_id=movie_info.get('id'),
                        label=torrent_label
                    )
                else:
                    logger.warning(f"Scanner: Could not find a matching movie for '{release_name}'. Ignoring.")

    except Exception as e:
        logger.error(f"rTorrent Scanner Error: {e}", exc_info=True)
