# app/utils/sftp_scanner.py
from . import rtorrent_client
from . import mapping_manager
from flask import current_app

def scan_and_map_torrents():
    """
    Scan rTorrent for completed torrents and add them to the mapping manager
    with a 'pending_staging' status if they are not already known.
    """
    current_app.logger.info("SFTP/rTorrent Scanner: Starting scan for completed torrents.")

    try:
        # 1. Get completed torrents from rTorrent
        completed_torrents = rtorrent_client.get_completed_torrents()
        if not completed_torrents:
            current_app.logger.info("SFTP/rTorrent Scanner: No completed torrents found.")
            return

        # 2. Get torrents already known to our mapping
        known_hashes = mapping_manager.get_all_torrent_hashes()

        # 3. Process each torrent
        new_torrents_added = 0
        for torrent in completed_torrents:
            torrent_hash = torrent.get('hash')
            release_name = torrent.get('name')
            download_path = torrent.get('download_dir')

            if torrent_hash and release_name and download_path and torrent_hash not in known_hashes:
                # This is a new torrent, let's add it.
                mapping_manager.add_torrent(
                    release_name=release_name,
                    torrent_hash=torrent_hash,
                    seedbox_download_path=download_path,
                    status='pending_staging'
                )
                new_torrents_added += 1
                current_app.logger.info(f"SFTP/rTorrent Scanner: New torrent found and mapped: {release_name} (Hash: {torrent_hash})")
            elif not download_path:
                current_app.logger.warning(f"SFTP/rTorrent Scanner: Skipping torrent '{release_name}' because its download path is missing.")

        if new_torrents_added > 0:
            current_app.logger.info(f"SFTP/rTorrent Scanner: Added {new_torrents_added} new torrents to the map.")
        else:
            current_app.logger.info("SFTP/rTorrent Scanner: No new torrents to add.")

    except Exception as e:
        current_app.logger.error(f"SFTP/rTorrent Scanner: An error occurred during the scan: {e}", exc_info=True)
