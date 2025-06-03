import os
import json
from datetime import datetime
# from flask import current_app # Removed from here
import logging # Needed for standalone testing

# Nom du fichier pour stocker les associations en attente
PENDING_ASSOCIATIONS_FILE = 'pending_torrents_map.json'

def get_pending_associations_filepath():
    """Retourne le chemin absolu du fichier des associations en attente."""
    # En supposant que le script s'exécute depuis la racine du projet ou que le CWD est la racine.
    # Pour une robustesse accrue dans différents contextes d'exécution, on pourrait utiliser:
    # return os.path.join(os.path.dirname(__file__), '..', '..', PENDING_ASSOCIATIONS_FILE)
    # Mais pour l'instant, on garde simple, en supposant que le fichier est à la racine du CWD.
    return PENDING_ASSOCIATIONS_FILE

def _get_logger():
    """Helper pour obtenir le logger de Flask ou un logger par défaut."""
    try:
        from flask import current_app # Import moved here
        return current_app.logger
    except (RuntimeError, ImportError): # Catch ImportError as well
        # Retourner un logger basique si hors contexte de l'application Flask (ex: tests unitaires)
        # Assurez-vous que ce logger est configuré si vous en avez besoin pour les tests.
        # Pour les tests __main__, un logger est déjà configuré.
        # Si ce module est importé ailleurs sans contexte d'app, et sans logger Flask,
        # les messages de log pourraient ne pas apparaître comme souhaité.
        # On pourrait initialiser un logger par défaut ici si nécessaire.
        # Pour l'instant, on va laisser les fonctions gérer le logger None.
        return None


def _load_associations():
    """Charge les associations depuis le fichier JSON. La clé principale est torrent_hash."""
    filepath = get_pending_associations_filepath()
    logger = _get_logger()

    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content: # Fichier vide
                return {}
            associations = json.loads(content)
            if not isinstance(associations, dict):
                if logger:
                    logger.warning(f"Le contenu de {filepath} n'est pas un dictionnaire JSON. Traité comme vide.")
                return {}
            return associations
    except (json.JSONDecodeError, IOError) as e:
        if logger:
            logger.error(f"Erreur lors du chargement du fichier d'associations {filepath}: {e}. Le fichier sera traité comme vide/malformé.")
        else: # Fallback pour les tests unitaires si pas de logger Flask
            print(f"ERROR (mapping_manager._load_associations): Erreur lors du chargement de {filepath}: {e}")
        return {}

def _save_associations(associations):
    """Sauvegarde les associations (dictionnaire basé sur torrent_hash) dans le fichier JSON."""
    filepath = get_pending_associations_filepath()
    logger = _get_logger()
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(associations, f, indent=4)
        return True
    except IOError as e:
        if logger:
            logger.error(f"Erreur lors de la sauvegarde du fichier d'associations {filepath}: {e}")
        else:
            print(f"ERROR (mapping_manager._save_associations): Erreur lors de la sauvegarde de {filepath}: {e}")
        return False

def add_association_by_hash(torrent_hash, release_name_expected_on_seedbox, app_type, target_id, label):
    """
    Ajoute ou met à jour une association en utilisant torrent_hash comme clé principale.
    """
    logger = _get_logger()

    if logger:
        logger.debug(f"Ajout/Mise à jour de l'association pour torrent_hash: {torrent_hash}")

    if not torrent_hash:
        if logger:
            logger.error("Tentative d'ajout d'une association avec un torrent_hash vide.")
        return False

    associations = _load_associations()

    associations[torrent_hash] = {
        'release_name_expected_on_seedbox': release_name_expected_on_seedbox,
        'app_type': app_type,
        'target_id': target_id,
        'label': label,
        'added_timestamp': datetime.utcnow().isoformat()
        # Note: le torrent_hash lui-même n'est pas stocké à l'intérieur de l'objet valeur,
        # car il est la clé.
    }

    if _save_associations(associations):
        if logger:
            logger.info(f"Association pour hash '{torrent_hash}' (Release: '{release_name_expected_on_seedbox}') sauvegardée.")
        return True
    else:
        if logger:
            logger.error(f"Échec de la sauvegarde de l'association pour hash '{torrent_hash}'.")
        return False

def get_association_by_hash(torrent_hash):
    """Récupère une association en attente par son torrent_hash."""
    logger = _get_logger()
    associations = _load_associations()
    association = associations.get(torrent_hash)

    if logger:
        if association:
            logger.debug(f"Association trouvée pour torrent_hash '{torrent_hash}': {association}")
        else:
            logger.debug(f"Aucune association trouvée pour torrent_hash '{torrent_hash}'.")
    return association

def get_association_by_release_name(release_name_to_find):
    """
    Récupère la première association trouvée correspondant au release_name_expected_on_seedbox.
    Retourne un tuple (torrent_hash, association_data) ou (None, None) si non trouvée.
    """
    logger = _get_logger()
    associations = _load_associations()

    if logger:
        logger.debug(f"Recherche d'association pour release_name_expected_on_seedbox: '{release_name_to_find}'")

    for hash_key, assoc_data in associations.items():
        if assoc_data.get('release_name_expected_on_seedbox') == release_name_to_find:
            if logger:
                logger.debug(f"Association trouvée pour release name '{release_name_to_find}' avec hash '{hash_key}': {assoc_data}")
            return hash_key, assoc_data

    if logger:
        logger.debug(f"Aucune association trouvée pour release name '{release_name_to_find}'.")
    return None, None

def remove_association_by_hash(torrent_hash):
    """Supprime une association en attente par son torrent_hash."""
    logger = _get_logger()
    associations = _load_associations()

    if torrent_hash in associations:
        del associations[torrent_hash]
        if _save_associations(associations):
            if logger:
                logger.info(f"Association pour torrent_hash '{torrent_hash}' supprimée.")
            return True
        else:
            if logger:
                logger.error(f"Échec de la sauvegarde après suppression de l'association pour torrent_hash '{torrent_hash}'.")
            return False

    if logger:
        logger.debug(f"Tentative de suppression d'une association non existante pour torrent_hash '{torrent_hash}'.")
    return False

def get_all_pending_associations():
    """
    Récupère toutes les associations en attente.
    Le dictionnaire retourné est indexé par torrent_hash.
    """
    logger = _get_logger()
    if logger:
        logger.debug("Chargement de toutes les associations en attente (par hash).")
    return _load_associations()


if __name__ == '__main__':
    # Configuration d'un logger simple pour les tests
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    test_logger = logging.getLogger("mapping_manager_tests") # Utiliser un nom spécifique

    # S'assurer que le logger de flask n'est pas attendu ici en forçant _get_logger à retourner None
    # ou en s'assurant que les fonctions gèrent bien logger=None (ce qui est le cas)
    # Pour ce test, on va supposer que _get_logger() retourne None ou un logger compatible.

    test_logger.info("Début des tests du gestionnaire d'associations (mapping_manager.py)...")
    filepath = get_pending_associations_filepath()
    test_logger.info(f"Utilisation du fichier d'associations: {os.path.abspath(filepath)}")

    # Nettoyer le fichier de test avant de commencer
    if os.path.exists(PENDING_ASSOCIATIONS_FILE):
        os.remove(PENDING_ASSOCIATIONS_FILE)
        test_logger.debug(f"Fichier '{PENDING_ASSOCIATIONS_FILE}' nettoyé avant les tests.")

    # --- Nouveaux Tests Basés sur Hash ---
    hash1 = "testhash001"
    release1 = "My.Awesome.Release.S01E01.1080p.WEB-DL"
    hash2 = "testhash002"
    release2 = "Another.Great.Movie.2023.Bluray"
    hash3 = "testhash003" # Pourra avoir le même release name que hash1 pour tester get_by_release_name
    release3 = release1 # Même release name que hash1

    # Test 1: Ajout d'une nouvelle association par hash
    test_logger.info("\nTest 1: Ajout d'une association pour hash1")
    assert add_association_by_hash(hash1, release1, 'sonarr', 'series_id_abc', 'label-sonarr') == True
    assoc_h1 = get_association_by_hash(hash1)
    assert assoc_h1 is not None
    assert assoc_h1['release_name_expected_on_seedbox'] == release1
    assert assoc_h1['app_type'] == 'sonarr'
    assert assoc_h1['target_id'] == 'series_id_abc'
    assert 'added_timestamp' in assoc_h1
    test_logger.info(f"Association pour hash1 ('{hash1}') ajoutée et vérifiée: {assoc_h1}")

    # Test 2: Ajout d'une autre association
    test_logger.info("\nTest 2: Ajout d'une association pour hash2")
    assert add_association_by_hash(hash2, release2, 'radarr', 789, 'label-radarr') == True
    assoc_h2 = get_association_by_hash(hash2)
    assert assoc_h2 is not None
    assert assoc_h2['release_name_expected_on_seedbox'] == release2
    assert assoc_h2['app_type'] == 'radarr'
    test_logger.info(f"Association pour hash2 ('{hash2}') ajoutée et vérifiée: {assoc_h2}")

    # Test 3: Récupération de toutes les associations
    test_logger.info("\nTest 3: Récupération de toutes les associations")
    all_assocs = get_all_pending_associations()
    assert len(all_assocs) == 2
    assert hash1 in all_assocs
    assert hash2 in all_assocs
    test_logger.info(f"Toutes les associations récupérées ({len(all_assocs)}): {all_assocs}")

    # Test 4: Mise à jour d'une association existante (nouvel ajout avec même hash)
    test_logger.info("\nTest 4: Mise à jour de l'association pour hash1")
    updated_release1 = "My.Awesome.Release.S01E01.INTERNAL.1080p"
    assert add_association_by_hash(hash1, updated_release1, 'sonarr', 'series_id_def', 'label-sonarr-upd') == True
    updated_assoc_h1 = get_association_by_hash(hash1)
    assert updated_assoc_h1 is not None
    assert updated_assoc_h1['release_name_expected_on_seedbox'] == updated_release1
    assert updated_assoc_h1['target_id'] == 'series_id_def'
    assert updated_assoc_h1['label'] == 'label-sonarr-upd'
    test_logger.info(f"Association pour hash1 mise à jour et vérifiée: {updated_assoc_h1}")
    assert len(get_all_pending_associations()) == 2 # Nombre total ne doit pas changer

    # Test 5: Suppression d'une association par hash
    test_logger.info("\nTest 5: Suppression de l'association pour hash1")
    assert remove_association_by_hash(hash1) == True
    assert get_association_by_hash(hash1) is None
    assert len(get_all_pending_associations()) == 1
    test_logger.info(f"Association pour hash1 supprimée et vérifiée.")

    # Test 6: Tentative de suppression d'une association non existante par hash
    test_logger.info("\nTest 6: Suppression de 'non_existent_hash'")
    assert remove_association_by_hash('non_existent_hash') == False
    test_logger.info("Tentative de suppression d'une association non existante (par hash) gérée.")

    # Test 7: Tests pour get_association_by_release_name
    test_logger.info("\nTest 7: Tests pour get_association_by_release_name")
    # Remettre hash1 pour ce test, mais avec son release name original
    assert add_association_by_hash(hash1, release1, 'sonarr', 'series_id_abc', 'label-sonarr') == True
    test_logger.info(f"Ré-ajout de hash1 avec release name '{release1}' pour les tests de recherche par nom.")

    # 7a: Trouver une association existante par release name
    found_hash, found_assoc = get_association_by_release_name(release2)
    assert found_hash == hash2
    assert found_assoc is not None
    assert found_assoc['release_name_expected_on_seedbox'] == release2
    test_logger.info(f"Association trouvée pour release name '{release2}': hash='{found_hash}', data={found_assoc}")

    # 7b: Ne pas trouver une association pour un release name non existant
    non_existent_rn_hash, non_existent_rn_assoc = get_association_by_release_name("Non.Existent.Release.Name.XYZ")
    assert non_existent_rn_hash is None
    assert non_existent_rn_assoc is None
    test_logger.info("Recherche pour un release name non existant a retourné None, None comme attendu.")

    # 7c: Ajouter une autre association avec le *même* release_name que hash1 (release1)
    test_logger.info(f"Ajout de hash3 avec le même release name que hash1 ('{release1}')")
    assert add_association_by_hash(hash3, release1, 'radarr', 'movie_id_xyz', 'label-radarr-dup') == True

    # Vérifier que get_association_by_release_name retourne l'un d'eux (l'implémentation actuelle retournera le premier rencontré)
    # L'ordre peut dépendre de l'insertion dans le dictionnaire si Python < 3.7, mais généralement prévisible pour >3.7.
    # On ne peut pas garantir *lequel* est retourné sans tri explicite ou autre logique.
    # On vérifie juste qu'on en obtient un qui correspond.
    found_hash_dup, found_assoc_dup = get_association_by_release_name(release1)
    assert found_hash_dup is not None
    assert found_assoc_dup is not None
    assert found_assoc_dup['release_name_expected_on_seedbox'] == release1
    assert found_hash_dup in [hash1, hash3] # Doit être l'un des deux
    test_logger.info(f"Recherche pour release name '{release1}' (dupliqué) a retourné: hash='{found_hash_dup}', data={found_assoc_dup}")
    # S'assurer que les deux associations avec le même release_name existent toujours via leur hash
    assert get_association_by_hash(hash1) is not None
    assert get_association_by_hash(hash3) is not None
    assert len(get_all_pending_associations()) == 3 # hash1, hash2, hash3

    # Test 8: Gestion d'un fichier JSON malformé ou vide (vérification que _load_associations gère toujours cela)
    test_logger.info("\nTest 8: Gestion fichier malformé/vide")
    # 8a: Simuler un fichier malformé
    with open(PENDING_ASSOCIATIONS_FILE, 'w', encoding='utf-8') as f:
        f.write("ceci n'est pas du json")
    malformed_assocs = _load_associations()
    assert malformed_assocs == {}
    test_logger.info("Fichier malformé géré, _load_associations retourne un dict vide.")

    # 8b: S'assurer que add_association_by_hash peut écraser un fichier malformé
    test_logger.info("Test 8b: add_association_by_hash sur un fichier malformé")
    hash4 = "testhash004"
    release4 = "A.Final.Test.Entry.2024"
    assert add_association_by_hash(hash4, release4, 'sonarr', 'series_id_final', 'label-final') == True
    assoc_h4 = get_association_by_hash(hash4)
    assert assoc_h4 is not None
    assert assoc_h4['release_name_expected_on_seedbox'] == release4
    test_logger.info("add_association_by_hash a écrasé le fichier malformé et a fonctionné.")
    assert len(get_all_pending_associations()) == 1 # Seule l'association hash4 doit exister

    # 8c: Simuler un fichier vide
    with open(PENDING_ASSOCIATIONS_FILE, 'w', encoding='utf-8') as f:
        f.write("")
    empty_file_assocs = _load_associations()
    assert empty_file_assocs == {}
    test_logger.info("Fichier vide géré, _load_associations retourne un dict vide.")

    # 8d: S'assurer que add_association_by_hash peut utiliser un fichier vide
    test_logger.info("Test 8d: add_association_by_hash sur un fichier vide")
    hash5 = "testhash005"
    release5 = "Another.Final.Movie.HD"
    assert add_association_by_hash(hash5, release5, 'radarr', 1001, 'label-radarr-empty') == True
    assoc_h5 = get_association_by_hash(hash5)
    assert assoc_h5 is not None
    assert assoc_h5['release_name_expected_on_seedbox'] == release5
    test_logger.info("add_association_by_hash a utilisé le fichier vide et a fonctionné.")
    assert len(get_all_pending_associations()) == 1 # Seule l'association hash5 doit exister

    # Test 9: Tentative d'ajout avec un hash vide (devrait échouer)
    test_logger.info("\nTest 9: Tentative d'ajout avec un hash vide")
    assert add_association_by_hash("", "Release.Sans.Hash", "sonarr", "id1", "label1") == False
    test_logger.info("add_association_by_hash a correctement refusé un hash vide.")
    assert len(get_all_pending_associations()) == 1 # Le nombre ne doit pas avoir changé


    # Nettoyer le fichier de test après tous les tests
    if os.path.exists(PENDING_ASSOCIATIONS_FILE):
        os.remove(PENDING_ASSOCIATIONS_FILE)
        test_logger.debug(f"Fichier '{PENDING_ASSOCIATIONS_FILE}' nettoyé à la fin des tests.")

    test_logger.info("\n--- Tous les tests du mapping_manager sont terminés ---")