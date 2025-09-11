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
    cache = _load_cache()
    entry = cache.get(key)

    if not entry:
        print(f"DEBUG: Cache MISS for key '{key}'")
        return None

    # Si l'entrée est verrouillée, on la retourne immédiatement sans vérifier la date d'expiration.
    if entry.get('is_locked'):
        print(f"DEBUG: Locked Cache HIT for key '{key}'")
        # On reconstruit la donnée pour ne retourner que la vidéo verrouillée.
        locked_video_id = entry.get('locked_video_id')
        if locked_video_id:
            for video in entry.get('data', {}).get('results', []):
                if video['videoId'] == locked_video_id:
                    # On signale à l'appelant que ce résultat est verrouillé.
                    return {'results': [video], 'is_locked': True}
        # Si la vidéo verrouillée n'est pas trouvée, on traite comme un cache miss.
        print(f"WARN: Locked video ID {locked_video_id} not found in cache entry for key '{key}'")
        return None

    # Logique existante pour les entrées non verrouillées.
    timestamp = datetime.fromisoformat(entry['timestamp'])
    if datetime.now() - timestamp < timedelta(days=CACHE_DURATION_DAYS):
        print(f"DEBUG: Cache HIT for key '{key}'")
        return entry['data']

    print(f"DEBUG: Expired Cache MISS for key '{key}'")
    return None


def set_in_cache(key, data):
    cache = _load_cache()

    # Si une entrée existe déjà et est verrouillée, on ne la met pas à jour.
    if key in cache and cache[key].get('is_locked'):
        print(f"INFO: Cache entry for '{key}' is locked. Skipping update.")
        return

    cache[key] = {
        'timestamp': datetime.now().isoformat(),
        'data': data,
        'is_locked': False,
        'locked_video_id': None
    }
    _save_cache(cache)


def lock_trailer_in_cache(key, video_id, title):
    """
    Verrouille une bande-annonce spécifique dans le cache.
    """
    cache = _load_cache()
    entry = cache.get(key)

    if not entry:
        print(f"ERROR: Cannot lock trailer for '{title}'. Cache entry not found for key: {key}")
        return False

    entry['is_locked'] = True
    entry['locked_video_id'] = video_id
    # Optionnel: On pourrait supprimer les autres résultats pour nettoyer le cache
    # entry['data']['results'] = [video for video in entry['data']['results'] if video['videoId'] == video_id]

    _save_cache(cache)
    print(f"INFO: Trailer for '{title}' (ID: {video_id}) has been locked in cache.")
    return True
