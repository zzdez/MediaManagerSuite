from flask import current_app
from . import rtorrent_client, mapping_manager

def scan_and_map_torrents():
    current_app.logger.info("rTorrent Scanner: Starting scan for completed torrents.")
    try:
        completed_torrents = rtorrent_client.get_completed_torrents()
        known_hashes = mapping_manager.get_all_torrent_hashes()
        new_torrents_added = 0

        for torrent in completed_torrents:
            torrent_hash = torrent.get('hash')
            release_name = torrent.get('name')
            download_path = torrent.get('base_path')

            if torrent_hash and release_name and download_path and torrent_hash not in known_hashes:
                mapping_manager.add_or_update_torrent_in_map(
                    torrent_hash=torrent_hash,
                    release_name=release_name,
                    app_type='unknown',
                    target_id='unknown', # Cannot be None due to the check in the function
                    label='unknown',
                    seedbox_download_path=download_path,
                    initial_status='pending_staging'
                )
                new_torrents_added += 1
                current_app.logger.info(f"rTorrent Scanner: New torrent mapped: {release_name}")
        current_app.logger.info(f"rTorrent Scanner: Added {new_torrents_added} new torrents to the map.")
    except Exception as e:
        current_app.logger.error(f"rTorrent Scanner Error: {e}", exc_info=True)
