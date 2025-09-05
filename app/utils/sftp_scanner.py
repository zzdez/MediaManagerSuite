import os
from flask import current_app
from pathlib import Path
from . import rtorrent_client, mapping_manager, arr_client

def scan_and_map_torrents():
    logger = current_app.logger

    # --- Locking Mechanism ---
    lock_file = Path(current_app.instance_path) / 'sftp_scanner.lock'
    if lock_file.exists():
        logger.warning("SFTP scanner lock file exists. Another scan may be in progress. Exiting.")
        return

    try:
        # Create lock file
        lock_file.touch()
        logger.info("rTorrent Scanner (Intelligent): Starting scan.")
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

                # --- BLOC DE CODE À AJOUTER ICI ---
                # Si le chemin n'était pas connu (promesse), on le met à jour maintenant.
                if not entry.get('seedbox_download_path'):
                    # On récupère le chemin final et réel depuis rTorrent
                    final_path = torrent.get('base_path')
                    if final_path:
                        logger.info(f"Scanner: Promesse tenue. Mise à jour du chemin pour '{release_name}' avec '{final_path}'.")
                        # On met à jour l'entrée avec le chemin trouvé.
                        mapping_manager.add_or_update_torrent_in_map(
                            torrent_hash=torrent_hash,
                            # On réutilise les informations déjà présentes dans l'entrée
                            release_name=entry.get('release_name'),
                            status=entry.get('status'),
                            app_type=entry.get('app_type'),
                            target_id=entry.get('target_id'),
                            label=entry.get('label'),
                            original_torrent_name=entry.get('original_torrent_name'),
                            # Et on ajoute les nouvelles informations
                            seedbox_download_path=final_path,
                            folder_name=os.path.basename(final_path)
                        )
                        # On met à jour notre variable locale pour que la suite de la logique fonctionne
                        entry['seedbox_download_path'] = final_path
                    else:
                        # Si rTorrent ne donne pas encore de chemin, on attend le prochain cycle.
                        logger.warning(f"Scanner: Le torrent '{release_name}' est terminé mais son chemin final n'est pas encore disponible. On réessaiera.")
                        continue # On passe au torrent suivant
                # --- FIN DU BLOC DE CODE À AJOUTER ---

                # Le reste de la fonction continue comme avant...
                if entry.get('status') == 'pending_download':
                    logger.info(f"Scanner: Torrent connu '{release_name}' est complet. Passage à 'pending_staging'.")
                    mapping_manager.update_torrent_status_in_map(torrent_hash, 'pending_staging')
                continue

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
    finally:
        # --- Release Lock ---
        if lock_file.exists():
            lock_file.unlink()
            logger.info("SFTP scanner lock file released.")
