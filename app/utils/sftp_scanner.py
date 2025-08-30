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
                entry = torrent_map[torrent_hash]

                # Si le chemin n'était pas connu (promesse), on le met à jour maintenant.
                if not entry.get('seedbox_download_path'):
                    new_path = torrent.get('base_path')
                    if new_path:
                        logger.info(f"Scanner: Mise à jour du chemin pour '{release_name}' avec '{new_path}'.")
                        # Mettre à jour l'entrée avec le chemin trouvé.
                        # On ne change pas le statut ici, la logique suivante s'en chargera.
                        mapping_manager.add_or_update_torrent_in_map(
                            release_name=entry.get('release_name', release_name),
                            torrent_hash=torrent_hash,
                            status=entry.get('status'),
                            seedbox_download_path=new_path,
                            folder_name=os.path.basename(new_path),
                            app_type=entry.get('app_type'),
                            target_id=entry.get('target_id'),
                            label=entry.get('label'),
                            original_torrent_name=entry.get('original_torrent_name')
                        )
                        # On met à jour l'objet local pour la suite de la logique dans cette boucle.
                        entry['seedbox_download_path'] = new_path
                    else:
                        logger.warning(f"Scanner: Le torrent '{release_name}' est terminé mais son chemin est toujours inconnu dans rTorrent. Ignoré pour ce cycle.")
                        continue

                # Le torrent est connu et son chemin est maintenant renseigné, on gère la fin de son téléchargement.
                if entry.get('status') == 'pending_download':
                    logger.info(f"Scanner: Torrent connu '{release_name}' est complet. Passage à 'pending_staging'.")
                    mapping_manager.update_torrent_status_in_map(torrent_hash, 'pending_staging')
                continue # On ne traite pas plus les items déjà connus

            # Si on arrive ici, le torrent est NOUVEAU pour nous.
            logger.info(f"Scanner: Nouveau torrent terminé détecté: '{release_name}'.")
            torrent_label = torrent.get('label')

            # On définit les labels automatiques que l'on s'attend à voir de la part de Sonarr/Radarr
            label_sonarr_auto = 'tv-sonarr'
            # Supposition pour Radarr, à ajuster si votre label automatique est différent
            label_radarr_auto = 'radarr' 

            if torrent_label in [label_sonarr, label_sonarr_auto]:
                series_info = arr_client.find_sonarr_series_by_release_name(release_name)
                if series_info and series_info.get('id'):
                    logger.info(f"Scanner: La release a été identifiée comme appartenant à la série '{series_info.get('title')}' (ID: {series_info.get('id')}).")
                    mapping_manager.add_or_update_torrent_in_map(
                        release_name=release_name,
                        torrent_hash=torrent_hash,
                        status='pending_staging', # <-- C'EST LA SEULE LIGNE MODIFIÉE
                        seedbox_download_path=torrent.get('base_path'),
                        folder_name=os.path.basename(torrent.get('base_path') or release_name),
                        app_type='sonarr',
                        target_id=series_info.get('id'),
                        label=torrent_label,
                        original_torrent_name=release_name
                    )
                else:
                    logger.warning(f"Scanner: Impossible de trouver une série correspondante pour '{release_name}'. L'item sera ignoré pour ce cycle.")

            elif torrent_label in [label_radarr, label_radarr_auto]:
                movie_info = arr_client.find_radarr_movie_by_release_name(release_name)
                if movie_info and movie_info.get('id'):
                    logger.info(f"Scanner: La release a été identifiée comme appartenant au film '{movie_info.get('title')}' (ID: {movie_info.get('id')}).")
                    mapping_manager.add_or_update_torrent_in_map(
                        release_name=release_name,
                        torrent_hash=torrent_hash,
                        status='pending_staging',
                        seedbox_download_path=torrent.get('base_path'),
                        folder_name=os.path.basename(torrent.get('base_path') or release_name),
                        app_type='radarr',
                        target_id=movie_info.get('id'),
                        label=torrent_label,
                        original_torrent_name=release_name
                    )
                else:
                    logger.warning(f"Scanner: Impossible de trouver un film correspondant pour '{release_name}'. L'item sera ignoré pour ce cycle.")

            else:
                logger.warning(f"Scanner: Le torrent '{release_name}' a un label inconnu ('{torrent_label}') et n'est pas dans le map. Il sera ignoré.")

    except Exception as e:
        logger.error(f"rTorrent Scanner Error: {e}", exc_info=True)
