# -*- coding: utf-8 -*-
import json
import os
import logging
from filelock import FileLock, Timeout
from flask import current_app
from datetime import datetime
from app.utils.tmdb_client import TheMovieDBClient
from app.utils.tvdb_client import CustomTVDBClient

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
        return {}
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
    """Construit une clé unique au format 'tv_<id>' ou 'movie_<id>'."""
    prefix = 'tv' if media_type == 'show' else media_type
    return f"{prefix.lower()}_{external_id}"

from app.utils.plex_client import PlexClient

def add_archived_media(media_type, external_id, user_id, rating_key=None, season_number=None, episode_number=None, total_episode_counts=None, last_viewed_at=None):
    """
    Ajoute ou met à jour une entrée pour un média archivé.
    Récupère les métadonnées fraîches et l'historique de visionnage, et gère les doublons.
    Pour les items fantômes ('shows'), peut enrichir l'historique avec les numéros de saison/épisode,
    le nombre total d'épisodes et la date de dernier visionnage.
    Retourne (True, "Success message") ou (False, "Error/Info message").
    """
    _, logger = _get_db_path_and_logger()

    if not all([media_type, external_id, user_id]):
        return False, "Données manquantes : media_type, external_id et user_id sont requis."

    db_key = _get_key(media_type, external_id)
    database = _load_database()
    is_new_entry = db_key not in database
    entry = database.get(db_key, {
        'media_type': 'tv' if media_type == 'show' else media_type,
        'external_id': external_id, 'archive_history': []
    })

    # Mise à jour des métadonnées si c'est une nouvelle entrée ou si elles sont incomplètes
    needs_metadata_update = not all(entry.get(k) for k in ['title', 'year', 'poster_url', 'summary'])

    if is_new_entry or needs_metadata_update:
        logger.info(f"Mise à jour des métadonnées requise pour {db_key} (Nouvelle entrée: {is_new_entry}, Données manquantes: {needs_metadata_update}).")
        fresh_metadata = {}
        if media_type == 'show':
            try:
                series_details = CustomTVDBClient().get_series_details_by_id(external_id)
                if series_details:
                    fresh_metadata = {'title': series_details.get('name'), 'year': series_details.get('year'),
                                      'poster_url': series_details.get('image'), 'summary': series_details.get('overview')}
            except Exception as e:
                logger.warning(f"Impossible de récupérer les détails TVDB pour {external_id}: {e}")
        elif media_type == 'movie':
            try:
                movie_details = TheMovieDBClient().get_movie_details(external_id)
                if movie_details:
                    fresh_metadata = {
                        'title': movie_details.get('title'),
                        'year': movie_details.get('year'), # Utilise directement l'année traitée par le client
                        'poster_url': f"https://image.tmdb.org/t/p/w500{movie_details.get('poster_path')}" if movie_details.get('poster_path') else None,
                        'summary': movie_details.get('overview')
                    }
                    logger.info(f"Métadonnées TMDB récupérées pour {db_key}: {fresh_metadata.get('title')} ({fresh_metadata.get('year')})")
            except Exception as e:
                logger.warning(f"Impossible de récupérer les détails TMDB pour {external_id}: {e}")

        # Remplacer les métadonnées existantes uniquement si les nouvelles sont valides
        for key, value in fresh_metadata.items():
            if value:
                entry[key] = value

    # Gérer l'historique de visionnage
    user_id_str = str(user_id)
    user_history_index = next((i for i, h in enumerate(entry['archive_history']) if str(h.get('user_id')) == user_id_str), -1)

    if user_history_index != -1:
        history_entry = entry['archive_history'][user_history_index]
    else:
        history_entry = {'user_id': user_id_str, 'archived_at': None, 'watched_status': {}}

    # Mise à jour de l'historique
    if rating_key: # Item non-fantôme
        try:
            plex_client = PlexClient(user_id=user_id)
            plex_item = plex_client.get_item_by_rating_key(int(rating_key))
            if media_type == 'show':
                history_entry['watched_status'] = plex_client.get_show_watch_history(plex_item) or {}
            else:
                history_entry['watched_status'] = plex_client.get_movie_watch_history(plex_item) or {}
            history_entry['archived_at'] = datetime.utcnow().isoformat()
        except Exception as e:
            logger.error(f"Erreur PLEX pour {rating_key}: {e}", exc_info=True)
            return False, f"Erreur de récupération PLEX pour {rating_key}."
    else: # Item fantôme
        # Mise à jour de la date de dernier visionnage si fournie et plus récente
        if last_viewed_at:
            if 'last_viewed_at' not in history_entry or not history_entry['last_viewed_at'] or last_viewed_at > history_entry['last_viewed_at']:
                history_entry['last_viewed_at'] = last_viewed_at

        if media_type == 'show':
            # Assurer l'initialisation de la structure
            if 'seasons' not in history_entry['watched_status']:
                history_entry['watched_status']['seasons'] = []

            # Enrichir les saisons existantes avec le total_count si disponible
            if total_episode_counts:
                for s in history_entry['watched_status']['seasons']:
                    s_num = s.get('season_number')
                    if s_num in total_episode_counts and 'total_count' not in s:
                        s['total_count'] = total_episode_counts[s_num]

            if season_number is not None and episode_number is not None:
                # Chercher si la saison existe déjà
                season_entry = next((s for s in history_entry['watched_status']['seasons'] if s.get('season_number') == season_number), None)
                if not season_entry:
                    season_entry = {'season_number': season_number, 'episodes_watched': []}
                    if total_episode_counts and season_number in total_episode_counts:
                        season_entry['total_count'] = total_episode_counts[season_number]
                    history_entry['watched_status']['seasons'].append(season_entry)

                # Ajouter l'épisode s'il n'est pas déjà listé
                if episode_number not in season_entry['episodes_watched']:
                    season_entry['episodes_watched'].append(episode_number)
                    season_entry['episodes_watched'].sort()
                    # Mettre à jour le compteur d'épisodes vus
                    season_entry['watched_count'] = len(season_entry['episodes_watched'])
                    history_entry['archived_at'] = datetime.utcnow().isoformat()
                    logger.info(f"Épisode fantôme S{season_number}E{episode_number} ajouté pour '{entry.get('title', db_key)}'.")
                else:
                    return False, f"Épisode S{season_number}E{episode_number} déjà archivé pour '{entry.get('title', db_key)}'."
        elif media_type == 'movie':
            if history_entry.get('archived_at'):
                return False, f"Film fantôme '{entry.get('title', db_key)}' déjà archivé."

            # Structure 'watched_status' alignée sur celle des items non-fantômes
            history_entry['watched_status'] = {
                "is_watched": True,
                "status": "viewed_ghost",
                "last_viewed_at": last_viewed_at,
                "history": [
                    {
                        "viewed_at": last_viewed_at,
                        "user_id": user_id_str
                    }
                ]
            }
            history_entry['archived_at'] = datetime.utcnow().isoformat()

    # Mettre à jour l'entrée dans la BDD
    if user_history_index != -1:
        entry['archive_history'][user_history_index] = history_entry
    else:
        entry['archive_history'].append(history_entry)

    database[db_key] = entry
    _save_database(database)

    return True, f"Média '{entry.get('title', db_key)}' archivé/mis à jour."


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

def migrate_database_keys():
    """
    Migre les clés de la base de données du format 'show_<id>' vers 'tv_<id>'.
    Cette fonction est destinée à être exécutée une seule fois au démarrage si nécessaire.
    """
    db_file, logger = _get_db_path_and_logger()
    if not os.path.exists(db_file):
        return # Pas de BDD, pas de migration à faire

    database = _load_database()
    if not database:
        return

    updated = False
    new_database = {}
    for key, value in database.items():
        if key.startswith('show_'):
            new_key = key.replace('show_', 'tv_', 1)
            new_database[new_key] = value
            logger.info(f"Migration de la clé d'archive: '{key}' -> '{new_key}'")
            updated = True
        else:
            new_database[key] = value

    if updated:
        _save_database(new_database)
        logger.info("Migration des clés de la base de données d'archives terminée.")

# Ligne pour déclencher la migration au démarrage de l'application.
# Cela garantit que la BDD est cohérente avant toute opération.
migrate_database_keys()
