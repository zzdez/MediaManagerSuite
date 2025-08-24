import os
from flask import current_app
from . import rtorrent_client, mapping_manager

def scan_and_map_torrents():
    current_app.logger.info("rTorrent Scanner: Starting scan for completed torrents.")
    try:
        completed_torrents = rtorrent_client.get_completed_torrents()
        if not completed_torrents:
            current_app.logger.info("rTorrent Scanner: No completed torrents found in rTorrent.")
            return

        torrent_map = mapping_manager.load_torrent_map()
        ignored_hashes = mapping_manager.load_ignored_hashes()

        final_statuses = {'completed_auto', 'completed_manual', 'processed_manual'}
        new_torrents_count = 0
        updated_torrents_count = 0

        for torrent in completed_torrents:
            torrent_hash = torrent.get('hash')
            release_name = torrent.get('name')

            if not torrent_hash or not release_name:
                continue

            if torrent_hash in ignored_hashes:
                continue

            existing_entry = torrent_map.get(torrent_hash)

            if existing_entry:
                # CAS A: Le torrent est déjà connu
                current_status = existing_entry.get('status')
                if current_status in final_statuses:
                    # Il a déjà un statut final, on ne touche à rien.
                    continue

                if current_status == 'pending_download':
                    # Le téléchargement vient de se terminer, on le met à jour.
                    download_path = torrent.get('base_path')
                    folder_name = os.path.basename(download_path) if download_path else release_name
                    mapping_manager.add_or_update_torrent_in_map(
                        release_name, torrent_hash, 'pending_staging',
                        seedbox_download_path=download_path, folder_name=folder_name
                    )
                    current_app.logger.info(f"rTorrent Scanner: Torrent '{release_name}' is now complete. Marked as 'pending_staging'.")
                    updated_torrents_count += 1
            else:
                # CAS B: Le torrent est nouveau pour nous (ajout automatique par *Arr)
                download_path = torrent.get('base_path')
                folder_name = os.path.basename(download_path) if download_path else release_name
                mapping_manager.add_or_update_torrent_in_map(
                    release_name, torrent_hash, 'pending_staging',
                    seedbox_download_path=download_path, folder_name=folder_name
                )
                new_torrents_count += 1

        if new_torrents_count > 0:
            current_app.logger.info(f"rTorrent Scanner: Added {new_torrents_count} new completed torrents to the map.")
        if updated_torrents_count > 0:
            current_app.logger.info(f"rTorrent Scanner: Updated {updated_torrents_count} existing torrents to 'pending_staging'.")

    except Exception as e:
        current_app.logger.error(f"rTorrent Scanner Error: {e}", exc_info=True)
