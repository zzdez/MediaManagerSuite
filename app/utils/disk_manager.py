import logging
import time
from app.utils import arr_client

logger = logging.getLogger(__name__)

class DiskManager:
    _cache = None
    _cache_time = 0
    _CACHE_DURATION = 300  # 5 minutes in seconds

    @classmethod
    def get_disk_usage(cls):
        """
        Retrieves aggregated disk usage statistics from Sonarr and Radarr.
        Uses caching to prevent excessive API calls.
        """
        current_time = time.time()
        if cls._cache and (current_time - cls._cache_time < cls._CACHE_DURATION):
            # logger.debug("DiskManager: Returning cached disk stats.")
            return cls._cache

        logger.info("DiskManager: Cache expired or empty. Fetching fresh disk stats.")

        # Initialize data structures
        disks = {}  # Key: mount_path, Value: dict

        # Helper to process disk space
        def process_disk_space(source_name, fetch_func):
            try:
                data = fetch_func()
                if not data:
                    return
                for item in data:
                    path = item.get('path')
                    if not path:
                        continue

                    # Normalize path (remove trailing slash for consistency, unless it's root like D:\ or /)
                    # Actually, keeping it as returned is usually safer for matching,
                    # but we need consistent keys.
                    # On Windows, APIs usually return 'C:\\'.
                    norm_path = path

                    if norm_path not in disks:
                        disks[norm_path] = {
                            'path': path,
                            'label': item.get('label', ''),
                            'free': item.get('freeSpace', 0),
                            'total': item.get('totalSpace', 0),
                            'sonarr_folders': [],
                            'radarr_folders': [],
                            'sources': set()
                        }
                    disks[norm_path]['sources'].add(source_name)
            except Exception as e:
                logger.error(f"DiskManager: Error fetching disk space from {source_name}: {e}")

        # Helper to process root folders
        def process_root_folders(source_name, fetch_func, folder_list_key):
            try:
                folders = fetch_func()
                if not folders:
                    return

                for folder in folders:
                    folder_path = folder.get('path')
                    if not folder_path:
                        continue

                    # Find which disk this folder belongs to
                    # We match the longest matching disk path
                    best_match_disk = None
                    max_len = -1

                    for disk_path, disk_data in disks.items():
                        # Simple string startswith check.
                        # Case insensitive for Windows? Usually APIs return consistent casing.
                        # Let's assume case-insensitive for robustness if on Windows.
                        if folder_path.lower().startswith(disk_path.lower()):
                            if len(disk_path) > max_len:
                                max_len = len(disk_path)
                                best_match_disk = disk_data

                    if best_match_disk:
                        best_match_disk[folder_list_key].append(folder_path)
            except Exception as e:
                logger.error(f"DiskManager: Error fetching root folders from {source_name}: {e}")

        # 1. Fetch Disk Space
        process_disk_space('Sonarr', arr_client.get_sonarr_diskspace)
        process_disk_space('Radarr', arr_client.get_radarr_diskspace)

        # 2. Fetch Root Folders to map them
        process_root_folders('Sonarr', arr_client.get_sonarr_root_folders, 'sonarr_folders')
        process_root_folders('Radarr', arr_client.get_radarr_root_folders, 'radarr_folders')

        # 3. Format and Filter
        results = []
        for path, data in disks.items():
            # Filter: Only keep disks that have at least one root folder associated
            if not data['sonarr_folders'] and not data['radarr_folders']:
                continue

            total = data['total']
            free = data['free']
            used = total - free
            percent = (used / total * 100) if total > 0 else 0

            # Format label: Use 'label' if available, else path
            # For Windows, path is usually 'D:\', label might be Volume Name
            display_name = data['path']
            if data['label']:
                display_name = f"{data['path']} ({data['label']})"

            results.append({
                'path': data['path'],
                'display_name': display_name,
                'total_fmt': arr_client._format_bytes(total),
                'free_fmt': arr_client._format_bytes(free),
                'percent_used': round(percent, 1),
                'sonarr_folders': sorted(data['sonarr_folders']),
                'radarr_folders': sorted(data['radarr_folders']),
                'css_class': 'bg-danger' if percent > 90 else ('bg-warning' if percent > 75 else 'bg-success')
            })

        # Sort results by path
        results.sort(key=lambda x: x['path'])

        cls._cache = results
        cls._cache_time = current_time
        logger.info(f"DiskManager: Updated cache with {len(results)} disks.")
        return results

    @classmethod
    def clear_cache(cls):
        cls._cache = None
        cls._cache_time = 0
