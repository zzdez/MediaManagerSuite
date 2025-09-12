import json
import os
from datetime import datetime, timedelta

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
        print(f"ERROR: Could not save JSON file at {file_path}: {e}")

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
    print(f"INFO: Pending lock added for media ID {media_id} with video ID {video_id}.")

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
        print(f"INFO: Pending lock removed for media ID {media_id}.")
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
        print(f"DEBUG: Cache MISS for key '{key}'")
        return None

    # Une entrée verrouillée n'expire jamais.
    if entry.get('is_locked'):
        print(f"DEBUG: Locked Cache HIT for key '{key}'")
        return entry

    # Vérifie l'expiration pour les entrées non verrouillées.
    timestamp = datetime.fromisoformat(entry['timestamp'])
    if datetime.now() - timestamp < timedelta(days=CACHE_DURATION_DAYS):
        print(f"DEBUG: Cache HIT for key '{key}'")
        return entry

    print(f"DEBUG: Expired Cache MISS for key '{key}'")
    del cache[key]
    _save_cache(cache)
    return None


def set_in_cache(key, results_list, is_locked=False, locked_video_id=None):
    """
    Crée ou met à jour une entrée dans le cache avec une structure de données unifiée.
    """
    cache = _load_cache()

    # La nouvelle structure est plate.
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
        print(f"ERROR: Cannot lock trailer for '{title}'. Cache entry not found for key: {key}")
        return False

    entry['is_locked'] = True
    entry['locked_video_id'] = video_id

    # Déplace la vidéo verrouillée en haut de la liste des résultats.
    results = entry.get('results', [])
    locked_item = next((item for item in results if item['videoId'] == video_id), None)
    if locked_item:
        results.remove(locked_item)
        results.insert(0, locked_item)
        entry['results'] = results
    else:
        print(f"WARN: Could not find videoId {video_id} in results to promote it to the top.")

    _save_cache(cache)
    print(f"INFO: Trailer for '{title}' (ID: {video_id}) has been locked in cache.")
    return True


def unlock_trailer_in_cache(key):
    """
    Déverrouille une bande-annonce dans le cache.
    """
    cache = _load_cache()
    entry = cache.get(key)

    if not entry:
        print(f"ERROR: Cannot unlock trailer. Cache entry not found for key: {key}")
        return False

    entry['is_locked'] = False
    entry['locked_video_id'] = None

    _save_cache(cache)
    print(f"INFO: Trailer lock has been removed for cache key: {key}")
    return True
