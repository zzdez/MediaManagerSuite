# app/seedbox_ui/torrent_map_manager.py
import json
import os
import logging
from filelock import FileLock, Timeout
from flask import current_app # current_app sera utilisé pour obtenir la config et le logger
from datetime import datetime

# Logger spécifique au module, sera configuré par Flask si disponible
module_logger = logging.getLogger(__name__)

def _get_map_file_path_and_logger():
    """
    Returns the configured path for the torrent map JSON file and the Flask app logger.
    Raises ValueError if the path is not configured.
    Ensures the directory for the map file exists.
    """
    try:
        # Utiliser le logger de l'application Flask
        logger = current_app.logger
        path = current_app.config.get('PENDING_TORRENTS_MAP_FILE')
        if not path:
            logger.error("PENDING_TORRENTS_MAP_FILE is not configured in Flask app.")
            raise ValueError("Torrent map file path not configured.")
    except RuntimeError: # Pas dans un contexte d'application Flask
        logger = module_logger # Utiliser le logger du module (pourrait nécessiter une config externe)
        # Pourrait tenter de lire une variable d'environnement ou un chemin par défaut ici si nécessaire
        # mais pour une app Flask, il est préférable que ce soit toujours configuré.
        logger.warning("Flask current_app not available. Logger might not be fully configured.")
        # Vous devrez définir un chemin par défaut ou lire une variable d'env si vous exécutez ceci hors Flask
        path = os.getenv('MMS_PENDING_TORRENTS_MAP_FILE_FALLBACK', 'instance/pending_torrents_map.json')
        logger.info(f"Using fallback map file path: {path}")

    map_dir = os.path.dirname(path)
    if map_dir and not os.path.exists(map_dir): # Vérifier si map_dir n'est pas une chaîne vide
        try:
            os.makedirs(map_dir)
            logger.info(f"Created directory for torrent map: {map_dir}")
        except OSError as e:
            logger.error(f"Error creating directory {map_dir}: {e}")
            raise
    return path, logger

def load_torrent_map():
    """Loads the torrent map from the JSON file with file locking."""
    map_file, logger = _get_map_file_path_and_logger()
    lock_file = map_file + ".lock"
    lock = FileLock(lock_file, timeout=10)

    try:
        with lock:
            if not os.path.exists(map_file):
                return {}
            with open(map_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip(): # Fichier vide ou seulement des espaces blancs
                    logger.info(f"Torrent map file {map_file} is empty. Returning empty map.")
                    return {}
                try:
                    data = json.loads(content)
                    if not isinstance(data, dict):
                        logger.warning(f"Content of {map_file} is not a dictionary. Returning empty map.")
                        return {}
                    return data
                except json.JSONDecodeError:
                    logger.error(f"Error decoding JSON from {map_file}. Returning empty map.")
                    return {}
    except Timeout:
        logger.error(f"Could not acquire lock for {map_file} within timeout period.")
        raise # Relancer pour que l'appelant puisse gérer
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading torrent map {map_file}: {e}")
        raise

def save_torrent_map(data):
    """Saves the torrent map to the JSON file with file locking."""
    map_file, logger = _get_map_file_path_and_logger()
    lock_file = map_file + ".lock"
    lock = FileLock(lock_file, timeout=10)

    try:
        with lock:
            with open(map_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logger.debug(f"Torrent map saved to {map_file}")
    except Timeout:
        logger.error(f"Could not acquire lock for {map_file} to save. Data not saved.")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred while saving torrent map to {map_file}: {e}")
        raise

def add_or_update_torrent_in_map(torrent_hash, release_name, app_type, target_id, label,
                                 seedbox_download_path, original_torrent_name="N/A",
                                 initial_status="pending_download_on_seedbox"):
    """
    Adds or updates a torrent's pre-association in the map.
    'release_name' is the name of the folder/file rTorrent will create,
                     and sftp_downloader will use (without .torrent extension).
    'seedbox_download_path' is the full path on the seedbox where rTorrent is told to download.
    """
    _, logger = _get_map_file_path_and_logger()

    if not all([torrent_hash, release_name, app_type, target_id, label, seedbox_download_path]):
        logger.error("Missing one or more required arguments for add_or_update_torrent_in_map.")
        return False

    # S'assurer que release_name n'a pas .torrent à la fin
    if release_name.lower().endswith(".torrent"):
        release_name = release_name[:-len(".torrent")]
        logger.debug(f"Removed .torrent extension from release_name, now: {release_name}")

    torrents = load_torrent_map()
    now_iso = datetime.utcnow().isoformat()

    if torrent_hash in torrents: # Update existing
        torrents[torrent_hash].update({
            "release_name": release_name,
            "app_type": app_type,
            "target_id": target_id,
            "label": label,
            "seedbox_download_path": seedbox_download_path,
            "original_torrent_name": original_torrent_name,
            # Ne pas écraser le statut s'il est déjà plus avancé, sauf si explicitement demandé
            # Pour l'instant, on met à jour les infos, et on ne touche au statut que s'il est "ancien"
            "status": torrents[torrent_hash].get("status", initial_status), # Conserve le statut si déjà présent
            "updated_at": now_iso
        })
        logger.info(f"Updated torrent {torrent_hash} ({release_name}) in map.")
    else: # Add new
        torrents[torrent_hash] = {
            "release_name": release_name,
            "app_type": app_type,
            "target_id": target_id,
            "label": label,
            "seedbox_download_path": seedbox_download_path,
            "original_torrent_name": original_torrent_name,
            "status": initial_status,
            "added_at": now_iso,
            "updated_at": now_iso
        }
        logger.info(f"Added new torrent {torrent_hash} ({release_name}) to map.")

    try:
        save_torrent_map(torrents)
        return True
    except Exception as e:
        logger.error(f"Failed to save torrent map after adding/updating {torrent_hash}: {e}")
        return False

def get_torrent_by_hash(torrent_hash):
    """Retrieves a torrent entry by its torrent_hash."""
    _, logger = _get_map_file_path_and_logger()
    torrents = load_torrent_map()
    association = torrents.get(torrent_hash)
    if association:
        logger.debug(f"Association found for torrent_hash '{torrent_hash}'.")
    else:
        logger.debug(f"No association found for torrent_hash '{torrent_hash}'.")
    return association

def find_torrent_by_release_name(item_name_in_staging):
    """
    Finds a torrent entry by its release_name.
    'item_name_in_staging' is the name of the folder/file as it appears in the local staging directory
    (which should match the 'release_name' stored in the map).
    Returns a tuple (torrent_hash, data_dict) or (None, None).
    """
    _, logger = _get_map_file_path_and_logger()
    torrents = load_torrent_map()

    # item_name_in_staging ne devrait pas avoir .torrent, mais au cas où, on s'assure
    if item_name_in_staging.lower().endswith(".torrent"):
        item_name_in_staging = item_name_in_staging[:-len(".torrent")]

    logger.debug(f"Searching for torrent by release_name: '{item_name_in_staging}'")
    for torrent_hash, data in torrents.items():
        # La 'release_name' stockée ne devrait pas non plus avoir .torrent
        stored_release_name = data.get("release_name", "")
        if stored_release_name == item_name_in_staging:
            logger.info(f"Found torrent_hash '{torrent_hash}' for release_name '{item_name_in_staging}'.")
            return torrent_hash, data
    logger.info(f"No torrent found for release_name '{item_name_in_staging}'.")
    return None, None

def update_torrent_status_in_map(torrent_hash, new_status, status_message=None):
    """Updates the status and optionally a status message of a torrent in the map."""
    _, logger = _get_map_file_path_and_logger()
    torrents = load_torrent_map()
    if torrent_hash in torrents:
        torrents[torrent_hash]["status"] = new_status
        torrents[torrent_hash]["updated_at"] = datetime.utcnow().isoformat()
        if status_message:
            torrents[torrent_hash]["status_message"] = status_message
        elif "status_message" in torrents[torrent_hash]: # Clear old message if new one not provided
            del torrents[torrent_hash]["status_message"]
        try:
            save_torrent_map(torrents)
            logger.info(f"Updated status for torrent {torrent_hash} to '{new_status}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to save torrent map after updating status for {torrent_hash}: {e}")
            return False
    else:
        logger.warning(f"Torrent {torrent_hash} not found in map for status update to '{new_status}'.")
        return False

def remove_torrent_from_map(torrent_hash):
    """Removes a torrent entry from the map."""
    _, logger = _get_map_file_path_and_logger()
    torrents = load_torrent_map()
    if torrent_hash in torrents:
        del torrents[torrent_hash]
        try:
            save_torrent_map(torrents)
            logger.info(f"Removed torrent {torrent_hash} from map.")
            return True
        except Exception as e:
            logger.error(f"Failed to save torrent map after removing {torrent_hash}: {e}")
            return False
    else:
        logger.warning(f"Torrent {torrent_hash} not found in map for removal.")
        return False

def get_all_torrents_in_map():
    """Retrieves all torrent entries from the map."""
    _, logger = _get_map_file_path_and_logger()
    logger.debug("Loading all torrents from map.")
    return load_torrent_map()

# Vous pouvez ajouter ici les tests de votre __main__ si vous voulez le tester en standalone,
# mais assurez-vous de configurer un logger basique et potentiellement de simuler current_app.config
# ou de vous appuyer sur le fallback getenv pour PENDING_TORRENTS_MAP_FILE.
if __name__ == '__main__':
    # Basic logger setup for standalone testing
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    test_logger = logging.getLogger("torrent_map_manager_standalone_tests")
    module_logger.addHandler(logging.StreamHandler()) # Pour voir les logs du module
    module_logger.setLevel(logging.DEBUG)

    # --- Mock Flask app context for testing ---
    class MockConfig:
        def __init__(self, map_file_path):
            self.PENDING_TORRENTS_MAP_FILE = map_file_path

    class MockApp:
        def __init__(self, map_file_path):
            self.config = MockConfig(map_file_path)
            self.logger = test_logger # Use the test logger

    # Simulate Flask's current_app (this is a bit hacky for standalone)
    # A better way for unit tests would be to use Flask's test client and app context
    original_current_app = None
    try:
        from flask import g
        if not hasattr(g, 'flask_app_for_test_map_manager'):
            g.flask_app_for_test_map_manager = MockApp('instance/test_pending_torrents_map.json')
        current_app_context_for_test = g.flask_app_for_test_map_manager
    except ImportError: # Flask not available
        current_app_context_for_test = MockApp('instance/test_pending_torrents_map.json')
        test_logger.warning("Flask 'g' not available. Mocking app context directly.")

    # Override current_app temporarily for tests
    _original_current_app_func = current_app # Store original
    def _mock_current_app():
        return current_app_context_for_test
    
    import builtins
    # This is tricky; direct assignment to flask.current_app isn't standard.
    # For simplicity in this standalone script, we'll rely on the try-except in _get_map_file_path_and_logger
    # and ensure 'instance/test_pending_torrents_map.json' exists or can be created.
    # The best practice is to test Flask-dependent code within a Flask test context.

    test_logger.info("Début des tests du torrent_map_manager.py...")
    test_map_file = 'instance/test_pending_torrents_map.json'
    os.makedirs('instance', exist_ok=True) # Ensure 'instance' dir exists for test file

    # --- Test Data ---
    hash1 = "HASH_ONE_111"
    release1 = "Test.Release.S01E01"
    orig_name1 = "Test.Release.S01E01.torrent"
    path1 = "/remote/path/Test.Release.S01E01"

    hash2 = "HASH_TWO_222"
    release2 = "Another.Movie.2024"
    orig_name2 = "Another.Movie.2024.torrent"
    path2 = "/remote/path/Another.Movie.2024"

    # Clean up test file before starting
    if os.path.exists(test_map_file):
        os.remove(test_map_file)

    # Test 1: Add new torrent
    test_logger.info("\nTest 1: Add torrent 1")
    assert add_or_update_torrent_in_map(hash1, release1, "sonarr", 123, "sonarr_label", path1, orig_name1, "staged") == True
    data_h1 = get_torrent_by_hash(hash1)
    assert data_h1 is not None
    assert data_h1["release_name"] == release1
    assert data_h1["status"] == "staged"

    # Test 2: Add another torrent (with .torrent in release_name to test stripping)
    test_logger.info("\nTest 2: Add torrent 2 (with .torrent in release name)")
    assert add_or_update_torrent_in_map(hash2, release2 + ".torrent", "radarr", 456, "radarr_label", path2, orig_name2) == True
    data_h2 = get_torrent_by_hash(hash2)
    assert data_h2 is not None
    assert data_h2["release_name"] == release2 # Should be stripped
    assert data_h2["status"] == "pending_download_on_seedbox" # Default initial status

    # Test 3: Find by release name
    test_logger.info("\nTest 3: Find torrent 1 by release name")
    found_hash, found_data = find_torrent_by_release_name(release1)
    assert found_hash == hash1
    assert found_data["target_id"] == 123

    test_logger.info("Test 3b: Find torrent 2 by release name (even if .torrent was in original add call)")
    found_hash_2, found_data_2 = find_torrent_by_release_name(release2)
    assert found_hash_2 == hash2
    assert found_data_2["app_type"] == "radarr"
    
    test_logger.info("Test 3c: Find non-existent release name")
    non_exist_hash, non_exist_data = find_torrent_by_release_name("Non.Existent.Release")
    assert non_exist_hash is None
    assert non_exist_data is None

    # Test 4: Update status
    test_logger.info("\nTest 4: Update status for torrent 1")
    assert update_torrent_status_in_map(hash1, "imported_successfully", "Imported by MMS.") == True
    data_h1_updated = get_torrent_by_hash(hash1)
    assert data_h1_updated["status"] == "imported_successfully"
    assert data_h1_updated["status_message"] == "Imported by MMS."

    # Test 5: Remove torrent
    test_logger.info("\nTest 5: Remove torrent 2")
    assert remove_torrent_from_map(hash2) == True
    assert get_torrent_by_hash(hash2) is None
    all_torrents = get_all_torrents_in_map()
    assert len(all_torrents) == 1
    assert hash1 in all_torrents

    # Test 6: Empty file handling
    test_logger.info("\nTest 6: Empty file handling")
    if os.path.exists(test_map_file): os.remove(test_map_file)
    with open(test_map_file, 'w') as f: f.write("") # Create empty file
    empty_map = load_torrent_map()
    assert empty_map == {}
    test_logger.info("Loading empty file returned empty dict.")

    # Test 7: Malformed file handling
    test_logger.info("\nTest 7: Malformed file handling")
    if os.path.exists(test_map_file): os.remove(test_map_file)
    with open(test_map_file, 'w') as f: f.write("{not_json:") # Create malformed file
    malformed_map = load_torrent_map()
    assert malformed_map == {}
    test_logger.info("Loading malformed file returned empty dict.")

    # Clean up
    if os.path.exists(test_map_file):
        os.remove(test_map_file)
    test_logger.info("\n--- Standalone tests for torrent_map_manager.py finished ---")