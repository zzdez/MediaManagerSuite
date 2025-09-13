import json
import os
from datetime import datetime, timedelta
from filelock import FileLock
from flask import current_app

class SimpleCache:
    def __init__(self, cache_name, cache_dir=None, default_lifetime_hours=6):
        if cache_dir is None:
            # Déplacer l'accès à current_app ici
            cache_dir = current_app.config.get('INSTANCE_PATH', os.path.join(os.getcwd(), 'instance'))

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
CACHE_DURATION_DAYS = 30 # Garder les résultats en cache pendant 30 jours

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
        # Use current_app.logger for consistency in Flask apps
        current_app.logger.error(f"ERROR: Could not save JSON file at {file_path}: {e}")

def _load_cache():
    return _load_json_file(CACHE_FILE)

def _save_cache(cache_data):
    _save_json_file(CACHE_FILE, cache_data)

# --- Pending Lock Functions ---

def add_pending_lock(media_id, video_id):
    """Ajoute un verrou en attente pour un média non encore dans Plex."""
    pending_locks = _load_json_file(PENDING_LOCKS_FILE)
    pending_locks[str(media_id)] = {'video_id': video_id, 'timestamp': datetime.now().isoformat()}
    _save_json_file(PENDING_LOCKS_FILE, pending_locks)
    current_app.logger.info(f"Pending lock added for media ID {media_id} with video ID {video_id}.")

def get_pending_lock(media_id):
    """Récupère un verrou en attente."""
    pending_locks = _load_json_file(PENDING_LOCKS_FILE)
    return pending_locks.get(str(media_id))

def remove_pending_lock(media_id):
    """Supprime un verrou en attente une fois qu'il a été traité."""
    pending_locks = _load_json_file(PENDING_LOCKS_FILE)
    if str(media_id) in pending_locks:
        del pending_locks[str(media_id)]
        _save_json_file(PENDING_LOCKS_FILE, pending_locks)
        current_app.logger.info(f"Pending lock removed for media ID {media_id}.")
        return True
    return False

# --- Main Cache Functions ---

def get_from_cache(key):
    """
    Récupère une entrée du cache. Si elle est valide, retourne l'objet complet.
    Retourne None si l'entrée n'existe pas ou est expirée (sauf si elle est verrouillée).
    """
    cache = _load_cache()
    entry = cache.get(key)

    if not entry:
        current_app.logger.debug(f"Cache MISS for key '{key}'")
        return None

    if entry.get('is_locked'):
        current_app.logger.debug(f"Locked Cache HIT for key '{key}'")
        return entry

    timestamp = datetime.fromisoformat(entry['timestamp'])
    if datetime.now() - timestamp < timedelta(days=CACHE_DURATION_DAYS):
        current_app.logger.debug(f"Cache HIT for key '{key}'")
        return entry

    current_app.logger.debug(f"Expired Cache MISS for key '{key}'")
    del cache[key]
    _save_cache(cache)
    return None


def set_in_cache(key, results_list, is_locked=False, locked_video_id=None):
    """
    Crée ou met à jour une entrée dans le cache avec une structure de données unifiée.
    """
    cache = _load_cache()

    cache[key] = {
        'timestamp': datetime.now().isoformat(),
        'is_locked': is_locked,
        'locked_video_id': locked_video_id,
        'results': results_list
    }
    _save_cache(cache)


def lock_trailer_in_cache(key, video_id, title):
    """
    Verrouille une bande-annonce. Met à jour l'entrée de cache existante.
    """
    cache = _load_cache()
    entry = cache.get(key)

    if not entry:
        current_app.logger.error(f"Cannot lock trailer for '{title}'. Cache entry not found for key: {key}")
        return False

    entry['is_locked'] = True
    entry['locked_video_id'] = video_id

    results = entry.get('results', [])
    locked_item = next((item for item in results if item['videoId'] == video_id), None)
    if locked_item:
        results.remove(locked_item)
        results.insert(0, locked_item)
        entry['results'] = results
    else:
        current_app.logger.warning(f"Could not find videoId {video_id} in results to promote it to the top.")

    _save_cache(cache)
    current_app.logger.info(f"Trailer for '{title}' (ID: {video_id}) has been locked in cache.")
    return True


def unlock_trailer_in_cache(key):
    """
    Déverrouille une bande-annonce dans le cache.
    """
    cache = _load_cache()
    entry = cache.get(key)

    if not entry:
        current_app.logger.error(f"Cannot unlock trailer. Cache entry not found for key: {key}")
        return False

    entry['is_locked'] = False
    entry['locked_video_id'] = None

    _save_cache(cache)
    current_app.logger.info(f"Trailer lock has been removed for cache key: {key}")
    return True
