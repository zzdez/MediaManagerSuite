import os
from flask import current_app
from . import rtorrent_client, mapping_manager

def scan_and_map_torrents():
    current_app.logger.info("rTorrent Scanner: Starting scan for completed torrents.")
    try:
        completed_torrents = rtorrent_client.get_completed_torrents()

        # On charge la map complète pour pouvoir la modifier
        torrent_map = mapping_manager.load_torrent_map()
        known_hashes = set(torrent_map.keys())
        ignored_hashes = mapping_manager.load_ignored_hashes()

        new_torrents_added = 0
        for torrent in completed_torrents:
            torrent_hash = torrent.get('hash')

            if torrent_hash in ignored_hashes:
                continue

            release_name = torrent.get('name')
            download_path = torrent.get('base_path')
            folder_name = os.path.basename(download_path) if download_path else release_name

            if torrent_hash in known_hashes:
                # CAS A: Le torrent est déjà connu (probablement un ajout manuel)
                if torrent_map[torrent_hash].get('status') == 'pending_download':
                    # On met à jour pour ajouter le folder_name et changer le statut
                    mapping_manager.add_or_update_torrent_in_map(
                        torrent_hash=torrent_hash,
                        release_name=release_name,
                        status='pending_staging',
                        seedbox_download_path=download_path,
                        folder_name=folder_name
                    )
                    current_app.logger.info(f"rTorrent Scanner: Torrent '{release_name}' is now complete. Marked as 'pending_staging' with folder_name '{folder_name}'.")
            else:
                # CAS B: Le torrent est nouveau (probablement un ajout automatique par *Arr)
                mapping_manager.add_or_update_torrent_in_map(
                    release_name=release_name,
                    torrent_hash=torrent_hash,
                    status='pending_staging',
                    seedbox_download_path=download_path,
                    folder_name=folder_name
                )
                new_torrents_added += 1

        if new_torrents_added > 0:
            current_app.logger.info(f"rTorrent Scanner: Added {new_torrents_added} new torrents to the map.")

    except Exception as e:
        current_app.logger.error(f"rTorrent Scanner Error: {e}", exc_info=True)
