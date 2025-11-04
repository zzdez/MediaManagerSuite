import json
import os
import logging
from filelock import FileLock, Timeout
from flask import current_app

# Logger pour ce module
logger = logging.getLogger(__name__)

def _get_config_path():
    """Retourne le chemin du fichier de configuration du mapping."""
    # Le fichier de config général est déjà géré par config_manager.py
    # Pour le mapping, nous utilisons un fichier dédié pour plus de clarté.
    return os.path.join(current_app.instance_path, 'plex_mappings.json')

def get_plex_mappings():
    """
    Charge la configuration du mapping depuis le fichier JSON.
    Utilise un verrou pour éviter les lectures concurrentes corrompues.
    """
    config_path = _get_config_path()
    lock_path = config_path + ".lock"
    lock = FileLock(lock_path, timeout=5)

    try:
        with lock:
            if not os.path.exists(config_path):
                return {}  # Si le fichier n'existe pas, retourne une config vide
            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    return {}
                return json.loads(content)
    except Timeout:
        logger.error(f"Impossible d'acquérir le verrou pour lire {config_path} dans le temps imparti.")
        raise
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la lecture de {config_path}: {e}")
        raise

def save_plex_mappings(data):
    """
    Sauvegarde la configuration du mapping dans le fichier JSON.
    Utilise un verrou pour éviter les écritures concurrentes.
    """
    config_path = _get_config_path()
    lock_path = config_path + ".lock"
    lock = FileLock(lock_path, timeout=5)

    try:
        with lock:
            # S'assurer que le répertoire 'instance' existe
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logger.info(f"Configuration du mapping Plex sauvegardée dans {config_path}")
    except Timeout:
        logger.error(f"Impossible d'acquérir le verrou pour sauvegarder {config_path}. Les données ne sont pas sauvegardées.")
        raise
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la sauvegarde de {config_path}: {e}")
        raise

if __name__ == '__main__':
    # Section pour des tests rapides en mode standalone
    # Nécessite de simuler le contexte de l'application Flask
    class MockApp:
        def __init__(self):
            self.instance_path = 'instance_test'

    # Simuler current_app
    current_app = MockApp()

    logging.basicConfig(level=logging.INFO)

    # Créer le répertoire de test s'il n'existe pas
    if not os.path.exists(current_app.instance_path):
        os.makedirs(current_app.instance_path)

    test_config_path = _get_config_path()

    # Nettoyer les fichiers de test précédents
    if os.path.exists(test_config_path):
        os.remove(test_config_path)
    if os.path.exists(test_config_path + ".lock"):
        os.remove(test_config_path + ".lock")

    logger.info("--- Début des tests pour plex_mapping_manager ---")

    # 1. Tester la lecture d'un fichier inexistant (devrait retourner un dictionnaire vide)
    logger.info("Test 1: Lecture d'une configuration inexistante.")
    mappings = get_plex_mappings()
    assert mappings == {}, f"Attendu: {{}}, Obtenu: {mappings}"
    logger.info("Test 1: Réussi.")

    # 2. Tester l'écriture d'une nouvelle configuration
    logger.info("Test 2: Sauvegarde d'une nouvelle configuration.")
    test_data = {
        "Plex Library - Films": [
            {
                "plex_path": "D:\\Films",
                "arr_root_folder": "D:\\media\\radarr\\Films",
                "arr_type": "radarr"
            }
        ],
        "Plex Library - Séries": [
            {
                "plex_path": "E:\\Series",
                "arr_root_folder": "/media/sonarr/series/",
                "arr_type": "sonarr"
            }
        ]
    }
    save_plex_mappings(test_data)
    assert os.path.exists(test_config_path), f"Le fichier {test_config_path} n'a pas été créé."
    logger.info("Test 2: Réussi.")

    # 3. Tester la lecture de la configuration sauvegardée
    logger.info("Test 3: Lecture de la configuration sauvegardée.")
    read_mappings = get_plex_mappings()
    assert read_mappings == test_data, f"Les données lues ne correspondent pas. Attendu: {test_data}, Obtenu: {read_mappings}"
    logger.info("Test 3: Réussi.")

    # Nettoyage final
    if os.path.exists(test_config_path):
        os.remove(test_config_path)
    if os.path.exists(current_app.instance_path):
        import shutil
        shutil.rmtree(current_app.instance_path)

    logger.info("--- Tous les tests pour plex_mapping_manager sont réussis ---")
