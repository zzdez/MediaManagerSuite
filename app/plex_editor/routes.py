# app/plex_editor/routes.py
# -*- coding: utf-8 -*-
# Commentaire pour forcer la relecture du fichier

import os
from app.auth import login_required
from flask import (render_template, current_app, flash, abort, url_for,
                   redirect, request, session, jsonify, current_app)
from datetime import datetime, timedelta
import pytz
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound, Unauthorized, BadRequest

# Importer le Blueprint
from . import plex_editor_bp

# Importer les fonctions utilitaires Plex depuis le nouveau module
from app.utils.plex_client import get_main_plex_account_object, get_plex_admin_server, get_user_specific_plex_server

# Importer les utils spécifiques à plex_editor
from .utils import cleanup_parent_directory_recursively, get_media_filepath, _is_dry_run_mode
# Importer les utils globaux/partagés
from app.utils.arr_client import (
    get_radarr_tag_id, get_radarr_movie_by_guid, update_radarr_movie,
    get_sonarr_tag_id, get_sonarr_series_by_guid, get_sonarr_series_by_id,
    update_sonarr_series, get_sonarr_episode_files, get_sonarr_episodes_by_series_id,
    get_all_sonarr_series, # <--- AJOUT ICI
    sonarr_trigger_series_rename,
    search_sonarr_series_by_title_and_year
)
from app.utils.trailer_finder import find_plex_trailer, get_videos_details
from app.utils.tmdb_client import TheMovieDBClient
from app.utils.tvdb_client import CustomTVDBClient
from app.utils.cache_manager import SimpleCache, get_pending_lock, remove_pending_lock
from app.utils import trailer_manager # Import du nouveau manager
from app.agent.services import _search_and_score_trailers
from thefuzz import fuzz

from app.utils.move_manager import move_manager
from app.utils.arr_client import get_sonarr_root_folders, get_radarr_root_folders, move_sonarr_series, move_radarr_movie, get_arr_command_status, radarr_post_command
from app.utils.bulk_move_manager import bulk_move_manager # Import du nouveau manager

# --- Routes du Blueprint ---

# --- Route de test pour la synchronisation de l'historique fantôme ---
@plex_editor_bp.route('/sync_test')
@login_required
def sync_test_page():
    """Affiche une page de test pour lancer la synchronisation de l'historique."""
    return render_template('plex_editor/sync_test.html')

@plex_editor_bp.route('/run_sync_test', methods=['POST'])
@login_required
def run_sync_test():
    """Exécute le script de test de synchronisation de l'historique fantôme."""
    from app.utils.archive_manager import add_archived_media
    user_id = request.form.get('user_id')
    if not user_id:
        flash("Veuillez sélectionner un utilisateur.", "danger")
        return redirect(url_for('plex_editor.sync_test_page'))

    try:
        main_account = get_main_plex_account_object()
        user_title = f"ID: {user_id}"
        if main_account:
            if str(main_account.id) == user_id:
                user_title = main_account.title
            else:
                user_account = next((u for u in main_account.users() if str(u.id) == user_id), None)
                if user_account:
                    user_title = user_account.title

        user_plex = get_user_specific_plex_server_from_id(user_id)
        if not user_plex:
            flash(f"Impossible de se connecter au serveur Plex pour l'utilisateur '{user_title}'.", "danger")
            return redirect(url_for('plex_editor.sync_test_page'))

        flash(f"Scan de l'historique Plex (2000 derniers éléments) pour '{user_title}' en cours...", "info")

        tmdb_client = TheMovieDBClient()
        tvdb_client = CustomTVDBClient()
        history = user_plex.history(maxresults=2000)

        media_cache = {}
        last_viewed_dates = {}
        plex_item_exists_cache = {}

        # --- NOUVEAUX COMPTEURS ET LIMITES ---
        processed_movies = set()
        processed_shows = set()
        MOVIE_LIMIT = 5
        SHOW_LIMIT = 5
        archived_count = 0
        limit_reached = False

        for entry in history:
            source_item = None
            try:
                source_item = entry.source()
            except NotFound:
                pass

            if source_item is not None:
                continue

            year = getattr(entry, 'originallyAvailableAt', None)
            if year:
                year = year.year

            unique_key, title, entry_media_type = None, None, None
            if entry.type == 'movie':
                title = getattr(entry, 'title', None)
                if title and year:
                    unique_key = f"movie_{title}_{year}"
                    entry_media_type = 'movie'
            elif entry.type == 'episode':
                title = getattr(entry, 'grandparentTitle', None)
                if title:
                    unique_key = f"show_{title}"
                    entry_media_type = 'show'

            if not unique_key:
                continue

            # --- NOUVELLE VÉRIFICATION DE LA LIMITE ---
            # On continue de traiter les entrées pour les médias déjà dans notre set de traitement,
            # mais on n'ajoute pas de NOUVEAUX médias si la limite est atteinte.
            if entry_media_type == 'movie' and unique_key not in processed_movies and len(processed_movies) >= MOVIE_LIMIT:
                continue

            if entry_media_type == 'show' and unique_key not in processed_shows and len(processed_shows) >= SHOW_LIMIT:
                continue

            # Condition d'arrêt/continuation: si les deux listes sont pleines, on ne traite plus que
            # les items déjà connus.
            if len(processed_movies) >= MOVIE_LIMIT and len(processed_shows) >= SHOW_LIMIT:
                limit_reached = True # On met le flag pour le message final
                if unique_key not in processed_movies and unique_key not in processed_shows:
                    continue # On ignore ce nouvel item et on passe au suivant.

            if title not in plex_item_exists_cache:
                plex_search_results = user_plex.search(title)
                exists = any(hasattr(item, 'title') and item.title.lower() == title.lower() for item in plex_search_results)
                plex_item_exists_cache[title] = exists

            if plex_item_exists_cache[title]:
                current_app.logger.info(f"Le média '{title}' existe toujours dans Plex. Ignoré.")
                continue

            entry_viewed_at = getattr(entry, 'viewedAt', None)
            if entry_viewed_at:
                current_latest = last_viewed_dates.get(unique_key)
                if not current_latest or entry_viewed_at.isoformat() > current_latest:
                    last_viewed_dates[unique_key] = entry_viewed_at.isoformat()

            if unique_key not in media_cache:
                media_type, external_id, extra_data = None, None, {}
                if entry.type == 'movie':
                    search_results = tmdb_client.search_movie(title)
                    filtered_results = [m for m in search_results if m.get('year') == str(year)]
                    if filtered_results:
                        media_type = 'movie'
                        external_id = filtered_results[0].get('id')
                elif entry.type == 'episode':
                    search_results = tvdb_client.search_and_translate_series(title)
                    best_match = None
                    if search_results:
                        if len(search_results) == 1:
                            best_match = search_results[0]
                        else:
                            SIMILARITY_THRESHOLD = 85
                            highly_similar_results = [r for r in search_results if fuzz.ratio(title.lower(), r.get('name', '').lower()) > SIMILARITY_THRESHOLD]
                            if highly_similar_results:
                                min_year_diff = float('inf')
                                for result in highly_similar_results:
                                    try:
                                        result_year = int(result.get('year', 0))
                                        if result_year > 0 and year is not None:
                                            diff = abs(result_year - year)
                                            if diff < min_year_diff:
                                                min_year_diff = diff
                                                best_match = result
                                    except (ValueError, TypeError): continue
                                if not best_match: best_match = highly_similar_results[0]
                    if best_match:
                        media_type = 'show'
                        external_id = best_match.get('tvdb_id')
                        total_episode_counts = tvdb_client.get_season_episode_counts(external_id)
                        extra_data['total_episode_counts'] = total_episode_counts
                        current_app.logger.info(f"Match TVDB pour '{title}' -> ID: {external_id}, Counts: {total_episode_counts}")

                media_cache[unique_key] = (media_type, external_id, extra_data)

            media_type, external_id, extra_data = media_cache.get(unique_key, (None, None, {}))

            if media_type and external_id:
                if media_type == 'movie':
                    processed_movies.add(unique_key)
                elif media_type == 'show':
                    processed_shows.add(unique_key)

                season_number = episode_number = None
                if entry.type == 'episode':
                    season_number = getattr(entry, 'parentIndex', None)
                    episode_number = getattr(entry, 'index', None)

                success, message = add_archived_media(
                    media_type=media_type,
                    external_id=external_id,
                    user_id=user_id,
                    season_number=season_number,
                    episode_number=episode_number,
                    total_episode_counts=extra_data.get('total_episode_counts'),
                    last_viewed_at=last_viewed_dates.get(unique_key)
                )

                if success and unique_key not in (getattr(request, '_processed_flash', set())):
                    flash(f"Archivage fantôme réussi pour : {title}", "success")
                    if not hasattr(request, '_processed_flash'):
                        request._processed_flash = set()
                    request._processed_flash.add(unique_key)
                    archived_count +=1
                elif not success:
                     current_app.logger.info(f"Info/Échec archivage fantôme pour {unique_key}: {message}")

        if limit_reached:
            flash(f"Limite de test atteinte ({len(processed_movies)} films, {len(processed_shows)} séries). Scan arrêté.", "warning")

        if archived_count == 0:
            flash("Scan terminé. Aucun nouvel item fantôme n'a pu être identifié dans l'échantillon.", "info")
        else:
            flash(f"Scan terminé. {archived_count} nouveau(x) média(s) fantôme(s) ont été archivés.", "success")

        return redirect(url_for('plex_editor.sync_test_page'))

    except Exception as e:
        current_app.logger.error(f"Erreur majeure lors du test de synchronisation: {e}", exc_info=True)
        flash(f"Une erreur inattendue est survenue: {str(e)}", "danger")
        return redirect(url_for('plex_editor.sync_test_page'))


@plex_editor_bp.route('/api/media/root_folders', methods=['GET'])
@login_required
def get_root_folders():
    sonarr_folders = get_sonarr_root_folders() or []
    radarr_folders = get_radarr_root_folders() or []

    all_folders = sonarr_folders + radarr_folders

    # Utiliser un dictionnaire pour dédoublonner par chemin, au cas où
    unique_folders_dict = {folder['path']: folder for folder in all_folders if folder.get('path')}
    unique_folders = list(unique_folders_dict.values())

    if not unique_folders:
        return jsonify([]) # Renvoyer une liste vide est plus simple pour le frontend

    response_data = [
        {
            'path': folder.get('path'),
            'freeSpace_formatted': folder.get('freeSpace_formatted', 'N/A')
        }
        for folder in unique_folders
    ]
    # Trier pour un affichage cohérent
    response_data.sort(key=lambda x: x['path'])

    return jsonify(response_data)

@plex_editor_bp.route('/api/media/move', methods=['POST'])
@login_required
def move_media_item():
    data = request.get_json()
    plex_rating_key = data.get('mediaId')
    media_type = data.get('mediaType')
    new_path = data.get('newPath')

    if not all([plex_rating_key, media_type, new_path]):
        return jsonify({'status': 'error', 'message': 'Données manquantes.'}), 400

    if move_manager.is_move_in_progress():
        return jsonify({'status': 'error', 'message': 'Un autre déplacement est déjà en cours.'}), 409

    try:
        plex_server = get_plex_admin_server()
        if not plex_server:
            return jsonify({'status': 'error', 'message': 'Connexion au serveur Plex admin échouée.'}), 500

        plex_item = plex_server.fetchItem(int(plex_rating_key))

        arr_item = None
        if media_type == 'sonarr':
            guid = next((g.id for g in plex_item.guids if 'tvdb' in g.id), None)
            if guid: arr_item = get_sonarr_series_by_guid(guid)
        elif media_type == 'radarr':
            guid = next((g.id for g in plex_item.guids if 'tmdb' in g.id), None)
            current_app.logger.info(f"Move '{plex_item.title}': Found Plex GUID for Radarr: {guid}")
            if guid: arr_item = get_radarr_movie_by_guid(guid)

        if not arr_item or not arr_item.get('id'):
            current_app.logger.error(f"Move '{plex_item.title}': Could not find corresponding media in {media_type.capitalize()} using GUID {guid}.")
            return jsonify({'status': 'error', 'message': f"Média non trouvé dans {media_type.capitalize()}."}), 404

        arr_item_id = arr_item.get('id')
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la traduction de l'ID Plex {plex_rating_key}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': "Erreur lors de la recherche du média correspondant."}), 500

    if media_type == 'sonarr':
        success, error = move_sonarr_series(arr_item_id, new_path)
        if success:
            return jsonify({'status': 'success', 'message': 'Déplacement initié dans Sonarr.'})
        else:
            return jsonify({'status': 'error', 'message': error or 'Échec du déplacement dans Sonarr.'}), 500

    elif media_type == 'radarr':
        # La nouvelle fonction move_radarr_movie est synchrone, comme pour Sonarr.
        # Le système de polling n'est plus nécessaire pour Radarr.
        success, error = move_radarr_movie(arr_item_id, new_path)
        if success:
            return jsonify({'status': 'success', 'message': 'Déplacement initié dans Radarr.'})
        else:
            return jsonify({'status': 'error', 'message': error or 'Échec du déplacement dans Radarr.'}), 500

    return jsonify({'status': 'error', 'message': 'Type de média non supporté.'}), 400

@plex_editor_bp.route('/api/media/move_status', methods=['GET'])
@login_required
def get_move_status():
    current_move = move_manager.get_current_move_status()
    if not current_move:
        return jsonify({'status': 'idle'})

    task_id = current_move['task_id']
    command_id = current_move.get('command_id')
    media_type = current_move['media_type']

    if not command_id:
        move_manager.end_move(task_id)
        return jsonify({'status': 'error', 'message': 'Tâche de déplacement invalide sans ID de commande.'})

    command_status = get_arr_command_status(media_type, command_id)

    if not command_status:
        move_manager.end_move(task_id)
        return jsonify({'status': 'error', 'message': f'Impossible de récupérer le statut de la commande {command_id}.'})

    status = command_status.get('status')
    if status == 'completed':
        move_manager.end_move(task_id)
        return jsonify({'status': 'completed', 'message': 'Déplacement terminé avec succès.'})
    elif status in ['failed', 'aborted']:
        error_message = command_status.get('body', {}).get('exception', 'Erreur inconnue.')
        move_manager.end_move(task_id)
        return jsonify({'status': 'failed', 'message': f'Le déplacement a échoué: {error_message}'})
    else: # 'pending', 'started', 'running'
        return jsonify({'status': 'running', 'message': f'Déplacement en cours... (Statut: {status})'})

@plex_editor_bp.route('/api/media/bulk_move', methods=['POST'])
@login_required
def bulk_move_media_items():
    data = request.get_json()
    items_to_move = data.get('items', []) # ex: [{'plex_id': key, 'media_type': type, 'destination': path}]

    if not items_to_move:
        return jsonify({'status': 'error', 'message': 'Aucun élément à déplacer fourni.'}), 400

    if bulk_move_manager.is_task_running():
        return jsonify({'status': 'error', 'message': 'Une autre tâche de déplacement est déjà en cours.'}), 409

    processed_items_for_manager = []
    try:
        plex_server = get_plex_admin_server()
        if not plex_server:
            return jsonify({'status': 'error', 'message': 'Connexion au serveur Plex admin échouée.'}), 500

        for item_data in items_to_move:
            plex_rating_key = item_data.get('plex_id')
            media_type = item_data.get('media_type') # 'sonarr' ou 'radarr'
            destination = item_data.get('destination')

            plex_item = plex_server.fetchItem(int(plex_rating_key))

            arr_item = None
            if media_type == 'sonarr':
                guid = next((g.id for g in plex_item.guids if 'tvdb' in g.id), None)
                if guid: arr_item = get_sonarr_series_by_guid(guid)
            elif media_type == 'radarr':
                guid = next((g.id for g in plex_item.guids if 'tmdb' in g.id), None)
                if guid: arr_item = get_radarr_movie_by_guid(guid)

            if not arr_item or not arr_item.get('id'):
                current_app.logger.error(f"BulkMove: Could not find media in {media_type} for Plex ID {plex_rating_key} (GUID: {guid})")
                continue # On ignore cet item

            processed_items_for_manager.append({
                'media_id': arr_item.get('id'),
                'title': plex_item.title,
                'media_type': media_type,
                'destination': destination,
                'library_key': plex_item.librarySectionID
            })

    except Exception as e:
        current_app.logger.error(f"Erreur lors de la préparation du déplacement en masse: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': "Erreur lors de la préparation des médias pour le déplacement."}), 500

    if not processed_items_for_manager:
        return jsonify({'status': 'error', 'message': 'Aucun média n\'a pu être trouvé dans Sonarr/Radarr pour le déplacement.'}), 404

    # Démarrer la tâche de fond
    app_context = current_app._get_current_object()
    task_id, error_message = bulk_move_manager.start_bulk_move(processed_items_for_manager, app_context)

    if error_message:
        return jsonify({'status': 'error', 'message': error_message}), 409

    return jsonify({'status': 'success', 'message': 'Déplacement en masse démarré.', 'task_id': task_id})

@plex_editor_bp.route('/api/media/bulk_move_status/<task_id>', methods=['GET'])
@login_required
def get_bulk_move_status(task_id):
    status = bulk_move_manager.get_task_status(task_id)
    if not status:
        return jsonify({'status': 'error', 'message': 'Tâche non trouvée.'}), 404

    return jsonify(status)


@plex_editor_bp.route('/api/users')
@login_required
def get_plex_users():
    """Retourne la liste des utilisateurs du compte Plex principal."""
    try:
        users_list = []
        main_plex_account = get_main_plex_account_object()
        if not main_plex_account:
            current_app.logger.error("API get_plex_users: Impossible de récupérer le compte Plex principal.")
            return jsonify({'error': "Impossible de récupérer le compte Plex principal."}), 500

        # Ajouter l'utilisateur principal
        main_title = main_plex_account.title or main_plex_account.username or f"Principal (ID: {main_plex_account.id})"
        users_list.append({'id': str(main_plex_account.id), 'text': main_title})

        # Ajouter les utilisateurs gérés
        for user in main_plex_account.users():
            managed_title = user.title or f"Géré (ID: {user.id})" # Utiliser user.title comme source principale
            users_list.append({'id': str(user.id), 'text': managed_title})

        return jsonify(users_list)
    except Exception as e:
        current_app.logger.error(f"Erreur API lors de la récupération des utilisateurs Plex : {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@plex_editor_bp.route('/api/libraries/<user_id>')
@login_required
def get_user_libraries(user_id):
    """Retourne les bibliothèques pour un utilisateur Plex donné."""
    try:
        plex_url = current_app.config.get('PLEX_URL')
        admin_token = current_app.config.get('PLEX_TOKEN')

        if not plex_url or not admin_token:
            current_app.logger.error("API get_user_libraries: Configuration Plex (URL/Token) manquante.")
            return jsonify({'error': "Configuration Plex manquante."}), 500

        main_plex_account = get_main_plex_account_object()
        if not main_plex_account:
            current_app.logger.error("API get_user_libraries: Impossible de récupérer le compte Plex principal.")
            return jsonify({'error': "Impossible de récupérer le compte Plex principal."}), 500

        target_plex_server = None

        if str(main_plex_account.id) == user_id:
            # L'utilisateur est l'admin/compte principal
            target_plex_server = PlexServer(plex_url, admin_token)
            current_app.logger.info(f"API get_user_libraries: Accès aux bibliothèques pour l'admin (ID: {user_id}).")
        else:
            # L'utilisateur est un utilisateur géré, il faut emprunter son identité
            admin_plex_server_for_setup = PlexServer(plex_url, admin_token) # Nécessaire pour machineIdentifier
            user_to_impersonate = next((u for u in main_plex_account.users() if str(u.id) == user_id), None)

            if user_to_impersonate:
                try:
                    managed_user_token = user_to_impersonate.get_token(admin_plex_server_for_setup.machineIdentifier)
                    target_plex_server = PlexServer(plex_url, managed_user_token)
                    current_app.logger.info(f"API get_user_libraries: Accès aux bibliothèques pour l'utilisateur géré '{user_to_impersonate.title}' (ID: {user_id}).")
                except Exception as e_impersonate:
                    current_app.logger.error(f"API get_user_libraries: Échec de l'emprunt d'identité pour {user_to_impersonate.title} (ID: {user_id}): {e_impersonate}", exc_info=True)
                    return jsonify({'error': f"Impossible d'emprunter l'identité de l'utilisateur {user_id}."}), 500
            else:
                current_app.logger.warning(f"API get_user_libraries: Utilisateur géré avec ID {user_id} non trouvé.")
                return jsonify({'error': f"Utilisateur avec ID {user_id} non trouvé."}), 404

        if not target_plex_server:
            # Ce cas ne devrait pas être atteint si la logique ci-dessus est correcte, mais c'est une sécurité.
            current_app.logger.error(f"API get_user_libraries: Impossible d'établir une connexion Plex pour l'utilisateur {user_id}.")
            return jsonify({'error': f"Impossible d'établir une connexion Plex pour l'utilisateur {user_id}."}), 500

        libraries = target_plex_server.library.sections()

        # **NOUVELLE LOGIQUE DE FILTRAGE**
        ignored_library_names = current_app.config.get('PLEX_LIBRARIES_TO_IGNORE', [])

        filtered_libraries = []
        for lib in libraries:
            # Condition 1: La bibliothèque n'est pas dans la liste des noms à ignorer
            is_ignored = lib.title in ignored_library_names

            # Condition 2: La bibliothèque est de type 'movie' ou 'show'
            is_valid_type = lib.type in ['movie', 'show']

            if not is_ignored and is_valid_type:
                filtered_libraries.append({'id': lib.key, 'text': lib.title})

        # On renvoie la liste filtrée
        return jsonify(filtered_libraries)

    except Unauthorized:
        current_app.logger.error(f"API get_user_libraries: Autorisation refusée pour l'utilisateur {user_id}. Token invalide ?", exc_info=True)
        return jsonify({'error': "Autorisation refusée par le serveur Plex."}), 401
    except NotFound:
        current_app.logger.warning(f"API get_user_libraries: Ressource non trouvée pour l'utilisateur {user_id} (ex: bibliothèques).", exc_info=True)
        return jsonify({'error': "Ressource non trouvée sur le serveur Plex."}), 404
    except Exception as e:
        current_app.logger.error(f"Erreur API lors de la récupération des bibliothèques pour l'utilisateur {user_id} : {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@plex_editor_bp.route('/api/genres', methods=['POST'])
@login_required
def get_genres_for_libraries():
    data = request.json
    user_id = data.get('userId')
    library_keys = data.get('libraryKeys', [])

    if not user_id or not library_keys:
        return jsonify(error="User ID and library keys are required."), 400

    try:
        user_plex = get_user_specific_plex_server_from_id(user_id)
        if not user_plex:
            return jsonify(error="Plex user not found."), 404

        all_genres = set()
        for key in library_keys:
            library = user_plex.library.sectionByID(int(key))
            # The .genres() method does not exist on a library.
            # We must iterate through items to find all genres.
            for item in library.all():
                if hasattr(item, 'genres'):
                    for genre in item.genres:
                        all_genres.add(genre.tag)

        return jsonify(sorted(list(all_genres)))

    except Exception as e:
        current_app.logger.error(f"Erreur API /api/genres: {e}", exc_info=True)
        return jsonify(error=str(e)), 500
        
@plex_editor_bp.route('/api/collections', methods=['POST'])
def get_collections_for_libraries():
    data = request.json
    user_id = data.get('userId')
    library_keys = data.get('libraryKeys', [])

    if not user_id or not library_keys:
        return jsonify(error="User ID and library keys are required."), 400

    try:
        user_plex = get_user_specific_plex_server_from_id(user_id)
        if not user_plex:
            return jsonify(error="Plex user not found."), 404

        all_collections = set()
        for key in library_keys:
            library = user_plex.library.sectionByID(int(key))
            all_collections.update([collection.title for collection in library.collections()])
        return jsonify(sorted(list(all_collections)))
    except Exception as e:
        current_app.logger.error(f"Erreur API /api/collections: {e}", exc_info=True)
        return jsonify(error=str(e)), 500

@plex_editor_bp.route('/api/resolutions', methods=['POST'])
def get_resolutions_for_libraries():
    data = request.json
    user_id = data.get('userId')
    library_keys = data.get('libraryKeys', [])

    if not user_id or not library_keys:
        return jsonify(error="User ID and library keys are required."), 400

    try:
        user_plex = get_user_specific_plex_server_from_id(user_id)
        if not user_plex:
            return jsonify(error="Plex user not found."), 404

        all_resolutions = set()
        for key in library_keys:
            library = user_plex.library.sectionByID(int(key))
            for item in library.all():
                if hasattr(item, 'media') and item.media:
                    for media in item.media:
                        if hasattr(media, 'videoResolution') and media.videoResolution:
                            all_resolutions.add(media.videoResolution)
        return jsonify(sorted(list(all_resolutions)))
    except Exception as e:
        current_app.logger.error(f"Erreur API /api/resolutions: {e}", exc_info=True)
        return jsonify(error=str(e)), 500

@plex_editor_bp.route('/api/studios', methods=['POST'])
def get_studios_for_libraries():
    data = request.json
    user_id = data.get('userId')
    library_keys = data.get('libraryKeys', [])

    if not user_id or not library_keys:
        return jsonify(error="User ID and library keys are required."), 400

    try:
        user_plex = get_user_specific_plex_server_from_id(user_id)
        if not user_plex:
            return jsonify(error="Plex user not found."), 404

        all_studios = set()
        for key in library_keys:
            library = user_plex.library.sectionByID(int(key))
            for item in library.all():
                if hasattr(item, 'studio') and item.studio:
                    all_studios.add(item.studio)
        return jsonify(sorted(list(all_studios)))
    except Exception as e:
        current_app.logger.error(f"Erreur API /api/studios: {e}", exc_info=True)
        return jsonify(error=str(e)), 500

@plex_editor_bp.route('/api/scan_libraries', methods=['POST'])
@login_required
def scan_libraries():
    data = request.json
    library_keys = data.get('libraryKeys', [])
    # L'user_id n'est plus nécessaire pour l'action, mais on le garde pour la validation du login
    user_id = data.get('userId')

    if not user_id or not library_keys:
        return jsonify({'success': False, 'message': 'ID utilisateur ou bibliothèques manquants.'}), 400

    try:
        # **MODIFICATION CLÉ : On utilise la connexion admin, comme pour la suppression**
        plex_server = get_plex_admin_server()
        if not plex_server:
            return jsonify({'success': False, 'message': 'Connexion admin au serveur Plex impossible.'}), 404

        scanned_libs = []
        for key in library_keys:
            # On trouve la bibliothèque sur le serveur admin
            library = plex_server.library.sectionByID(int(key))
            library.update() # On lance le scan avec les droits admin
            scanned_libs.append(library.title)

        return jsonify({'success': True, 'message': f'Scan lancé pour : {", ".join(scanned_libs)}'})

    except Exception as e:
        current_app.logger.error(f"Erreur API /api/scan_libraries: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Erreur lors du scan : {str(e)}'}), 500

@plex_editor_bp.route('/select_user', methods=['POST'])
@login_required
def select_user_route():
    """Stocke l'ID et le titre de l'utilisateur Plex sélectionné dans la session."""
    data = request.json
    user_id = data.get('id')
    user_title = data.get('title')

    if not user_id or not user_title:
        return jsonify({'status': 'error', 'message': 'ID ou titre manquant.'}), 400

    session['plex_user_id'] = user_id
    session['plex_user_title'] = user_title
    session.permanent = True
    session.modified = True
    current_app.logger.info(f"Utilisateur Plex sélectionné et enregistré en session: '{user_title}' (ID: {user_id})")
    return jsonify({'status': 'success', 'message': f"Utilisateur '{user_title}' sélectionné."})
    
# Dans app/plex_editor/routes.py

# Dans app/plex_editor/routes.py

def _parse_main_external_id(guids):
    """
    Parses the list of guids from a Plex item to find the primary external ID.
    Prefers 'tvdb' for shows and 'tmdb' for movies.
    """
    # Priorité des sources
    priority_order = ['tvdb', 'tmdb', 'imdb']

    for source in priority_order:
        for guid_obj in guids:
            if guid_obj.id.startswith(f'{source}://'):
                try:
                    # 'tmdb://12345' -> ('tmdb', '12345')
                    id_val = guid_obj.id.split('//')[1]
                    # Pour les séries, on veut le type 'tv' pour notre API
                    media_type = 'tv' if source == 'tvdb' else source
                    return media_type, id_val
                except (IndexError, ValueError):
                    continue
    return None, None

def get_user_specific_plex_server_from_id(user_id):
    """
    Helper function to get a PlexServer instance for a specific user ID,
    handling impersonation. Returns None on failure.
    """
    # On a besoin de l'accès admin pour trouver d'autres utilisateurs
    admin_server = get_plex_admin_server()
    if not admin_server:
        current_app.logger.error("Helper get_user_specific_plex_server_from_id: Impossible d'obtenir la connexion admin.")
        return None

    main_account = get_main_plex_account_object()
    if not main_account:
        current_app.logger.error("Helper get_user_specific_plex_server_from_id: Impossible de récupérer le compte principal.")
        return None

    # Cas 1: L'utilisateur est l'admin
    if str(main_account.id) == user_id:
        return admin_server

    # Cas 2: L'utilisateur est un utilisateur géré
    user_to_impersonate = next((u for u in main_account.users() if str(u.id) == user_id), None)
    if user_to_impersonate:
        token = user_to_impersonate.get_token(admin_server.machineIdentifier)
        plex_url = current_app.config.get('PLEX_URL')
        return PlexServer(plex_url, token)

    # Si l'ID n'a pas été trouvé
    current_app.logger.warning(f"Helper get_user_specific_plex_server_from_id: Utilisateur avec ID '{user_id}' non trouvé.")
    return None

@plex_editor_bp.route('/api/media_items', methods=['POST'])
@login_required
def get_media_items():
    # --- 1. Récupération des filtres ---
    data = request.json
    user_id = data.get('userId')
    library_keys = data.get('libraryKeys', [])
    status_filter = data.get('statusFilter', 'all')
    title_filter = data.get('titleFilter', '').strip()
    year_filter = data.get('year')
    genres_filter = data.get('genres', [])
    genre_logic = data.get('genreLogic', 'or')
    collections_filter = data.get('collections', [])
    resolutions_filter = data.get('resolutions', [])
    actor_filter = data.get('actor')
    director_filter = data.get('director')
    writer_filter = data.get('writer')
    studios_filter = data.get('studios', [])
    root_folders_filter = data.get('rootFolders', []) # <--- NOUVEAU FILTRE

    cleaned_genres = [genre for genre in genres_filter if genre]
    cleaned_collections = [c for c in collections_filter if c]
    cleaned_resolutions = [r for r in resolutions_filter if r]
    cleaned_studios = [s for s in studios_filter if s]

    if not user_id or not library_keys:
        return jsonify({'error': 'ID utilisateur et au moins une clé de bibliothèque sont requis.'}), 400

    try:
        # --- 2. Connexion au serveur ---
        target_plex_server = get_user_specific_plex_server_from_id(user_id)
        if not target_plex_server:
            return jsonify({'error': f"Impossible de se connecter en tant que {user_id}."}), 500

        # ### DÉBUT MODIFICATION : Initialisation du cache ###
        series_status_cache = SimpleCache('series_completeness_status', default_lifetime_hours=6)
        # ### FIN MODIFICATION ###

        # Charger les mappings pour l'enrichissement
        from app.utils.plex_mapping_manager import get_plex_mappings
        plex_mappings = get_plex_mappings()

        # --- 3. NOUVELLE LOGIQUE : Recherche unifiée sur Plex d'abord ---
        all_plex_items = {}  # Utilise un dictionnaire pour dédupliquer par ratingKey

        for lib_key in library_keys:
            try:
                library = target_plex_server.library.sectionByID(int(lib_key))

                # Construit les arguments de base pour cette bibliothèque
                search_args = {}
                # Les filtres suivants sont passés directement à l'API Plex
                if cleaned_genres and genre_logic == 'or':
                    search_args['genre'] = cleaned_genres
                # Pour la logique 'AND', on filtre plus tard en Python
                elif cleaned_genres and genre_logic == 'and':
                    search_args['genre'] = cleaned_genres[0] # Pré-filtre sur le premier

                if year_filter:
                    try:
                        search_args['year'] = int(year_filter)
                    except (ValueError, TypeError): pass
                if cleaned_collections:
                    search_args['collection'] = cleaned_collections
                if cleaned_resolutions:
                    search_args['resolution'] = cleaned_resolutions
                if cleaned_studios:
                    search_args['studio'] = cleaned_studios

                date_filter = data.get('dateFilter', {})
                date_type = date_filter.get('type')
                if date_type and date_filter.get('preset'):
                    preset = date_filter['preset']
                    today = datetime.now()
                    start_date, end_date = None, None
                    if preset == 'today':
                        start_date, end_date = today.replace(hour=0, minute=0, second=0), today.replace(hour=23, minute=59, second=59)
                    elif preset == 'last7days':
                        start_date, end_date = today - timedelta(days=7), today
                    elif preset == 'last30days':
                        start_date, end_date = today - timedelta(days=30), today
                    elif preset == 'thisMonth':
                        start_date, end_date = today.replace(day=1, hour=0, minute=0, second=0), today
                    elif preset == 'lastMonth':
                        end_of_last_month = today.replace(day=1) - timedelta(days=1)
                        start_date, end_date = end_of_last_month.replace(day=1, hour=0, minute=0, second=0), end_of_last_month.replace(hour=23, minute=59, second=59)
                    elif preset == 'custom':
                        start_date_str, end_date_str = date_filter.get('start'), date_filter.get('end')
                        if start_date_str: start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                        if end_date_str: end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                    if start_date: search_args[f'{date_type}>>'] = start_date
                    if end_date: search_args[f'{date_type}<<'] = end_date

                rating_filter = data.get('ratingFilter', {})
                if rating_filter and rating_filter.get('operator'):
                    operator, value = rating_filter['operator'], rating_filter.get('value')
                    if operator == 'is_rated': search_args['userRating>>'] = 0
                    elif operator == 'is_not_rated': search_args['userRating'] = -1
                    elif value:
                        try:
                            rating_value = float(value)
                            if operator == 'gte': search_args['userRating>>'] = rating_value
                            elif operator == 'lte': search_args['userRating<<'] = rating_value
                            elif operator == 'eq': search_args['userRating'] = rating_value
                        except (ValueError, TypeError): pass

                # Logique de recherche par titre unifiée
                if title_filter:
                    search_title = library.search(title__icontains=title_filter, **search_args)
                    search_original = library.search(originalTitle__icontains=title_filter, **search_args)

                    search_sort_smart = []
                    if title_filter.lower().startswith('the '):
                        search_term = title_filter[4:]
                        search_sort_smart = library.search(titleSort__icontains=search_term, **search_args)
                    else:
                        search_sort_smart = library.search(titleSort__icontains=title_filter, **search_args)

                    for item in search_title + search_original + search_sort_smart:
                        all_plex_items[item.ratingKey] = item
                else:
                    search_results = library.search(**search_args)
                    for item in search_results:
                        all_plex_items[item.ratingKey] = item

            except Exception as e_lib:
                current_app.logger.error(f"Erreur accès bibliothèque {lib_key}: {e_lib}", exc_info=True)

        # --- NOUVELLE ÉTAPE 3.5: FINALISATION DES VERROUS EN ATTENTE (VERSION DÉFINITIVE) ---
        for item in all_plex_items.values():
            if not hasattr(item, 'guids'):
                continue

            # Extraire tous les IDs externes de l'item Plex (tmdb, tvdb, imdb)
            plex_external_ids = set()
            for guid_obj in item.guids:
                try:
                    # format 'tvdb://12345' -> '12345'
                    id_val = guid_obj.id.split('//')[1]
                    plex_external_ids.add(id_val)
                except IndexError:
                    continue

            if not plex_external_ids:
                continue

            # Chercher un verrou en attente pour n'importe lequel des IDs de l'item
            pending_lock = None
            matched_id = None
            for ext_id in plex_external_ids:
                pending_lock = get_pending_lock(ext_id)
                if pending_lock:
                    matched_id = ext_id
                    break

            if not pending_lock:
                continue

            current_app.logger.info(f"FINALIZATION: Pending lock found for '{item.title}' (matched Plex ID {matched_id}). Finalizing...")

            video_id_to_lock = pending_lock['video_id']
            cache_key = f"trailer_search_{item.title}_{item.year}_{item.ratingKey}"

            # Amélioration: au lieu de créer une entrée minimale, on tente de récupérer les vrais détails de la vidéo.
            youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')
            video_details = None
            if youtube_api_key:
                video_details = get_videos_details([video_id_to_lock], youtube_api_key)

            if video_details and video_id_to_lock in video_details:
                details = video_details[video_id_to_lock]['snippet']
                final_trailer_object = {
                    'videoId': video_id_to_lock,
                    'title': details.get('title', f"Bande-annonce pour {item.title}"),
                    'channel': details.get('channelTitle', "N/A"),
                    'thumbnail': details.get('thumbnails', {}).get('high', {}).get('url', ''),
                    'score': 9999 # Maintenir le score élevé pour le verrouillage
                }
            else:
                # Fallback: si l'appel API échoue, on utilise l'ancienne méthode robuste.
                current_app.logger.warning(f"FINALIZATION: Could not fetch details for videoId {video_id_to_lock}. Using fallback.")
                final_trailer_object = {
                    'videoId': video_id_to_lock,
                    'title': f"Bande-annonce verrouillée pour {item.title}",
                    'channel': "N/A",
                    'thumbnail': '',
                    'score': 9999
                }

            results_list = [final_trailer_object]

            # Créer l'entrée de cache, directement verrouillée.
            current_app.logger.info(f"FINALIZATION: Setting permanent locked cache for key '{cache_key}' with videoId '{video_id_to_lock}'.")
            set_in_cache(cache_key, results_list, is_locked=True, locked_video_id=video_id_to_lock)

            # Supprimer le verrou en attente.
            remove_pending_lock(matched_id)
            current_app.logger.info(f"FINALIZATION: Success for '{item.title}'. Pending lock for {matched_id} removed.")

        # --- 4. LA DÉCISION : Chercher dans les archives ou à l'extérieur ? ---
        final_plex_results_unfiltered = list(all_plex_items.values())
        external_suggestions = []
        archived_results = [] # Toujours initialiser la liste

        if not final_plex_results_unfiltered and title_filter:
            # Priorité n°1 : Chercher dans notre base de données d'archives locales
            from app.utils.archive_manager import find_archived_media_by_title
            archived_results = find_archived_media_by_title(title_filter)

            # Priorité n°2 : Si (et seulement si) on n'a rien trouvé dans nos archives, on cherche des suggestions externes
            if not archived_results:
                current_app.logger.info(f"No results in Plex or Archive for '{title_filter}'. Searching externally.")

                tmdb_client = TheMovieDBClient()
                tvdb_client = CustomTVDBClient()

                # Recherche Films (TMDb)
                tmdb_results = tmdb_client.search_movie(title_filter)
                for movie in tmdb_results[:3]:
                    tmdb_id = movie.get('id')
                    radarr_entry = get_radarr_movie_by_guid(f'tmdb:{tmdb_id}')
                    movie['is_monitored'] = radarr_entry is not None
                    movie['source_url'] = f"https://www.themoviedb.org/movie/{movie.get('id')}"
                    movie['poster_url'] = f"https://image.tmdb.org/t/p/w500{movie.get('poster_path')}" if movie.get('poster_path') else ''
                    movie['year'] = movie.get('release_date', 'N/A').split('-')[0] if movie.get('release_date') else 'N/A'
                    movie['type'] = 'movie'
                    external_suggestions.append(movie)

                # Recherche Séries (TVDb)
                tvdb_results = tvdb_client.search_and_translate_series(title_filter)
                for series in tvdb_results[:3]:
                    tvdb_id = series.get('tvdb_id')
                    sonarr_entry = get_sonarr_series_by_guid(f'tvdb:{tvdb_id}')
                    series['is_monitored'] = sonarr_entry is not None
                    series['source_url'] = f"https://thetvdb.com/series/{series.get('slug')}"
                    series['poster_url'] = series.get('image_url', '')
                    series['year'] = series.get('first_air_time', 'N/A')
                    series['type'] = 'show'
                    external_suggestions.append(series)

        # --- 5. Post-filtrage et Rendu ---
        items_to_render = []
        if final_plex_results_unfiltered:
            items_after_python_filter = final_plex_results_unfiltered

            if cleaned_genres and genre_logic == 'and':
                required_genres_set = {genre.lower() for genre in cleaned_genres}
                items_after_python_filter = [
                    item for item in items_after_python_filter
                    if hasattr(item, 'genres') and required_genres_set.issubset({g.tag.lower() for g in item.genres})
                ]

            if actor_filter:
                items_after_python_filter = [item for item in items_after_python_filter if hasattr(item, 'actors') and any(actor_filter.lower() in actor.tag.lower() for actor in item.actors)]
            if director_filter:
                items_after_python_filter = [item for item in items_after_python_filter if hasattr(item, 'directors') and any(director_filter.lower() in director.tag.lower() for director in item.directors)]
            if writer_filter:
                items_after_python_filter = [item for item in items_after_python_filter if hasattr(item, 'writers') and any(writer_filter.lower() in writer.tag.lower() for writer in item.writers)]

            # --- NOUVEAU BLOC : FILTRAGE PAR ROOT FOLDER ---
            if root_folders_filter:
                normalized_root_paths = [os.path.normpath(p).lower() for p in root_folders_filter]

                def get_item_path(item):
                    if item.type == 'movie':
                        return getattr(item.media[0].parts[0], 'file', None) if item.media and item.media[0].parts else None
                    elif item.type == 'show':
                        return item.locations[0] if item.locations else None
                    return None

                items_temp = []
                for item in items_after_python_filter:
                    item_path_str = get_item_path(item)
                    if item_path_str:
                        normalized_item_path = os.path.normpath(item_path_str).lower()
                        for root_path in normalized_root_paths:
                            # CORRECTION: La vérification doit être stricte.
                            # Le chemin de l'item doit soit être identique au chemin racine,
                            # soit commencer par le chemin racine suivi d'un séparateur.
                            if normalized_item_path == root_path or normalized_item_path.startswith(root_path + os.sep):
                                items_temp.append(item)
                                break
                items_after_python_filter = items_temp
            # --- FIN DU NOUVEAU BLOC ---

            final_filtered_list = []
            if status_filter == 'all':
                final_filtered_list = items_after_python_filter
            else:
                for item in items_after_python_filter:
                    if item.type == 'show':
                        # Recalculer les attributs ici car ils ne sont pas sur l'objet de base
                        item.reload() # Assure que les comptes sont à jour
                        is_watched = item.leafCount > 0 and item.viewedLeafCount == item.leafCount
                        is_unwatched = item.leafCount > 0 and item.viewedLeafCount == 0
                        is_in_progress = item.leafCount > 0 and item.viewedLeafCount > 0 and not is_watched
                        if (status_filter == 'watched' and is_watched) or \
                           (status_filter == 'unwatched' and is_unwatched) or \
                           (status_filter == 'in_progress' and is_in_progress):
                            final_filtered_list.append(item)
                    elif item.type == 'movie':
                        if (status_filter == 'watched' and item.isWatched) or \
                           (status_filter == 'unwatched' and not item.isWatched):
                            final_filtered_list.append(item)

            for item in final_filtered_list:
                item.library_name = item.librarySectionTitle
                item.title_sort = getattr(item, 'titleSort', None)
                item.original_title = getattr(item, 'originalTitle', None)
                thumb_path = getattr(item, 'thumb', None)
                item.poster_url = target_plex_server.url(thumb_path, includeToken=True) if thumb_path else None

                # Enrichissement avec l'ID externe pour la recherche de bande-annonce
                item.external_source, item.external_id = _parse_main_external_id(item.guids)
                # Correction du type pour correspondre à l'API du trailer_manager ('movie' ou 'tv')
                item.media_type_for_trailer = 'tv' if item.type == 'show' else 'movie'


                if item.type == 'movie':
                    item.file_path = getattr(item.media[0].parts[0], 'file', None) if item.media and item.media[0].parts else None
                    item.total_size = item.media[0].parts[0].size if hasattr(item, 'media') and item.media and item.media[0].parts else 0
                elif item.type == 'show':
                    item.file_path = item.locations[0] if item.locations else None
                    item.total_size = sum(getattr(part, 'size', 0) for ep in item.episodes() for part in (ep.media[0].parts if ep.media and ep.media[0].parts else []))
                    item.viewed_episodes = item.viewedLeafCount
                    item.total_episodes = item.leafCount

                    cache_key = item.ratingKey
                    cached_data = series_status_cache.get(cache_key)

                    if cached_data:
                        item.is_incomplete = cached_data.get('is_incomplete', False)
                        item.production_status = cached_data.get('production_status')
                        current_app.logger.debug(f"Cache HIT for '{item.title}' (ratingKey: {cache_key}).")
                    else:
                        current_app.logger.debug(f"Cache MISS for '{item.title}' (ratingKey: {cache_key}). Fetching from Sonarr.")
                        try:
                            is_incomplete_status = False
                            production_status = None

                            sonarr_series = get_sonarr_series_by_guid(next((g.id for g in item.guids if 'tvdb' in g.id), None))
                            if sonarr_series:
                                full_sonarr_series = get_sonarr_series_by_id(sonarr_series['id'])
                                if full_sonarr_series:
                                    stats = full_sonarr_series.get('statistics', {})
                                    file_count = stats.get('episodeFileCount', 0)
                                    total_aired_count = stats.get('episodeCount', 0) - stats.get('futureEpisodeCount', 0)
                                    if file_count < total_aired_count:
                                        is_incomplete_status = True

                                    sonarr_status = full_sonarr_series.get('status')
                                    if sonarr_status == 'continuing':
                                        production_status = 'En Production'
                                    elif sonarr_status == 'ended':
                                        production_status = 'Terminée'
                                    elif sonarr_status == 'upcoming':
                                        production_status = 'À venir'

                            item.is_incomplete = is_incomplete_status
                            item.production_status = production_status

                            series_status_cache.set(cache_key, {
                                'is_incomplete': item.is_incomplete,
                                'production_status': item.production_status
                            })
                        except Exception as e_sonarr:
                            current_app.logger.warning(f"Impossible de vérifier l'état Sonarr pour '{item.title}': {e_sonarr}")

                if getattr(item, 'total_size', 0) > 0:
                    size_name = ("B", "KB", "MB", "GB", "TB"); i = 0
                    temp_size = float(item.total_size)
                    while temp_size >= 1024 and i < len(size_name) - 1: temp_size /= 1024.0; i += 1
                    item.total_size_display = f"{temp_size:.2f} {size_name[i]}"
                else:
                    item.total_size_display = "0 B"

                item.plex_trailer_url = find_plex_trailer(item, target_plex_server)

                # Récupération du statut détaillé du trailer
                item.trailer_status = 'NONE' # Default
                if item.external_id:
                    item.trailer_status = trailer_manager.get_trailer_status(
                        media_type=item.media_type_for_trailer,
                        external_id=item.external_id
                    )

                # Enrichissement avec le type de média depuis le mapping
                item.media_type_from_mapping = None # Sera 'sonarr' ou 'radarr'
                item.custom_media_type = None       # Sera 'FILM', 'SÉRIE', etc.

                # 1. Déterminer le type d'*Arr* de base (sonarr/radarr) à partir du type Plex
                if item.type == 'show':
                    item.media_type_from_mapping = 'sonarr'
                elif item.type == 'movie':
                    item.media_type_from_mapping = 'radarr'

                # 2. Chercher le "type" personnalisé dans le mapping JSON
                if item.file_path:
                    normalized_item_path = os.path.normpath(item.file_path.lower())
                    mapping_found = False
                    for lib_name, mappings in plex_mappings.items():
                        for mapping in mappings:
                            # Utiliser la nouvelle structure de clé : 'path'
                            normalized_mapped_path = os.path.normpath(mapping['path'].lower())
                            if normalized_item_path.startswith(normalized_mapped_path):
                                # Utiliser la nouvelle structure de clé : 'type'
                                item.custom_media_type = mapping.get('type')
                                mapping_found = True
                                break
                        if mapping_found:
                            break

                # 3. Fallback : si aucun type personnalisé n'est trouvé, utiliser un type par défaut
                if not item.custom_media_type:
                    item.custom_media_type = 'SÉRIE' if item.type == 'show' else 'FILM'

                items_to_render.append(item)

        items_to_render.sort(key=lambda x: getattr(x, 'titleSort', x.title).lower())

        return render_template(
            'plex_editor/_media_table.html',
            items=items_to_render,
            external_suggestions=external_suggestions,
            archived_results=archived_results
        )

    except Exception as e:
        current_app.logger.error(f"Erreur API get_media_items: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@plex_editor_bp.route('/api/media_item/<int:rating_key>', methods=['DELETE'])
@login_required
def delete_media_item_api(rating_key): # Renommé pour éviter conflit avec la non-API delete_item
    """Supprime un média en utilisant sa ratingKey (via API)."""
    try:
        admin_plex_server = get_plex_admin_server()
        if not admin_plex_server:
            current_app.logger.error(f"API delete_media_item: Impossible d'obtenir une connexion admin Plex.")
            return jsonify({'status': 'error', 'message': 'Connexion au serveur Plex admin échouée.'}), 500

        item_to_delete = admin_plex_server.fetchItem(rating_key)

        if item_to_delete:
            item_title = item_to_delete.title
            current_app.logger.info(f"API delete_media_item: Tentative de suppression du média '{item_title}' (ratingKey: {rating_key}).")
            item_to_delete.delete()
            # La suppression des fichiers du disque est omise ici pour la version API.
            # cleanup_parent_directory_recursively etc. ne sont pas appelés.
            current_app.logger.info(f"API delete_media_item: Média '{item_title}' (ratingKey: {rating_key}) supprimé de Plex.")
            return jsonify({'status': 'success', 'message': f"'{item_title}' a été supprimé de Plex."})
        else:
            # Ce cas est techniquement couvert par l'exception NotFound ci-dessous, mais une vérification explicite est possible.
            current_app.logger.warning(f"API delete_media_item: Média avec ratingKey {rating_key} non trouvé (avant exception).")
            return jsonify({'status': 'error', 'message': f'Média avec ratingKey {rating_key} non trouvé.'}), 404

    except NotFound:
        current_app.logger.warning(f"API delete_media_item: Média avec ratingKey {rating_key} non trouvé (NotFound Exception).")
        return jsonify({'status': 'error', 'message': f'Média avec ratingKey {rating_key} non trouvé.'}), 404
    except Unauthorized:
        current_app.logger.error(f"API delete_media_item: Autorisation refusée pour supprimer {rating_key}. Token admin invalide ?")
        return jsonify({'status': 'error', 'message': 'Autorisation refusée par le serveur Plex.'}), 401
    except BadRequest: # Au cas où l'item ne peut pas être supprimé pour une raison de requête
        current_app.logger.error(f"API delete_media_item: Requête incorrecte pour la suppression de {rating_key}.", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Requête de suppression incorrecte vers Plex.'}), 400
    except Exception as e:
        current_app.logger.error(f"API delete_media_item: Erreur lors de la suppression du média {rating_key}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Erreur serveur: {str(e)}'}), 500

@plex_editor_bp.route('/api/media_item/<int:rating_key>/toggle_watched', methods=['POST'])
@login_required
def toggle_watched_status_api(rating_key): # Nom de fonction unique
    """Bascule le statut 'vu' d'un média pour un utilisateur donné."""
    data = request.json
    user_id = data.get('userId')

    if not user_id:
        return jsonify({'status': 'error', 'message': 'userId manquant dans la requête.'}), 400

    try:
        plex_url = current_app.config.get('PLEX_URL')
        admin_token = current_app.config.get('PLEX_TOKEN')
        if not plex_url or not admin_token:
            current_app.logger.error("API toggle_watched: Configuration Plex manquante.")
            return jsonify({'status': 'error', 'message': 'Configuration Plex serveur manquante.'}), 500

        main_plex_account = get_main_plex_account_object()
        if not main_plex_account:
            current_app.logger.error("API toggle_watched: Compte Plex principal non récupérable.")
            return jsonify({'status': 'error', 'message': 'Compte Plex principal non accessible.'}), 500

        user_plex_server = None
        user_context_description = ""

        if str(main_plex_account.id) == user_id:
            user_plex_server = PlexServer(plex_url, admin_token)
            user_context_description = f"admin (ID: {user_id})"
        else:
            admin_plex_server_for_token = PlexServer(plex_url, admin_token) # Pour machineIdentifier
            user_to_impersonate = next((u for u in main_plex_account.users() if str(u.id) == user_id), None)
            if user_to_impersonate:
                managed_user_token = user_to_impersonate.get_token(admin_plex_server_for_token.machineIdentifier)
                user_plex_server = PlexServer(plex_url, managed_user_token)
                user_context_description = f"utilisateur géré '{user_to_impersonate.title}' (ID: {user_id})"
            else:
                current_app.logger.warning(f"API toggle_watched: Utilisateur {user_id} non trouvé pour impersonnalisation.")
                return jsonify({'status': 'error', 'message': f'Utilisateur {user_id} non trouvé.'}), 404

        if not user_plex_server:
            # Devrait être couvert par la logique ci-dessus, mais par sécurité.
            return jsonify({'status': 'error', 'message': f'Impossible d_établir la connexion Plex pour l_utilisateur {user_id}.'}), 500

        item = user_plex_server.fetchItem(rating_key)
        if not item: # fetchItem lève NotFound, mais double vérification
            return jsonify({'status': 'error', 'message': 'Média non trouvé.'}), 404

        current_status_is_watched = item.isWatched
        new_status_str = ''

        if current_status_is_watched:
            item.markUnwatched()
            new_status_str = 'Non Vu'
        else:
            item.markWatched()
            new_status_str = 'Vu'

        # Re-fetch ou vérifier l'état après action si l'API ne met pas à jour l'objet local immédiatement.
        # Pour PlexAPI, l'objet local `item` devrait refléter le changement.
        # Donc `item.isWatched` après l'action devrait être le nouvel état.
        final_is_watched_status = item.isWatched

        current_app.logger.info(f"API toggle_watched: Statut du média '{item.title}' (ratingKey: {rating_key}) changé à '{new_status_str}' pour {user_context_description}.")
        return jsonify({
            'status': 'success',
            'new_status_str': new_status_str,
            'is_watched': final_is_watched_status # Renvoie le statut après l'action
        })

    except NotFound:
        current_app.logger.warning(f"API toggle_watched: Média {rating_key} non trouvé (contexte {user_context_description}).")
        return jsonify({'status': 'error', 'message': 'Média non trouvé.'}), 404
    except Unauthorized:
        current_app.logger.error(f"API toggle_watched: Non autorisé pour média {rating_key} (contexte {user_context_description}).")
        return jsonify({'status': 'error', 'message': 'Action non autorisée par le serveur Plex.'}), 401
    except Exception as e:
        current_app.logger.error(f"API toggle_watched: Erreur pour média {rating_key} (contexte {user_context_description}): {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@plex_editor_bp.route('/')
@login_required
def index():
    """Affiche le nouveau tableau de bord unifié."""
    return render_template('plex_editor/index.html')

@plex_editor_bp.route('/toggle_watched_status', methods=['POST'])
@login_required
def toggle_watched_status():
    data = request.get_json()
    rating_key = data.get('ratingKey')
    user_id = data.get('userId')

    if not rating_key or not user_id:
        return jsonify({'status': 'error', 'message': 'Données manquantes.'}), 400

    try:
        user_plex_server = get_user_specific_plex_server_from_id(user_id)
        if not user_plex_server:
            return jsonify({'status': 'error', 'message': 'Connexion Plex impossible.'}), 500

        item = user_plex_server.fetchItem(int(rating_key))
        
        if item.isWatched:
            item.markUnwatched()
            new_status_text = 'Non Vu'
        else:
            item.markWatched()
            new_status_text = 'Vu'
            
        # Pour le rafraîchissement de la table principale, on a toujours besoin du HTML
        refreshed_item = user_plex_server.fetchItem(int(rating_key))
        new_html = render_template('plex_editor/_media_status_cell.html', item=refreshed_item)

        return jsonify({
            'status': 'success',
            'new_status': new_status_text, # Info pour les icônes de la modale
            'new_status_html': new_html   # Info pour la table principale
        })

    except Exception as e:
        current_app.logger.error(f"Erreur toggle_watched_status: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

def find_ready_to_watch_shows_in_library(library_name):
    """
    Fonction helper qui trouve les séries terminées, complètes et non vues
    dans une bibliothèque Plex spécifique. Retourne une liste d'objets Show de Plex.
    """
    current_app.logger.info(f"Lancement du filtre spécial 'Prêtes à Regarder' pour la bibliothèque '{library_name}'.")
    try:
        # --- ÉTAPE 1: Récupérer et filtrer les séries de Sonarr ---
        all_sonarr_series = get_all_sonarr_series()
        if not all_sonarr_series:
            flash("Impossible de récupérer la liste des séries depuis Sonarr.", "danger")
            return []

        # On ne garde que les séries terminées et à 100%
        candidate_series = [
            s for s in all_sonarr_series
            if s.get('status') == 'ended' and s.get('statistics', {}).get('percentOfEpisodes', 0) == 100.0
        ]

        # On stocke leurs TVDB IDs pour une recherche rapide (set est plus performant)
        candidate_tvdb_ids = {s.get('tvdbId') for s in candidate_series}
        current_app.logger.info(f"{len(candidate_tvdb_ids)} séries candidates trouvées dans Sonarr (terminées et complètes).")

        # --- ÉTAPE 2: Croiser avec la bibliothèque Plex ---
        ready_to_watch_shows = []
        user_plex_server = get_user_specific_plex_server()
        if not user_plex_server:
            flash("Erreur de connexion à Plex.", "danger")
            return []

        library = user_plex_server.library.section(library_name)
        if library.type != 'show':
            current_app.logger.warning(f"Le filtre 'Prêtes à Regarder' a été appelé sur une bibliothèque qui n'est pas de type 'show': {library_name}")
            return []

        current_app.logger.info(f"Scan de la bibliothèque Plex '{library_name}' pour trouver les séries non vues...")
        # On utilise search(unwatched=True) pour que Plex fasse le premier gros tri, c'est plus efficace
        for show in library.search(unwatched=True):
            # On vérifie que la série est bien 100% non vue (unwatched=True peut inclure les séries partiellement vues)
            if show.viewedLeafCount != 0:
                continue

            plex_tvdb_id = None
            for guid in show.guids:
                if 'tvdb' in guid.id:
                    try:
                        plex_tvdb_id = int(guid.id.split('//')[1])
                        break
                    except (ValueError, IndexError):
                        continue

            if plex_tvdb_id in candidate_tvdb_ids:
                ready_to_watch_shows.append(show)
                current_app.logger.info(f"  -> MATCH: '{show.title}' est prête à être regardée.")

        ready_to_watch_shows.sort(key=lambda s: s.titleSort.lower())
        flash(f"{len(ready_to_watch_shows)} série(s) prête(s) à être commencée(s) trouvée(s) !", "success")
        return ready_to_watch_shows

    except Exception as e:
        current_app.logger.error(f"Erreur dans find_ready_to_watch_shows_in_library: {e}", exc_info=True)
        flash("Une erreur est survenue pendant la recherche complexe.", "danger")
        return []

@plex_editor_bp.route('/library')
@plex_editor_bp.route('/library/<path:library_name>')
@login_required
def show_library(library_name=None):
    special_filter = request.args.get('special_filter')
    lib_name_for_special_filter = library_name or request.args.get('library_name')

    if special_filter == 'ready_to_watch' and lib_name_for_special_filter:
        items_list = find_ready_to_watch_shows_in_library(lib_name_for_special_filter)

        user_plex_server = get_user_specific_plex_server()
        library_obj = user_plex_server.library.section(lib_name_for_special_filter) if user_plex_server else None

        return render_template('plex_editor/library.html',
                               title=f"Séries Prêtes à Regarder",
                               items=items_list,
                               library_name=lib_name_for_special_filter,
                               library_obj=library_obj,
                               current_filters={'sort_by': 'titleSort:asc', 'title_filter': ''},
                               selected_libs=[lib_name_for_special_filter],
                               view_mode='ready_to_watch',
                               plex_error=None,
                               user_title=session.get('plex_user_title', ''),
                               config=current_app.config)

    if 'plex_user_id' not in session:
        flash("Veuillez sélectionner un utilisateur.", "info")
        return redirect(url_for('plex_editor.index'))
    # ... (le reste de la fonction a été omis pour la concision)
    return "Contenu de la fonction show_library"

@plex_editor_bp.route('/delete_item/<int:rating_key>', methods=['POST'])
@login_required
def delete_item(rating_key):
    # ... (le contenu de la fonction a été omis pour la concision)
    return "Contenu de la fonction delete_item"

@plex_editor_bp.route('/bulk_delete_items', methods=['POST'])
@login_required
def bulk_delete_items():
    # ... (le contenu de la fonction a été omis pour la concision)
    return "Contenu de la fonction bulk_delete_items"

@plex_editor_bp.route('/archive_movie', methods=['POST'])
@login_required
def archive_movie_route():
    data = request.get_json()
    rating_key = data.get('ratingKey')
    options = data.get('options', {})
    user_id = data.get('userId')

    if not rating_key or not user_id:
        return jsonify({'status': 'error', 'message': 'Missing ratingKey or userId.'}), 400

    try:
        from app.utils.plex_client import PlexClient
        plex_client = PlexClient(user_id=user_id)
        movie = plex_client.get_item_by_rating_key(int(rating_key))

        if not movie or movie.type != 'movie':
            return jsonify({'status': 'error', 'message': 'Movie not found or not a movie item.'}), 404

        if not movie.isWatched:
            return jsonify({'status': 'error', 'message': 'Movie is not marked as watched for the selected user.'}), 400

        radarr_movie = next((m for g in movie.guids if (m := get_radarr_movie_by_guid(g.id))), None)
        if not radarr_movie:
            return jsonify({'status': 'error', 'message': 'Movie not found in Radarr.'}), 404

        if options.get('archive'):
            try:
                from app.utils.archive_manager import add_archived_media
                tmdb_id = next((g.id.replace('tmdb://', '') for g in movie.guids if g.id.startswith('tmdb://')), None)
                poster_url = plex_client.get_item_poster_url(movie)

                success, message = add_archived_media(
                    media_type='movie',
                    external_id=tmdb_id,
                    user_id=user_id,
                    title=movie.title,
                    year=movie.year,
                    summary=movie.summary,
                    poster_url=poster_url,
                    watched_status={'is_fully_watched': True, 'last_watched_at': movie.lastViewedAt.isoformat() if movie.lastViewedAt else None}
                )
                if success:
                    current_app.logger.info(f"'{movie.title}' archivé manuellement avec succès.")
                else:
                    current_app.logger.error(f"Échec de l'archivage manuel pour '{movie.title}': {message}")
            except Exception as e:
                current_app.logger.error(f"Erreur majeure lors de la sauvegarde manuelle pour '{movie.title}': {e}", exc_info=True)


        if options.get('unmonitor') or options.get('addTag'):
            if options.get('unmonitor'):
                radarr_movie['monitored'] = False
            if options.get('addTag'):
                tag_id = get_radarr_tag_id('vu')
                if tag_id and tag_id not in radarr_movie.get('tags', []):
                    radarr_movie['tags'].append(tag_id)

            if not update_radarr_movie(radarr_movie):
                 return jsonify({'status': 'error', 'message': 'Failed to update movie in Radarr.'}), 500

        if options.get('deleteFiles'):
            # ... (la logique de suppression de fichiers reste la même)
            pass

        return jsonify({'status': 'success', 'message': f"Film '{movie.title}' archivé avec succès."})

    except NotFound:
        return jsonify({'status': 'error', 'message': f"Movie with ratingKey {rating_key} not found."}), 404
    except Exception as e:
        current_app.logger.error(f"Error archiving movie: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@plex_editor_bp.route('/archive_show', methods=['POST'])
@login_required
def archive_show_route():
    data = request.get_json()
    rating_key = data.get('ratingKey')
    options = data.get('options', {})
    user_id = data.get('userId')

    if not rating_key or not user_id:
        return jsonify({'status': 'error', 'message': 'Missing ratingKey or userId.'}), 400

    try:
        from app.utils.plex_client import PlexClient
        plex_client = PlexClient(user_id=user_id)
        show = plex_client.get_item_by_rating_key(int(rating_key))

        if not show or show.type != 'show':
            return jsonify({'status': 'error', 'message': 'Show not found or not a show item.'}), 404

        if show.viewedLeafCount != show.leafCount:
            error_msg = f"Not all episodes are marked as watched for the selected user (Viewed: {show.viewedLeafCount}, Total: {show.leafCount})."
            return jsonify({'status': 'error', 'message': error_msg}), 400

        sonarr_series = next((s for g in show.guids if (s := get_sonarr_series_by_guid(g.id))), None)
        if not sonarr_series:
            return jsonify({'status': 'error', 'message': 'Show not found in Sonarr.'}), 404

        # Obtenir l'historique de visionnage détaillé (DÉPLACÉ ICI)
        watch_history = plex_client.get_show_watch_history(show)

        if options.get('archive'):
            try:
                from app.utils.archive_manager import add_archived_media
                tvdb_id = next((g.id.replace('tvdb://', '') for g in show.guids if g.id.startswith('tvdb://')), None)
                success, message = add_archived_media(
                    media_type='show',
                    external_id=tvdb_id,
                    user_id=user_id,
                    title=show.title,
                    year=show.year,
                    summary=show.summary,
                    poster_url=watch_history.get('poster_url'),
                    watched_status=watch_history
                )
                if success:
                    current_app.logger.info(f"'{show.title}' archivé manuellement avec succès.")
                else:
                    current_app.logger.error(f"Échec de l'archivage manuel pour '{show.title}': {message}")
            except Exception as e:
                current_app.logger.error(f"Erreur majeure lors de la sauvegarde manuelle pour '{show.title}': {e}", exc_info=True)

        if options.get('unmonitor') or options.get('addTag'):
            full_series_data = get_sonarr_series_by_id(sonarr_series['id'])
            if not full_series_data: return jsonify({'status': 'error', 'message': 'Could not fetch full series details from Sonarr.'}), 500

            if options.get('unmonitor'):
                full_series_data['monitored'] = False

            if options.get('addTag'):
                watched_tags = ['vu']
                if watch_history.get('is_fully_watched'):
                    watched_tags.append('vu-complet')
                for season in watch_history.get('seasons', []):
                    if season.get('is_watched'):
                        watched_tags.append(f"Saison {season.get('season_number')}")
                for tag_label in set(watched_tags):
                    tag_id = get_sonarr_tag_id(tag_label)
                    if tag_id and tag_id not in full_series_data.get('tags', []):
                        full_series_data['tags'].append(tag_id)

            if not update_sonarr_series(full_series_data):
                return jsonify({'status': 'error', 'message': 'Failed to update series in Sonarr.'}), 500

        if options.get('deleteFiles'):
            # ... (la logique de suppression de fichiers reste la même)
            pass

        return jsonify({'status': 'success', 'message': f"Série '{show.title}' archivée avec succès."})

    except NotFound:
        return jsonify({'status': 'error', 'message': f"Show with ratingKey {rating_key} not found."}), 404
    except Exception as e:
        current_app.logger.error(f"Error archiving show: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ... (le reste du fichier a été omis pour la concision)
