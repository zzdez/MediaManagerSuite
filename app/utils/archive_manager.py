# -*- coding: utf-8 -*-
import json
import os
import logging
from filelock import FileLock, Timeout
from flask import current_app
from datetime import datetime

# Logger pour ce module
module_logger = logging.getLogger(__name__)

def _get_db_path_and_logger():
    """Récupère le chemin du fichier de la BDD d'archives et le logger."""
    try:
        logger = current_app.logger
        path = current_app.config.get('ARCHIVE_DATABASE_FILE')
        if not path:
            logger.error("ARCHIVE_DATABASE_FILE n'est pas configuré.")
            raise ValueError("Chemin de la BDD d'archives non configuré.")
    except RuntimeError:
        logger = module_logger
        path = 'instance/archive_database.json'
        logger.info(f"Utilisation du chemin de secours pour la BDD d'archives: {path}")

    db_dir = os.path.dirname(path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
    return path, logger

def _load_database():
    """Charge la base de données JSON avec un verrouillage de fichier."""
    db_file, logger = _get_db_path_and_logger()
    lock_file = db_file + ".lock"
    lock = FileLock(lock_file, timeout=10)
    try:
        with lock:
            if not os.path.exists(db_file):
                return {}
            with open(db_file, 'r', encoding='utf-8') as f:
                content = f.read()
                return json.loads(content) if content else {}
    except (Timeout, json.JSONDecodeError) as e:
        logger.error(f"Erreur lors du chargement de {db_file}: {e}")
        return {} # Retourner un dictionnaire vide en cas d'erreur
    except Exception as e:
        logger.error(f"Erreur inattendue lors du chargement de {db_file}: {e}", exc_info=True)
        raise

def _save_database(data):
    """Sauvegarde la base de données JSON avec un verrouillage de fichier."""
    db_file, logger = _get_db_path_and_logger()
    lock_file = db_file + ".lock"
    lock = FileLock(lock_file, timeout=10)
    try:
        with lock:
            with open(db_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
    except Timeout:
        logger.error(f"Timeout lors de la sauvegarde de {db_file}.")
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la sauvegarde de {db_file}: {e}", exc_info=True)
        raise

def _get_key(media_type, external_id):
    """Construit une clé unique pour une entrée média."""
    return f"{media_type.lower()}_{external_id}"

def add_archived_media(media_data):
    """
    Ajoute ou met à jour une entrée pour un média archivé.
    media_data doit être un dictionnaire contenant les infos à sauvegarder.
    """
    if not all(k in media_data for k in ['media_type', 'external_id', 'user_id']):
        _, logger = _get_db_path_and_logger()
        logger.error("Données manquantes pour l'archivage: media_type, external_id et user_id sont requis.")
        return

    db_key = _get_key(media_data['media_type'], media_data['external_id'])
    database = _load_database()

    # Obtenir ou créer l'entrée de base
    entry = database.get(db_key, {
        'media_type': media_data['media_type'],
        'external_id': media_data['external_id'],
        'archive_history': []
    })

    # Mettre à jour les métadonnées principales à chaque fois
    entry['title'] = media_data.get('title')
    entry['year'] = media_data.get('year')
    entry['poster_url'] = media_data.get('poster_url')
    entry['summary'] = media_data.get('summary')

    # Chercher si une entrée existe déjà pour cet utilisateur (comparaison robuste)
    user_id_to_check = str(media_data['user_id'])
    existing_entry_index = -1
    for i, history in enumerate(entry['archive_history']):
        if str(history.get('user_id')) == user_id_to_check:
            existing_entry_index = i
            break

    # Créer ou mettre à jour l'entrée d'historique
    new_history_entry = {
        'user_id': user_id_to_check, # Sauvegarder en string pour la cohérence
        'archived_at': datetime.utcnow().isoformat(),
        'watched_status': media_data.get('watched_status', {})
    }

    if existing_entry_index != -1:
        # Remplacer l'entrée existante
        entry['archive_history'][existing_entry_index] = new_history_entry
    else:
        # Ajouter une nouvelle entrée
        entry['archive_history'].append(new_history_entry)

    database[db_key] = entry
    _save_database(database)

def find_archived_media_by_id(media_type, external_id):
    """
    Récupère un média archivé par son type et son ID externe.
    """
    db_key = _get_key(media_type, external_id)
    database = _load_database()
    return database.get(db_key)

def find_archived_media_by_title(title):
    """
    Recherche des médias archivés dont le titre correspond (insensible à la casse).
    """
    database = _load_database()
    results = []
    normalized_title = title.strip().lower()

    for key, entry in database.items():
        if entry.get('title') and normalized_title in entry['title'].lower():
            results.append(entry)

    return results
