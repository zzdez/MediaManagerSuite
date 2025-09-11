import json
import os
from datetime import datetime, timedelta

CACHE_FILE = os.path.join('instance', 'trailer_cache.json')
CACHE_DURATION_DAYS = 30 # Garder les résultats en cache pendant 30 jours

def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}

def _save_cache(cache_data):
    try:
        # Assurer que le répertoire 'instance' existe
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w') as f: # Correction du nom de la variable
            json.dump(cache_data, f, indent=4)
    except IOError:
        pass

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
