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
    if entry:
        timestamp = datetime.fromisoformat(entry['timestamp'])
        if datetime.now() - timestamp < timedelta(days=CACHE_DURATION_DAYS):
            print(f"DEBUG: Cache HIT for key '{key}'")
            return entry['data']
    print(f"DEBUG: Cache MISS for key '{key}'")
    return None

def set_in_cache(key, data):
    cache = _load_cache()
    cache[key] = {
        'timestamp': datetime.now().isoformat(),
        'data': data
    }
    _save_cache(cache)
