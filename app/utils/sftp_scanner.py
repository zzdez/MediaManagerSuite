import os
from flask import current_app
from . import rtorrent_client, mapping_manager, arr_client

def scan_and_map_torrents():
    logger = current_app.logger
    logger.info("rTorrent Scanner (Intelligent): Starting scan.")
    try:
        completed_torrents = rtorrent_client.get_completed_torrents()
        if not completed_torrents:
            return

        torrent_map = mapping_manager.load_torrent_map()
        ignored_hashes = mapping_manager.load_ignored_hashes()

        label_sonarr = current_app.config.get('RTORRENT_LABEL_SONARR', 'sonarr')
        label_radarr = current_app.config.get('RTORRENT_LABEL_RADARR', 'radarr')
        final_statuses = {'completed_auto', 'completed_manual', 'processed_manual'}

        for torrent in completed_torrents:
            torrent_hash = torrent.get('hash')
            release_name = torrent.get('name')

            if not all([torrent_hash, release_name]) or torrent_hash in ignored_hashes:
                continue

            if torrent_hash in torrent_map:
                # Le torrent est connu, on gère la fin de son téléchargement
                entry = torrent_map[torrent_hash]
                if entry.get('status') == 'pending_download':
                    logger.info(f"Scanner: Torrent connu '{release_name}' est complet. Passage à 'pending_staging'.")
                    mapping_manager.update_torrent_status_in_map(torrent_hash, 'pending_staging')
                continue # On ne traite pas plus les items déjà connus

            # Si on arrive ici, le torrent est NOUVEAU pour nous.
            logger.info(f"Scanner: Nouveau torrent terminé détecté: '{release_name}'.")
            torrent_label = torrent.get('label')

            if torrent_label == label_sonarr:
                series_info = arr_client.find_sonarr_series_by_release_name(release_name)
                if series_info and series_info.get('id'):
                    logger.info(f"Scanner: La release a été identifiée comme appartenant à la série '{series_info.get('title')}' (ID: {series_info.get('id')}).")
                    mapping_manager.add_or_update_torrent_in_map(
                        release_name=release_name,
                        torrent_hash=torrent_hash,
                        status='completed_auto', # On assume que Sonarr a déjà fait le travail
                        seedbox_download_path=torrent.get('base_path'),
                        folder_name=os.path.basename(torrent.get('base_path') or release_name),
                        app_type='sonarr',
                        target_id=series_info.get('id'),
                        label=torrent_label,
                        original_torrent_name=release_name
                    )
                else:
                    logger.warning(f"Scanner: Impossible de trouver une série correspondante pour '{release_name}'. L'item sera ignoré pour ce cycle.")

            elif torrent_label == label_radarr:
                # TODO: Implémenter la logique équivalente pour Radarr
                logger.warning(f"Scanner: La logique d'identification automatique pour Radarr n'est pas encore implémentée. '{release_name}' sera ignoré.")

            else:
                logger.warning(f"Scanner: Le torrent '{release_name}' a un label inconnu ('{torrent_label}') et n'est pas dans le map. Il sera ignoré.")

    except Exception as e:
        logger.error(f"rTorrent Scanner Error: {e}", exc_info=True)
