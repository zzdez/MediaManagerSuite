import json
import os
import logging
from filelock import FileLock, Timeout
from flask import current_app
from datetime import datetime, timedelta

# Clients pour les métadonnées et la recherche
from app.utils.tmdb_client import TheMovieDBClient
from app.utils.tvdb_client import CustomTVDBClient
from app.utils.trailer_finder import find_youtube_trailer

# Logger pour ce module
module_logger = logging.getLogger(__name__)

def _get_db_path_and_logger():
    """
    Récupère le chemin du fichier de la base de données des bandes-annonces et le logger de l'application.
    Crée le répertoire si nécessaire.
    """
    try:
        logger = current_app.logger
        path = current_app.config.get('TRAILER_DATABASE_FILE')
        if not path:
            logger.error("TRAILER_DATABASE_FILE n'est pas configuré dans l'application Flask.")
            raise ValueError("Le chemin du fichier de la base de données des bandes-annonces n'est pas configuré.")
    except RuntimeError:  # Hors du contexte de l'application Flask
        logger = module_logger
        logger.warning("Contexte de l'application Flask non disponible. Le logger pourrait ne pas être entièrement configuré.")
        path = os.getenv('MMS_TRAILER_DATABASE_FILE_FALLBACK', 'instance/trailer_database.json')
        logger.info(f"Utilisation du chemin de secours pour la base de données des bandes-annonces : {path}")

    db_dir = os.path.dirname(path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir)
            logger.info(f"Répertoire créé pour la base de données des bandes-annonces : {db_dir}")
        except OSError as e:
            logger.error(f"Erreur lors de la création du répertoire {db_dir}: {e}")
            raise
    return path, logger

def _load_database():
    """Charge la base de données depuis le fichier JSON avec un verrouillage de fichier."""
    db_file, logger = _get_db_path_and_logger()
    lock_file = db_file + ".lock"
    lock = FileLock(lock_file, timeout=10)

    try:
        with lock:
            if not os.path.exists(db_file):
                return {}
            with open(db_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    logger.info(f"Le fichier de la base de données {db_file} est vide. Retourne une base de données vide.")
                    return {}
                try:
                    data = json.loads(content)
                    return data
                except json.JSONDecodeError:
                    logger.error(f"Erreur de décodage JSON depuis {db_file}. Retourne une base de données vide.")
                    return {}
    except Timeout:
        logger.error(f"Impossible d'acquérir le verrou pour {db_file} dans le temps imparti.")
        raise
    except Exception as e:
        logger.error(f"Une erreur inattendue est survenue lors du chargement de la base de données {db_file}: {e}")
        raise

def _save_database(data):
    """Sauvegarde la base de données dans le fichier JSON avec un verrouillage de fichier."""
    db_file, logger = _get_db_path_and_logger()
    lock_file = db_file + ".lock"
    lock = FileLock(lock_file, timeout=10)

    try:
        with lock:
            with open(db_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logger.debug(f"Base de données des bandes-annonces sauvegardée dans {db_file}")
    except Timeout:
        logger.error(f"Impossible d'acquérir le verrou pour {db_file} pour la sauvegarde. Données non sauvegardées.")
        raise
    except Exception as e:
        logger.error(f"Une erreur inattendue est survenue lors de la sauvegarde de la base de données dans {db_file}: {e}")
        raise

def _get_key(media_type, external_id):
    """Construit la clé de base de données standardisée."""
    return f"{media_type.lower()}_{external_id}"

def get_trailer_info(media_type, external_id, title, year=None, page_token=None):
    """
    Fonction principale pour obtenir les informations sur la bande-annonce d'un média.
    Implémente la logique de cache, de verrouillage et de recherche externe.
    """
    db_key = _get_key(media_type, external_id)
    database = _load_database()
    _, logger = _get_db_path_and_logger()

    entry = database.get(db_key, {})

    # Cas 1: La bande-annonce est verrouillée
    if entry.get('is_locked'):
        # Rétrocompatibilité : si on trouve un ancien format, on le migre
        if entry.get('locked_video_id') and not entry.get('locked_video_data'):
            logger.info(f"Migration de l'ancien format de verrouillage pour {db_key}.")
            entry['locked_video_data'] = {
                'videoId': entry['locked_video_id'],
                'title': 'Bande-annonce verrouillée (données à rafraîchir)',
                'thumbnail': '/static/img/placeholder.png',
                'channel': ''
            }
            entry.pop('locked_video_id', None)
            database[db_key] = entry # Met à jour la base de données en mémoire
            _save_database(database) # Sauvegarde la migration sur le disque

        if entry.get('locked_video_data'):
            logger.info(f"Retourne la bande-annonce verrouillée pour {db_key}.")
            return {'status': 'locked', 'locked_video_data': entry['locked_video_data']}

    # Cas 2: Il y a une recherche en cache et on ne demande pas une autre page
    cache_age_days = current_app.config.get('TRAILER_CACHE_AGE_DAYS', 7)
    if not page_token and entry.get('search_results'):
        last_search_str = entry.get('last_search_timestamp')
        if last_search_str:
            last_search_date = datetime.fromisoformat(last_search_str)
            if datetime.utcnow() - last_search_date < timedelta(days=cache_age_days):
                logger.info(f"Retourne les résultats de recherche en cache pour {db_key}.")
                return {
                    'status': 'success',
                    'results': entry['search_results'],
                    'next_page_token': entry.get('next_page_token')
                }

    # Cas 3: Le cache est expiré, inexistant, ou on demande une nouvelle page -> Recherche externe
    logger.info(f"Cache expiré ou inexistant pour {db_key}. Lancement d'une nouvelle recherche.")

    # Étape A: Vérifier que le titre a été fourni par l'appelant.
    if not title:
        logger.error(f"Titre non fourni pour la recherche de bande-annonce pour {db_key}. C'est une erreur de l'appelant.")
        return {'status': 'error', 'message': 'Le titre est manquant pour lancer la recherche.'}

    # Étape B: Construire la requête et appeler l'API YouTube
    query = f"{title} {year if year else ''} bande annonce fr"
    api_key = current_app.config.get('YOUTUBE_API_KEY')
    if not api_key:
        logger.error("Clé API YouTube non configurée.")
        return {'status': 'error', 'message': 'Clé API YouTube non configurée.'}

    youtube_response = find_youtube_trailer(query, api_key, page_token=page_token)

    # Étape C: Mettre à jour la base de données et retourner la réponse
    new_results = youtube_response.get('results', [])
    new_next_page_token = youtube_response.get('nextPageToken')

    # Si on pagine, on ajoute les résultats. Sinon, on les remplace.
    if page_token and entry.get('search_results'):
        entry['search_results'].extend(new_results)
    else:
        entry['search_results'] = new_results

    entry['next_page_token'] = new_next_page_token
    entry['last_search_timestamp'] = datetime.utcnow().isoformat()
    entry['is_locked'] = False # S'assurer que le statut est bien 'non verrouillé'

    database[db_key] = entry
    _save_database(database)
    logger.info(f"Résultats de recherche mis à jour pour {db_key}.")

    return {
        'status': 'success',
        'results': entry['search_results'],
        'next_page_token': new_next_page_token
    }

def lock_trailer(media_type, external_id, video_data):
    """
    Verrouille une bande-annonce spécifique pour un média en sauvegardant toutes ses données.
    """
    db_key = _get_key(media_type, external_id)
    database = _load_database()
    _, logger = _get_db_path_and_logger()

    entry = database.get(db_key, {})

    entry['is_locked'] = True
    # Au lieu de juste stocker l'ID, on stocke l'objet vidéo complet
    entry['locked_video_data'] = {
        'videoId': video_data.get('videoId'),
        'title': video_data.get('title'),
        'thumbnail': video_data.get('thumbnail'),
        'channel': video_data.get('channel')
    }
    entry['last_updated_timestamp'] = datetime.utcnow().isoformat()

    # On purge les anciens résultats de recherche pour ne garder que le verrou
    if 'search_results' in entry:
        del entry['search_results']
    if 'next_page_token' in entry:
        del entry['next_page_token']

    database[db_key] = entry
    _save_database(database)
    logger.info(f"Bande-annonce verrouillée pour {db_key} avec les données : {video_data}")
    return True

def get_trailer_status(media_type, external_id):
    """
    Vérifie le statut d'une bande-annonce pour un média donné.

    Retourne:
        str: 'LOCKED' si une bande-annonce est verrouillée.
             'UNLOCKED' si des résultats de recherche existent mais rien n'est verrouillé.
             'NONE' si aucune information n'est disponible.
    """
    db_key = _get_key(media_type, external_id)
    database = _load_database()
    entry = database.get(db_key, {})

    if entry.get('is_locked'):
        return 'LOCKED'
    if entry.get('search_results'):
        return 'UNLOCKED'
    return 'NONE'

def is_trailer_locked(media_type, external_id):
    """
    Vérifie de manière légère si une bande-annonce est verrouillée.
    Utilise maintenant get_trailer_status pour la cohérence.
    Retourne True si le statut est 'LOCKED', False sinon.
    """
    return get_trailer_status(media_type, external_id) == 'LOCKED'

def get_locked_trailer_video_id(media_type, external_id):
    """
    Récupère l'ID vidéo de la bande-annonce verrouillée, si elle existe.
    Retourne:
        str|None: L'ID de la vidéo YouTube, ou None si non verrouillée ou non trouvée.
    """
    db_key = _get_key(media_type, external_id)
    database = _load_database()
    entry = database.get(db_key, {})

    if entry.get('is_locked') and entry.get('locked_video_data'):
        return entry['locked_video_data'].get('videoId')
    return None

def unlock_trailer(media_type, external_id):
    """Déverrouille la bande-annonce pour un média."""
    db_key = _get_key(media_type, external_id)
    database = _load_database()
    _, logger = _get_db_path_and_logger()

    if db_key in database:
        database[db_key]['is_locked'] = False
        database[db_key].pop('locked_video_id', None) # Ancien format
        database[db_key].pop('locked_video_data', None) # Nouveau format
        database[db_key]['last_updated_timestamp'] = datetime.utcnow().isoformat()
        _save_database(database)
        logger.info(f"Bande-annonce déverrouillée pour {db_key}.")
        return True

    logger.warning(f"Tentative de déverrouillage pour une entrée inexistante : {db_key}")
    return False

def clear_trailer_cache(media_type, external_id):
    """Supprime complètement une entrée de la base de données des bandes-annonces."""
    db_key = _get_key(media_type, external_id)
    database = _load_database()
    _, logger = _get_db_path_and_logger()

    if db_key in database:
        del database[db_key]
        _save_database(database)
        logger.info(f"Cache effacé pour {db_key}.")
        return True

    logger.warning(f"Tentative d'effacement de cache pour une entrée inexistante : {db_key}")
    return False

def clean_stale_entries(max_age_days=30):
    """
    Nettoie les anciennes entrées non verrouillées de la base de données des bandes-annonces.
    """
    database = _load_database()
    _, logger = _get_db_path_and_logger()

    keys_to_delete = []
    now = datetime.utcnow()
    max_age = timedelta(days=max_age_days)

    for key, entry in database.items():
        # On ne nettoie que les entrées qui ne sont pas verrouillées
        if not entry.get('is_locked'):
            last_search_str = entry.get('last_search_timestamp')
            if last_search_str:
                try:
                    last_search_date = datetime.fromisoformat(last_search_str)
                    if now - last_search_date > max_age:
                        keys_to_delete.append(key)
                except ValueError:
                    # Si le timestamp est malformé, on le supprime aussi par sécurité
                    logger.warning(f"Timestamp malformé pour l'entrée {key}. Elle sera supprimée.")
                    keys_to_delete.append(key)
            else:
                # S'il n'y a pas de timestamp et que ce n'est pas verrouillé, c'est une entrée orpheline
                logger.warning(f"Entrée orpheline trouvée ({key}). Elle sera supprimée.")
                keys_to_delete.append(key)

    if keys_to_delete:
        logger.info(f"Nettoyage de {len(keys_to_delete)} entrée(s) obsolète(s) de la base de données des bandes-annonces.")
        for key in keys_to_delete:
            del database[key]
        _save_database(database)
        return len(keys_to_delete)

    logger.info("Aucune entrée obsolète à nettoyer dans la base de données des bandes-annonces.")
    return 0