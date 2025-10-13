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
