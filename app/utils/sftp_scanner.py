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
            # --- DÉBUT DU BLOC DE DÉBOGAGE ---
            logger.info("="*50)
            logger.info(f"DEBUG SCANNER: Informations brutes de rTorrent pour le torrent : {torrent.get('name')}")
            logger.info(f"  - Hash: {torrent.get('hash')}")
            logger.info(f"  - Nom: {torrent.get('name')}")
            logger.info(f"  - Label: {torrent.get('label')}")
            logger.info(f"  - Chemin de base (base_path): {torrent.get('base_path')}")
            logger.info(f"  - Chemin du fichier (path): {torrent.get('path')}")
            logger.info(f"  - Est complet: {torrent.get('is_complete')}")
            logger.info(f"  - Personnalisé 1 (custom1): {torrent.get('custom1')}") # Ajout pour voir le label de ruTorrent
            logger.info("="*50)
            # --- FIN DU BLOC DE DÉBOGAGE ---

            torrent_hash = torrent.get('hash')
            release_name = torrent.get('name')

            if not all([torrent_hash, release_name]) or torrent_hash in ignored_hashes:
                continue

            if torrent_hash in torrent_map:
                entry = torrent_map[torrent_hash]
                current_status = entry.get('status')

                # Si le torrent est connu et en attente de téléchargement, il est maintenant prêt.
                if current_status == 'pending_download':
                    # C'est ici que l'on met à jour l'entrée avec le chemin final.
                    final_path = torrent.get('base_path')
                    if final_path:
                        logger.info(f"Scanner: Torrent pré-mappé '{release_name}' est complet. Mise à jour avec le chemin final et passage à 'pending_staging'.")
                        # On met à jour le chemin ET le statut en une seule fois.
                        mapping_manager.add_or_update_torrent_in_map(
                            release_name=entry.get('release_name', release_name),
                            torrent_hash=torrent_hash,
                            status='pending_staging', # <-- Passage au statut suivant
                            seedbox_download_path=final_path, # <-- Enregistrement du chemin CORRECT
                            folder_name=entry.get('folder_name', os.path.basename(final_path or release_name)),
                            app_type=entry.get('app_type'),
                            target_id=entry.get('target_id'),
                            label=entry.get('label'),
                            original_torrent_name=entry.get('original_torrent_name')
                        )
                    else:
                        logger.error(f"Scanner: Torrent '{release_name}' est complet mais rTorrent n'a pas fourni de 'base_path'. L'association ne peut pas être mise à jour.")

                # Si le statut est autre (ex: 'pending_staging', 'error_*'), on ne fait rien pour éviter les boucles.
                continue # On passe au torrent suivant.

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
