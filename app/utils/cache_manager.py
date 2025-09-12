# Fichier : app/utils/cache_manager.py
import json
import os
from datetime import datetime, timedelta
from filelock import FileLock
from flask import current_app

class SimpleCache:
    def __init__(self, cache_name, cache_dir=None, default_lifetime_hours=6):
        if cache_dir is None:
            cache_dir = current_app.config.get('INSTANCE_PATH', 'instance')

        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

        self.cache_path = os.path.join(cache_dir, f"{cache_name}.json")
        self.lock_path = f"{self.cache_path}.lock"
        self.lifetime = timedelta(hours=default_lifetime_hours)

    def _load_cache(self):
        if not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def get(self, key):
        data = self._load_cache()
        entry = data.get(str(key))

        if not entry:
            return None

        timestamp_str = entry.get('timestamp')
        if not timestamp_str:
            return None

        try:
            timestamp = datetime.fromisoformat(timestamp_str)
            if datetime.now() - timestamp > self.lifetime:
                # Cache entry has expired
                return None
            return entry.get('value')
        except ValueError:
            return None

    def set(self, key, value):
        with FileLock(self.lock_path, timeout=5):
            data = self._load_cache()
            data[str(key)] = {
                'value': value,
                'timestamp': datetime.now().isoformat()
            }
            try:
                with open(self.cache_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
            except IOError as e:
                current_app.logger.error(f"Failed to write to cache file {self.cache_path}: {e}")

# --- Trailer Cache Management ---

CACHE_FILE = os.path.join('instance', 'trailer_cache.json')
PENDING_LOCKS_FILE = os.path.join('instance', 'pending_trailer_locks.json')
CACHE_DURATION_DAYS = 30

def _load_json_file(file_path):
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def _save_json_file(file_path, data):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        current_app.logger.error(f"ERROR: Could not save JSON file at {file_path}: {e}")

def _load_cache():
    return _load_json_file(CACHE_FILE)

def _save_cache(cache_data):
    _save_json_file(CACHE_FILE, cache_data)

def get_from_cache(key):
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return None
    if entry.get('is_locked'):
        return entry
    timestamp = datetime.fromisoformat(entry['timestamp'])
    if datetime.now() - timestamp < timedelta(days=CACHE_DURATION_DAYS):
        return entry
    del cache[key]
    _save_cache(cache)
    return None

def set_in_cache(key, results_list, is_locked=False, locked_video_id=None):
    cache = _load_cache()
    cache[key] = {
        'timestamp': datetime.now().isoformat(),
        'is_locked': is_locked,
        'locked_video_id': locked_video_id,
        'results': results_list
    }
    _save_cache(cache)

def lock_trailer_in_cache(key, video_id, title):
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return False
    entry['is_locked'] = True
    entry['locked_video_id'] = video_id
    results = entry.get('results', [])
    locked_item = next((item for item in results if item['videoId'] == video_id), None)
    if locked_item:
        results.remove(locked_item)
        results.insert(0, locked_item)
        entry['results'] = results
    _save_cache(cache)
    return True

def unlock_trailer_in_cache(key):
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return False
    entry['is_locked'] = False
    entry['locked_video_id'] = None
    _save_cache(cache)
    return True

def add_pending_lock(media_id, video_id):
    pending_locks = _load_json_file(PENDING_LOCKS_FILE)
    pending_locks[str(media_id)] = {'video_id': video_id, 'timestamp': datetime.now().isoformat()}
    _save_json_file(PENDING_LOCKS_FILE, pending_locks)

def get_pending_lock(media_id):
    pending_locks = _load_json_file(PENDING_LOCKS_FILE)
    return pending_locks.get(str(media_id))

def remove_pending_lock(media_id):
    pending_locks = _load_json_file(PENDING_LOCKS_FILE)
    if str(media_id) in pending_locks:
        del pending_locks[str(media_id)]
        _save_json_file(PENDING_LOCKS_FILE, pending_locks)
        return True
    return False
