# app/utils/plex_mapping_manager.py

import json
import os
from flask import current_app
from filelock import FileLock, Timeout

CONFIG_FILE_NAME = 'config.json'
MAPPING_KEY = 'PLEX_LIBRARY_MAPPINGS'

def _get_config_path():
    """Retourne le chemin complet du fichier de configuration dans le dossier 'instance'."""
    return os.path.join(current_app.instance_path, CONFIG_FILE_NAME)

def load_plex_mappings():
    """
    Charge la configuration du mapping des bibliothèques Plex depuis instance/config.json.
    Retourne la configuration si elle existe, sinon un dictionnaire vide.
    """
    config_path = _get_config_path()
    if not os.path.exists(config_path):
        return {}

    lock_path = config_path + ".lock"
    lock = FileLock(lock_path, timeout=5)

    try:
        with lock:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(MAPPING_KEY, {})
    except (json.JSONDecodeError, Timeout):
        # En cas d'erreur de parsing ou de timeout, retourne une structure vide
        return {}
    except Exception:
        # Pour toute autre erreur, retourne aussi une structure vide
        return {}

def save_plex_mappings(mappings_data):
    """
    Sauvegarde la configuration du mapping des bibliothèques Plex dans instance/config.json.
    'mappings_data' doit être un dictionnaire Python valide.
    """
    config_path = _get_config_path()
    lock_path = config_path + ".lock"
    lock = FileLock(lock_path, timeout=5)

    try:
        with lock:
            # Lire la configuration existante pour ne modifier que la clé PLEX_LIBRARY_MAPPINGS
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    try:
                        current_config = json.load(f)
                    except json.JSONDecodeError:
                        current_config = {} # Fichier corrompu, on l'écrase
            else:
                current_config = {}

            # Mettre à jour la clé spécifique
            current_config[MAPPING_KEY] = mappings_data

            # Écrire la configuration mise à jour
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(current_config, f, indent=4)
        return True, "Configuration sauvegardée avec succès."
    except Timeout:
        return False, "Impossible d'accéder au fichier de configuration (verrouillé)."
    except Exception as e:
        return False, f"Une erreur est survenue lors de la sauvegarde : {str(e)}"
