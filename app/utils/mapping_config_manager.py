# app/utils/mapping_config_manager.py

import json
import os
from filelock import FileLock
from flask import current_app

CONFIG_FILE = 'instance/mapping_config.json'
LOCK_FILE = 'instance/mapping_config.json.lock'

class MappingConfigManager:
    def __init__(self):
        self.config_path = CONFIG_FILE
        self.lock_path = LOCK_FILE
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """Crée le fichier de configuration avec une structure vide s'il n'existe pas."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        if not os.path.exists(self.config_path):
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump({'mappings': []}, f, indent=4)

    def get_mappings(self):
        """Charge et retourne les mappings depuis le fichier JSON."""
        with FileLock(self.lock_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # S'assurer que la clé 'mappings' existe
                    if 'mappings' not in data or not isinstance(data['mappings'], list):
                        return []
                    return data['mappings']
            except (json.JSONDecodeError, FileNotFoundError):
                # En cas de fichier corrompu ou manquant, retourner une structure vide
                return []

    def save_mappings(self, mappings_data):
        """Sauvegarde la liste complète des mappings dans le fichier JSON."""
        if not isinstance(mappings_data, list):
            raise ValueError("Les données de mapping doivent être une liste.")

        with FileLock(self.lock_path):
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump({'mappings': mappings_data}, f, indent=4)
        current_app.logger.info(f"{len(mappings_data)} règles de mapping sauvegardées avec succès.")

# Instance unique pour être utilisée dans toute l'application
mapping_config_manager = MappingConfigManager()
