import os
import json
from datetime import datetime
from flask import current_app

# Nom du fichier pour stocker les associations en attente
# Ce fichier sera à la racine du projet
PENDING_ASSOCIATIONS_FILE = 'pending_torrents_map.json'

def get_pending_associations_filepath():
    """Retourne le chemin absolu du fichier des associations en attente."""
    return PENDING_ASSOCIATIONS_FILE

def _load_associations():
    """Charge les associations depuis le fichier JSON."""
    filepath = get_pending_associations_filepath()
    logger = None
    try:
        logger = current_app.logger
    except RuntimeError:
        pass # logger remains None

    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                return {}
            return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        if logger:
            logger.error(f"Erreur lors du chargement du fichier d'associations {filepath}: {e}. Le fichier sera traité comme vide/malformé.")
        else:
            print(f"ERROR: Erreur lors du chargement du fichier d'associations {filepath}: {e}. Le fichier sera traité comme vide/malformé.")
        return {}

def _save_associations(associations):
    """Sauvegarde les associations dans le fichier JSON."""
    filepath = get_pending_associations_filepath()
    logger = None
    try:
        logger = current_app.logger
    except RuntimeError:
        pass

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(associations, f, indent=4)
        return True
    except IOError as e:
        if logger:
            logger.error(f"Erreur lors de la sauvegarde du fichier d'associations {filepath}: {e}")
        else:
            print(f"ERROR: Erreur lors de la sauvegarde du fichier d'associations {filepath}: {e}")
        return False

def add_pending_association(release_name, app_type, target_id, label, torrent_hash=None):
    """
    Ajoute ou met à jour une association en attente en utilisant release_name comme clé.
    """
    logger = None
    try:
        logger = current_app.logger
    except RuntimeError:
        pass
        
    if logger:
        logger.debug(f"Ajout/Mise à jour de l'association pour release_name: {release_name}")

    associations = _load_associations()

    associations[release_name] = {
        'torrent_hash': torrent_hash,
        'app_type': app_type,
        'target_id': target_id,
        'label': label,
        'added_timestamp': datetime.utcnow().isoformat()
    }

    if _save_associations(associations):
        if logger:
            logger.info(f"Association pour '{release_name}' sauvegardée.")
        return True
    else:
        if logger:
            logger.error(f"Échec de la sauvegarde de l'association pour '{release_name}'.")
        return False

def get_pending_association(release_name):
    """Récupère une association en attente par son release_name."""
    logger = None
    try:
        logger = current_app.logger
    except RuntimeError:
        pass

    associations = _load_associations()
    association = associations.get(release_name)
    
    if logger:
        if association:
            logger.debug(f"Association trouvée pour release_name '{release_name}': {association}")
        else:
            logger.debug(f"Aucune association trouvée pour release_name '{release_name}'.")
    return association

def remove_pending_association(release_name):
    """Supprime une association en attente par son release_name."""
    logger = None
    try:
        logger = current_app.logger
    except RuntimeError:
        pass
        
    associations = _load_associations()

    if release_name in associations:
        del associations[release_name]
        if _save_associations(associations):
            if logger:
                logger.info(f"Association pour '{release_name}' supprimée.")
            return True
        else:
            if logger:
                logger.error(f"Échec de la sauvegarde après suppression de l'association pour '{release_name}'.")
            return False
    
    if logger:
        logger.debug(f"Tentative de suppression d'une association non existante pour release_name '{release_name}'.")
    return False

def get_all_pending_associations():
    """Récupère toutes les associations en attente."""
    logger = None
    try:
        logger = current_app.logger
    except RuntimeError:
        pass
        
    if logger:
        logger.debug("Chargement de toutes les associations en attente.")
    return _load_associations()

# Exemple d'utilisation (peut être décommenté pour des tests directs)
if __name__ == '__main__':
    # Pour les tests hors contexte Flask, current_app.logger ne sera pas disponible.
    # Les fonctions utilisent maintenant try-except pour current_app.logger.
    # Un logger basique est utilisé pour la sortie des tests eux-mêmes.
    import logging
    logging.basicConfig(level=logging.INFO) # Change to INFO to reduce noise, DEBUG for more details
    test_logger = logging.getLogger(__name__)


    test_logger.info("Test du gestionnaire d'associations en attente...")
    filepath = get_pending_associations_filepath()
    test_logger.info(f"Utilisation du fichier: {os.path.abspath(filepath)}")

    # Nettoyer le fichier de test s'il existe
    if os.path.exists(PENDING_ASSOCIATIONS_FILE):
        os.remove(PENDING_ASSOCIATIONS_FILE)

    # Test 1: Ajout d'une nouvelle association
    test_logger.info("\nTest 1: Ajout de 'Release.Name.One'")
    assert add_pending_association('Release.Name.One', 'sonarr', 'series_id_123', 'tv-sonarr', 'hash123xyz') == True
    assoc = get_pending_association('Release.Name.One')
    assert assoc and assoc['app_type'] == 'sonarr' and assoc['target_id'] == 'series_id_123'
    test_logger.info("Association 'Release.Name.One' ajoutée et vérifiée.")

    # Test 2: Ajout d'une autre association
    test_logger.info("\nTest 2: Ajout de 'Release.Name.Two'")
    assert add_pending_association('Release.Name.Two', 'radarr', 456, 'movies-radarr', torrent_hash='hash456abc') == True
    assoc2 = get_pending_association('Release.Name.Two')
    assert assoc2 and assoc2['app_type'] == 'radarr' and assoc2['target_id'] == 456
    test_logger.info("Association 'Release.Name.Two' ajoutée et vérifiée.")

    # Test 3: Récupération de toutes les associations
    test_logger.info("\nTest 3: Récupération de toutes les associations")
    all_assocs = get_all_pending_associations()
    assert len(all_assocs) == 2
    assert 'Release.Name.One' in all_assocs and 'Release.Name.Two' in all_assocs
    test_logger.info(f"Toutes les associations récupérées: {all_assocs}")

    # Test 4: Mise à jour d'une association existante (nouvel ajout avec même clé)
    test_logger.info("\nTest 4: Mise à jour de 'Release.Name.One'")
    assert add_pending_association('Release.Name.One', 'sonarr', 'series_id_789', 'tv-sonarr-updated', 'hash123xyz-updated') == True
    updated_assoc = get_pending_association('Release.Name.One')
    assert updated_assoc and updated_assoc['target_id'] == 'series_id_789' and updated_assoc['label'] == 'tv-sonarr-updated'
    assert updated_assoc['torrent_hash'] == 'hash123xyz-updated'
    test_logger.info("Association 'Release.Name.One' mise à jour et vérifiée.")
    assert len(get_all_pending_associations()) == 2

    # Test 5: Suppression d'une association
    test_logger.info("\nTest 5: Suppression de 'Release.Name.One'")
    assert remove_pending_association('Release.Name.One') == True
    assert get_pending_association('Release.Name.One') is None
    assert len(get_all_pending_associations()) == 1
    test_logger.info("Association 'Release.Name.One' supprimée et vérifiée.")

    # Test 6: Tentative de suppression d'une association non existante
    test_logger.info("\nTest 6: Suppression de 'Non.Existent.Release'")
    assert remove_pending_association('Non.Existent.Release') == False
    test_logger.info("Tentative de suppression de 'Non.Existent.Release' gérée.")

    # Test 7: Gestion d'un fichier JSON malformé ou vide
    test_logger.info("\nTest 7: Gestion fichier malformé/vide")
    # Simuler un fichier malformé
    with open(PENDING_ASSOCIATIONS_FILE, 'w') as f:
        f.write("ceci n'est pas du json")
    malformed_assocs = _load_associations() # Appelle _load_associations directement pour tester ce cas
    assert malformed_assocs == {}
    test_logger.info("Fichier malformé géré, retourne un dict vide.")
    
    # S'assurer que add_pending_association peut écraser un fichier malformé
    test_logger.info("Test 7b: add_pending_association sur un fichier malformé")
    assert add_pending_association('Release.Name.Three', 'sonarr', 'series_id_101', 'tv-sonarr', 'hash789') == True
    assoc3 = get_pending_association('Release.Name.Three')
    assert assoc3 and assoc3['app_type'] == 'sonarr'
    test_logger.info("add_pending_association a écrasé le fichier malformé et a fonctionné.")
    
    # Simuler un fichier vide
    with open(PENDING_ASSOCIATIONS_FILE, 'w') as f:
        f.write("") 
    empty_file_assocs = _load_associations() # Appelle _load_associations directement
    assert empty_file_assocs == {}
    test_logger.info("Fichier vide géré, retourne un dict vide.")

    # S'assurer que add_pending_association peut utiliser un fichier vide
    test_logger.info("Test 7c: add_pending_association sur un fichier vide")
    assert add_pending_association('Release.Name.Four', 'radarr', 999, 'movies-radarr', 'hash000') == True
    assoc4 = get_pending_association('Release.Name.Four')
    assert assoc4 and assoc4['app_type'] == 'radarr'
    test_logger.info("add_pending_association a utilisé le fichier vide et a fonctionné.")


    # Nettoyer après les tests
    if os.path.exists(PENDING_ASSOCIATIONS_FILE):
        os.remove(PENDING_ASSOCIATIONS_FILE)
    test_logger.info(f"\nFichier de test '{PENDING_ASSOCIATIONS_FILE}' nettoyé.")
    test_logger.info("\nTous les tests unitaires simples sont passés.")
