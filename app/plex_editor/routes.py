# app/plex_editor/routes.py
# -*- coding: utf-8 -*-

import os
from app.auth import login_required
from flask import (render_template, current_app, flash, abort, url_for,
                   redirect, request, session, jsonify)
from datetime import datetime, timedelta
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
    get_all_sonarr_series # <--- AJOUT ICI
)

# --- Routes du Blueprint ---

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
        library_list = [{'id': lib.key, 'text': lib.title} for lib in libraries]
        return jsonify(library_list)

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


    cleaned_genres = [genre for genre in genres_filter if genre]
    cleaned_collections = [c for c in collections_filter if c]
    cleaned_resolutions = [r for r in resolutions_filter if r]
    cleaned_studios = [s for s in studios_filter if s]

    if not user_id or not library_keys:
        return jsonify({'error': 'ID utilisateur et au moins une clé de bibliothèque sont requis.'}), 400

    try:
        target_plex_server = get_user_specific_plex_server_from_id(user_id)
        if not target_plex_server:
            return jsonify({'error': f"Impossible de se connecter en tant que {user_id}."}), 500

        all_media_from_plex = []
        for lib_key in library_keys:
            try:
                library = target_plex_server.library.sectionByID(int(lib_key))

                search_args = {}
                # Pour la logique 'AND', on ne met qu'un seul genre dans la recherche initiale
                # pour filtrer un minimum côté serveur, le reste sera fait en Python.
                # Pour 'OR', on peut tout passer.
                if cleaned_genres:
                    if genre_logic == 'and':
                        search_args['genre'] = cleaned_genres[0]
                    else: # 'or'
                        search_args['genre'] = cleaned_genres

                if title_filter:
                    search_args['title__icontains'] = title_filter

                if year_filter:
                    try:
                        search_args['year'] = int(year_filter)
                    except (ValueError, TypeError):
                        pass # Ignorer si la valeur n'est pas un entier valide

                date_filter = data.get('dateFilter', {})
                date_type = date_filter.get('type')

                if date_type and date_filter.get('preset'):
                    preset = date_filter['preset']
                    today = datetime.now()
                    start_date, end_date = None, None

                    if preset == 'today':
                        start_date = today.replace(hour=0, minute=0, second=0)
                        end_date = today.replace(hour=23, minute=59, second=59)
                    elif preset == 'last7days':
                        start_date = today - timedelta(days=7)
                        end_date = today
                    elif preset == 'last30days':
                        start_date = today - timedelta(days=30)
                        end_date = today
                    elif preset == 'thisMonth':
                        start_date = today.replace(day=1, hour=0, minute=0, second=0)
                        end_date = today
                    elif preset == 'lastMonth':
                        end_of_last_month = today.replace(day=1) - timedelta(days=1)
                        start_date = end_of_last_month.replace(day=1, hour=0, minute=0, second=0)
                        end_date = end_of_last_month.replace(hour=23, minute=59, second=59)
                    elif preset == 'custom':
                        start_date_str = date_filter.get('start')
                        end_date_str = date_filter.get('end')
                        if start_date_str:
                            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                        if end_date_str:
                            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)

                    if start_date:
                        search_args[f'{date_type}>>'] = start_date
                    if end_date:
                        search_args[f'{date_type}<<'] = end_date

                rating_filter = data.get('ratingFilter', {})
                if rating_filter and rating_filter.get('operator'):
                    operator = rating_filter['operator']
                    value = rating_filter.get('value')

                    # Pour 'Est Noté', on cherche les notes strictement supérieures à 0.
                    if operator == 'is_rated':
                        search_args['userRating>>'] = 0
                    
                    # Pour 'N'est Pas Noté', on utilise la valeur spéciale -1 découverte par le script.
                    elif operator == 'is_not_rated':
                        search_args['userRating'] = -1
                    
                    # Le reste de la logique (gte, lte, eq) est correct et ne change pas.
                    elif value:
                        try:
                            rating_value = float(value)
                            if operator == 'gte':
                                search_args['userRating>>'] = rating_value
                            elif operator == 'lte':
                                search_args['userRating<<'] = rating_value
                            elif operator == 'eq':
                                search_args['userRating'] = rating_value
                        except (ValueError, TypeError):
                            pass # Ignorer si la valeur n'est pas un nombre valide

                if cleaned_collections:
                    search_args['collection'] = cleaned_collections

                if cleaned_resolutions:
                    search_args['resolution'] = cleaned_resolutions
                if cleaned_studios:
                    search_args['studio'] = cleaned_studios

                items_from_lib = library.search(**search_args)

                # Le filtrage "AND" se fait maintenant ici, sur les résultats pré-filtrés
                if cleaned_genres and genre_logic == 'and':
                    items_with_all_genres = []
                    # On a déjà filtré sur le premier genre, donc on vérifie les autres
                    required_genres_set = {genre.lower() for genre in cleaned_genres}

                    for item in items_from_lib:
                        if hasattr(item, 'genres') and item.genres:
                            item_genres_set = {g.tag.lower() for g in item.genres}
                            if required_genres_set.issubset(item_genres_set):
                                items_with_all_genres.append(item)

                    items_from_lib = items_with_all_genres

                # Le filtrage "AND" se fait maintenant ici, sur les résultats pré-filtrés
                if cleaned_genres and genre_logic == 'and':
                    items_with_all_genres = []
                    # On a déjà filtré sur le premier genre, donc on vérifie les autres
                    required_genres_set = {genre.lower() for genre in cleaned_genres}

                    for item in items_from_lib:
                        if hasattr(item, 'genres') and item.genres:
                            item_genres_set = {g.tag.lower() for g in item.genres}
                            if required_genres_set.issubset(item_genres_set):
                                items_with_all_genres.append(item)

                    items_from_lib = items_with_all_genres

                # Filtrage en Python pour les acteurs, réalisateurs et scénaristes
                if actor_filter:
                    items_from_lib = [
                        item for item in items_from_lib
                        if hasattr(item, 'actors') and any(actor_filter.lower() in actor.tag.lower() for actor in item.actors)
                    ]
                if director_filter:
                    items_from_lib = [
                        item for item in items_from_lib
                        if hasattr(item, 'directors') and any(director_filter.lower() in director.tag.lower() for director in item.directors)
                    ]
                if writer_filter:
                    items_from_lib = [
                        item for item in items_from_lib
                        if hasattr(item, 'writers') and any(writer_filter.lower() in writer.tag.lower() for writer in item.writers)
                    ]

                for item_from_lib in items_from_lib:
                    item_from_lib.library_name = library.title
                    item_from_lib.title_sort = getattr(item_from_lib, 'titleSort', None)
                    item_from_lib.original_title = getattr(item_from_lib, 'originalTitle', None)

                    # --- AJOUTE CE BLOC POUR LE POSTER ---
                    thumb_path = getattr(item_from_lib, 'thumb', None) 
                    if thumb_path:
                        item_from_lib.poster_url = target_plex_server.url(thumb_path, includeToken=True)
                    else:
                        item_from_lib.poster_url = None
                    # --- FIN DE L'AJOUT ---

                    # --- BLOC CORRIGÉ POUR LE CHEMIN DU FICHIER ---
                    if item_from_lib.type == 'movie':
                        # Pour les films, on prend le chemin du premier fichier
                        item_from_lib.file_path = getattr(item_from_lib.media[0].parts[0], 'file', None) if item_from_lib.media and item_from_lib.media[0].parts else None
                    elif item_from_lib.type == 'show':
                        # Pour les séries, on prend le chemin du premier dossier de la bibliothèque
                        item_from_lib.file_path = item_from_lib.locations[0] if item_from_lib.locations else None
                    else:
                        item_from_lib.file_path = None
                    # --- FIN DE LA CORRECTION ---

                    try:
                        # ... (calcul de la taille, etc. - code inchangé)
                        if item_from_lib.type == 'movie':
                            item_from_lib.total_size = item_from_lib.media[0].parts[0].size if hasattr(item_from_lib, 'media') and item_from_lib.media and item_from_lib.media[0].parts else 0
                        elif item_from_lib.type == 'show':
                            item_from_lib.total_size = sum(getattr(part, 'size', 0) for ep in item_from_lib.episodes() for part in (ep.media[0].parts if ep.media and ep.media[0].parts else []))
                        else:
                            item_from_lib.total_size = 0
                        # ... (formatage de la taille - code inchangé)
                        if item_from_lib.total_size > 0:
                            size_name = ("B", "KB", "MB", "GB", "TB"); i = 0
                            temp_size = float(item_from_lib.total_size)
                            while temp_size >= 1024 and i < len(size_name) - 1: temp_size /= 1024.0; i += 1
                            item_from_lib.total_size_display = f"{temp_size:.2f} {size_name[i]}"
                        else:
                            item_from_lib.total_size_display = "0 B"
                        
                        if item_from_lib.type == 'show':
                            item_from_lib.viewed_episodes = item_from_lib.viewedLeafCount
                            item_from_lib.total_episodes = item_from_lib.leafCount
                    except Exception:
                        item_from_lib.total_size_display = "Erreur"
                    all_media_from_plex.append(item_from_lib)

            except Exception as e_lib:
                current_app.logger.error(f"Erreur accès bibliothèque {lib_key}: {e_lib}", exc_info=True)

        # (La logique de filtrage par statut et le tri restent identiques)
        # ...
        filtered_items = []
        if status_filter == 'all':
            filtered_items = all_media_from_plex
        else:
            for item in all_media_from_plex:
                # ... (logique de filtre par statut inchangée)
                if item.type == 'show':
                    is_watched = item.total_episodes > 0 and item.viewed_episodes == item.total_episodes
                    is_unwatched = item.total_episodes > 0 and item.viewed_episodes == 0
                    is_in_progress = item.total_episodes > 0 and item.viewed_episodes > 0 and not is_watched
                    if (status_filter == 'watched' and is_watched) or (status_filter == 'unwatched' and is_unwatched) or (status_filter == 'in_progress' and is_in_progress):
                        filtered_items.append(item)
                elif item.type == 'movie':
                    if (status_filter == 'watched' and item.isWatched) or (status_filter == 'unwatched' and not item.isWatched):
                        filtered_items.append(item)

        filtered_items.sort(key=lambda x: getattr(x, 'titleSort', x.title).lower())
        return render_template('plex_editor/_media_table.html', items=filtered_items)

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

# @plex_editor_bp.route('/libraries')
# @login_required
# def list_libraries():
#     """Affiche la liste des bibliothèques Plex disponibles."""
#     if 'plex_user_id' not in session:
#         flash("Veuillez d'abord sélectionner un utilisateur Plex.", "info")
#         return redirect(url_for('plex_editor.index')) # (### MODIFICATION ICI ###) - Pointeur vers la nouvelle fonction 'index'
#
#     user_title = session.get('plex_user_title', 'Utilisateur Inconnu')
#     plex_server = get_plex_admin_server()
#     libraries = []
#     plex_error_message = None
#
#     if plex_server:
#         try:
#             libraries = plex_server.library.sections()
#             flash(f'Connecté au serveur Plex: {plex_server.friendlyName} (Utilisateur actuel: {user_title})', 'success')
#         except Exception as e:
#             plex_error_message = str(e)
#             current_app.logger.error(f"list_libraries: Erreur de récupération des bibliothèques: {e}", exc_info=True)
#             flash(f"Erreur de récupération des bibliothèques : {e}", 'danger')
#     else:
#         plex_error_message = "Impossible de se connecter au serveur Plex."
#
#     return render_template('plex_editor/index.html',
#                            title=f'Bibliothèques - {user_title}',
#                            libraries=libraries,
#                            plex_error=plex_error_message,
#                            user_title=user_title)
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

# Si la série est dans notre liste de candidates Sonarr, c'est un match !
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
def find_ready_to_watch_shows_in_library(library_name):
    """
    Trouve les séries terminées, complètes et non vues dans une bibliothèque Plex.
    """
    current_app.logger.info(f"Filtre Spécial 'Prêtes à Regarder' pour la bibliothèque '{library_name}'.")
    try:
        all_sonarr_series = get_all_sonarr_series()
        if not all_sonarr_series:
            flash("Erreur de communication avec Sonarr.", "danger")
            return []

        candidate_tvdb_ids = {
            s['tvdbId'] for s in all_sonarr_series
            if s.get('status') == 'ended' and s.get('statistics', {}).get('percentOfEpisodes', 0) == 100.0
        }

        ready_to_watch_shows = []
        user_plex_server = get_user_specific_plex_server()
        if not user_plex_server: return []

        library = user_plex_server.library.section(library_name)
        if library.type != 'show': return []

        for show in library.search(unwatched=True):
            if show.viewedLeafCount == 0:
                plex_tvdb_id = next((int(g.id.split('//')[1]) for g in show.guids if 'tvdb' in g.id), None)
                if plex_tvdb_id in candidate_tvdb_ids:
                    ready_to_watch_shows.append(show)

        ready_to_watch_shows.sort(key=lambda s: s.titleSort.lower())
        flash(f"{len(ready_to_watch_shows)} série(s) prête(s) à être commencée(s) trouvée(s) !", "success")
        return ready_to_watch_shows

    except Exception as e:
        current_app.logger.error(f"Erreur dans find_ready_to_watch_shows_in_library: {e}", exc_info=True)
        flash("Une erreur est survenue pendant la recherche complexe.", "danger")
        return []
# Route existante modifiée pour accepter un nom de bibliothèque optionnel dans le chemin
@plex_editor_bp.route('/library')
@plex_editor_bp.route('/library/<path:library_name>')
@login_required
def show_library(library_name=None):
    # --- DÉTECTION DES FILTRES SPÉCIAUX ---
    special_filter = request.args.get('special_filter')
    # On gère le cas où le nom de la bibliothèque vient du chemin OU d'un paramètre (pour les filtres futurs)
    lib_name_for_special_filter = library_name or request.args.get('library_name')

    if special_filter == 'ready_to_watch' and lib_name_for_special_filter:
        items_list = find_ready_to_watch_shows_in_library(lib_name_for_special_filter)

        # On récupère l'objet bibliothèque pour l'affichage et les liens
        user_plex_server = get_user_specific_plex_server()
        library_obj = user_plex_server.library.section(lib_name_for_special_filter) if user_plex_server else None

        return render_template('plex_editor/library.html',
                               title=f"Séries Prêtes à Regarder",
                               items=items_list,
                               library_name=lib_name_for_special_filter,
                               library_obj=library_obj,
                               current_filters={'sort_by': 'titleSort:asc', 'title_filter': ''}, # Fournir tous les filtres attendus
                               selected_libs=[lib_name_for_special_filter],
                               view_mode='ready_to_watch', # Pour adapter l'affichage
                               plex_error=None,
                               user_title=session.get('plex_user_title', ''),
                               config=current_app.config)

    # --- SI PAS DE FILTRE SPÉCIAL, ON EXÉCUTE LA LOGIQUE NORMALE ---

    if 'plex_user_id' not in session:
        flash("Veuillez sélectionner un utilisateur.", "info")
        return redirect(url_for('plex_editor.index'))

    # --- ÉTAPE A.1: DÉTERMINER LES BIBLIOTHÈQUES À TRAITER (MODIFIED BLOCK) ---
    library_names = []
    if library_name:
        # Single library from URL path
        library_names = [library_name]
        current_app.logger.info(f"show_library (A.1): Single library mode. Initial library from path: '{library_name}'")
    else:
        # Multiple libraries from query parameters
        selected_libs_from_args = request.args.getlist('selected_libs')
        if selected_libs_from_args:
            library_names = selected_libs_from_args
            current_app.logger.info(f"show_library (A.1): Multi-library mode. Libraries from args: {library_names}")
        else:
            current_app.logger.warning("show_library (A.1): No library specified in path and no 'selected_libs' in query arguments. Redirecting.")
            flash("Aucune bibliothèque spécifiée. Veuillez sélectionner une ou plusieurs bibliothèques.", "warning")
            return redirect(url_for('plex_editor.list_libraries'))

    if not library_names: # Final safeguard
        current_app.logger.error("show_library (A.1): Critical error - library_names list is empty after determination logic. Redirecting.")
        flash("Erreur critique : aucune bibliothèque à traiter n'a pu être déterminée.", "danger")
        return redirect(url_for('plex_editor.list_libraries'))

    current_app.logger.info(f"show_library (A.1): Final list of libraries to process: {library_names}")
    # --- END OF MODIFIED BLOCK FOR STEP A.1 ---

    # --- STEP A.2: UNIFIED FILTER RETRIEVAL (Placeholder - will be replaced by Step A.2 of the plan) ---
    current_filters = {
        'vu': request.args.get('vu', 'tous'),
        'note_filter_type': request.args.get('note_filter_type', 'toutes'),
        'note_filter_value': request.args.get('note_filter_value', ''),
        'date_filter_type': request.args.get('date_filter_type', 'aucun'),
        'date_filter_value': request.args.get('date_filter_value', ''),
        'viewdate_filter_type': request.args.get('viewdate_filter_type', 'aucun'),
        'viewdate_filter_value': request.args.get('viewdate_filter_value', ''),
        'sort_by': request.args.get('sort_by', 'addedAt:desc'),
        'title_filter': request.args.get('title_filter', '').strip()
    }
    current_app.logger.debug(f"show_library (A.2 - Placeholder): Initial current_filters: {current_filters}")

    # --- STEP A.3: BUILD PLEXAPI SEARCH ARGUMENTS (search_args) (Placeholder - will be replaced by Step A.3) ---
    search_args = {}
    filter_fully_watched_shows_in_python = False
    filter_for_non_notes_in_python = False

    if current_filters['title_filter']:
        search_args['title__icontains'] = current_filters['title_filter']
    if current_filters['vu'] == 'vu': search_args['unwatched'] = False
    elif current_filters['vu'] == 'nonvu': search_args['unwatched'] = True

    note_type = current_filters['note_filter_type'] # Corrected Indentation
    if note_type == 'non_notes':
        filter_for_non_notes_in_python = True
    elif note_type in ['note_exacte', 'note_min', 'note_max'] and current_filters['note_filter_value']:
        try:
            note_val_float = float(current_filters['note_filter_value'])
            if note_type == 'note_exacte': search_args['userRating'] = note_val_float
            elif note_type == 'note_min': search_args['userRating>>='] = note_val_float
            elif note_type == 'note_max': search_args['userRating<<='] = note_val_float
        except (ValueError, TypeError):
            flash(f"La valeur de note '{current_filters['note_filter_value']}' est invalide.", "warning")

    date_type = current_filters['date_filter_type']
    date_value = current_filters['date_filter_value']
    if date_type != 'aucun' and date_value:
        try:
            if date_type == 'ajout_recent_jours':
                search_args['addedAt>>='] = f"{int(date_value)}d"
            elif date_type == 'sortie_annee':
                search_args['year'] = int(date_value)
            else:
                parsed_date = datetime.strptime(date_value, '%Y-%m-%d')
                date_str = parsed_date.strftime('%Y-%m-%d')
                if date_type == 'ajout_avant_date': search_args['addedAt<<'] = date_str
                elif date_type == 'ajout_apres_date': search_args['addedAt>>='] = date_str
        except (ValueError, TypeError):
            flash(f"Valeur de date '{date_value}' invalide pour le filtre '{date_type}'.", "warning")

    viewdate_type = current_filters['viewdate_filter_type']
    viewdate_value = current_filters['viewdate_filter_value']
    if viewdate_type != 'aucun' and viewdate_value:
        try:
            if viewdate_type == 'viewed_recent_days':
                search_args['lastViewedAt>>='] = f"{int(viewdate_value)}d"
            else:
                parsed_date = datetime.strptime(viewdate_value, '%Y-%m-%d')
                date_str = parsed_date.strftime('%Y-%m-%d')
                if viewdate_type == 'viewed_before_date': search_args['lastViewedAt<<='] = date_str
                elif viewdate_type == 'viewed_after_date': search_args['lastViewedAt>>='] = date_str
        except (ValueError, TypeError):
            flash(f"Valeur de date de visionnage '{viewdate_value}' invalide.", "warning")
    current_app.logger.debug(f"show_library (A.3 - Placeholder): Constructed search_args: {search_args}")

    # --- STEP A.4: Execute Search and Merge Results (Placeholder - will be replaced by Step A.4) ---
    all_items = []
    plex_error_message = None
    user_specific_plex_server = get_user_specific_plex_server() # Call once
    if not user_specific_plex_server:
        return redirect(url_for('plex_editor.index'))

    processed_libs_objects = [] # For Step A.6

    for i, lib_name_iter in enumerate(library_names):
        try:
            library_object = user_specific_plex_server.library.section(lib_name_iter)
            processed_libs_objects.append(library_object)

            temp_search_args = search_args.copy()
            if library_object.type == 'show' and current_filters['vu'] == 'vu':
                filter_fully_watched_shows_in_python = True

            items_from_lib = library_object.search(**temp_search_args)
            all_items.extend(items_from_lib)
            current_app.logger.info(f"show_library (A.4 - Placeholder): Fetched {len(items_from_lib)} items from library '{lib_name_iter}'.")
        except NotFound:
            error_msg = f"Bibliothèque '{lib_name_iter}' non trouvée."
            current_app.logger.warning(f"show_library (A.4 - Placeholder): {error_msg}")
            if len(library_names) == 1:
                flash(error_msg, "danger")
                return redirect(url_for('plex_editor.list_libraries'))
            else:
                plex_error_message = (plex_error_message + f"; {error_msg}" if plex_error_message else error_msg)
        except Exception as e:
            error_msg = f"Erreur lors de l'accès à '{lib_name_iter}': {str(e)}"
            current_app.logger.error(f"show_library (A.4 - Placeholder): {error_msg}", exc_info=True)
            if i == 0 or len(library_names) == 1: # Corrected from if i == 0 or len(library_names) == 1:
                flash(error_msg, "danger")
                return redirect(url_for('plex_editor.list_libraries'))
            else:
                 plex_error_message = (plex_error_message + f"; {error_msg}" if plex_error_message else error_msg)

    # --- STEP A.5: Python Post-Filtering and Final Sort (Placeholder - will be replaced by Step A.5) ---
    items_filtered = all_items
    if filter_fully_watched_shows_in_python:
        current_app.logger.debug("show_library (A.5 - Placeholder): Applying Python post-filter for 'fully watched shows'.")
        items_filtered = [item for item in items_filtered if item.type != 'show' or (item.leafCount > 0 and item.viewedLeafCount == item.leafCount)]

    if filter_for_non_notes_in_python:
        current_app.logger.debug("show_library (A.5 - Placeholder): Applying Python post-filter for 'non notés'.")
        items_filtered = [item for item in items_filtered if getattr(item, 'userRating', None) is None]

    if current_filters['sort_by']:
        sort_key_attr, sort_direction = current_filters['sort_by'].split(':')
        sort_reverse_flag = (sort_direction == 'desc')
        def robust_sort_key_func(item_to_sort):
            val = getattr(item_to_sort, sort_key_attr, None)
            if val is None:
                if sort_key_attr in ['addedAt', 'lastViewedAt', 'originallyAvailableAt', 'updatedAt', 'lastRatedAt']:
                    return datetime.min
                elif sort_key_attr in ['userRating', 'rating', 'year', 'index', 'parentIndex']:
                    return float('-inf') if sort_reverse_flag else float('inf')
                else: return ""
            if isinstance(val, str): return val.lower()
            return val
        try:
            items_filtered.sort(key=robust_sort_key_func, reverse=sort_reverse_flag)
            current_app.logger.info(f"show_library (A.5 - Placeholder): Sorted {len(items_filtered)} items by '{sort_key_attr}' ({sort_direction}).")
        except TypeError as e_sort_type:
            current_app.logger.error(f"show_library (A.5 - Placeholder): Erreur de tri (TypeError) sur la clé '{sort_key_attr}': {e_sort_type}.", exc_info=True)
            flash(f"Erreur de tri pour '{sort_key_attr}'. Tri par défaut appliqué.", "warning")
            # Fallback sort might be needed if robust_sort_key_func isn't perfect
            items_filtered.sort(key=lambda x: getattr(x, 'titleSort', '').lower(), reverse=False) # Basic fallback
        except Exception as e_sort:
            current_app.logger.error(f"show_library (A.5 - Placeholder): Erreur de tri inattendue sur la clé '{sort_key_attr}': {e_sort}", exc_info=True)
            flash(f"Erreur inattendue pendant le tri par '{sort_key_attr}'.", "warning")

    # --- STEP A.6: Render Template with Consistent Context (Placeholder - will be refined by Step A.6) ---
    display_title = ", ".join(library_names) # Will be updated in A.6 based on processed_libs_objects
    library_obj_for_template = processed_libs_objects[0] if processed_libs_objects else None
    processed_library_names = [lib.title for lib in processed_libs_objects] # Use processed_libs_objects

    # Placeholder flash message logic (will be fully implemented in Step A.6)
    user_title_in_session = session.get('plex_user_title', 'Utilisateur Inconnu')
    page_title = f"Bibliothèque: {display_title} - {user_title_in_session}" # title for <title> tag
    final_flash_message = ""
    flash_category = "info"

    if plex_error_message and not processed_libs_objects:
        final_flash_message = plex_error_message + " Aucune bibliothèque n'a pu être chargée."
        flash_category = "danger"
    elif plex_error_message: # Some errors, but some libs might have been processed
        final_flash_message = f"Affichage de {len(items_filtered)} élément(s) pour '{', '.join(processed_library_names) if processed_library_names else 'bibliothèques sélectionnées'}'. "
        final_flash_message += f"Erreurs rencontrées: {plex_error_message}"
        flash_category = "warning"
    elif not items_filtered and processed_libs_objects: # Successfully processed libs, but no items
        final_flash_message = f"Aucun élément trouvé dans '{', '.join(processed_library_names)}' avec les filtres actuels."
        flash_category = "info"
    elif processed_libs_objects: # Success
        final_flash_message = f"Affichage de {len(items_filtered)} élément(s) pour '{', '.join(processed_library_names)}'."
        flash_category = "success" # Changed from info for successful display

    if final_flash_message: # Ensure flash is only called if there's a message
        flash(final_flash_message, flash_category)

    return render_template('plex_editor/library.html',
                           title=page_title, # Pass page_title
                           items=items_filtered,
                           current_filters=current_filters,
                           library_name=display_title, # Will be refined in A.6
                           library_obj=library_obj_for_template, # Will be refined in A.6
                           selected_libs=processed_library_names, # Use names of processed libs for template
                           plex_error=plex_error_message, # For direct error display if needed by template
                           user_title=user_title_in_session,
                           config=current_app.config,
                           view_mode='standard')

@plex_editor_bp.route('/delete_item/<int:rating_key>', methods=['POST'])
@login_required
def delete_item(rating_key):
    # --- Début des logs de débogage initiaux ---
    print(f"--- PRINT: FONCTION delete_item APPELÉE pour rating_key: {rating_key} ---")
    print(f"--- PRINT: Contenu du formulaire delete_item: {request.form}")
    current_app.logger.info(f"--- LOG: FONCTION delete_item APPELÉE pour rating_key: {rating_key} ---")
    current_app.logger.debug(f"LOG: Contenu du formulaire delete_item: {request.form}")
    # --- Fin des logs de débogage initiaux ---

    if 'plex_user_id' not in session:
        flash("Session expirée. Veuillez vous reconnecter.", "danger")
        return redirect(url_for('plex_editor.index')) # (### MODIFICATION ICI ###) - Pointeur vers 'index'

    current_library_name = request.form.get('current_library_name')
    # Correction: le fallback 'index' est ambigu, il vaut mieux pointer vers la liste des bibliothèques
    redirect_url = request.referrer or url_for('plex_editor.list_libraries')

    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')

    if not plex_url or not admin_token:
        flash("Configuration Plex admin manquante. Suppression impossible.", "danger")
        return redirect(redirect_url)

    media_filepath_to_cleanup = None
    item_title_for_flash = f"Item (ratingKey: {rating_key})"

    # Variables pour les chemins dynamiques
    active_plex_library_roots = []
    deduced_base_paths_guards = [] # Initialiser comme liste

    try:
        plex_server = PlexServer(plex_url, admin_token)

        # --- RÉCUPÉRATION DYNAMIQUE DES RACINES ET GARDE-FOUS ---
        try:
            library_sections = plex_server.library.sections()
            temp_roots = set()
            temp_guards = set()
            for lib_sec in library_sections:
                if hasattr(lib_sec, 'locations') and lib_sec.locations:
                    for loc_path in lib_sec.locations:
                        norm_loc_path = os.path.normpath(loc_path)
                        temp_roots.add(norm_loc_path)
                        drive, _ = os.path.splitdrive(norm_loc_path) # Sépare en lecteur et reste
                        if drive: # Windows: drive sera 'X:'
                            temp_guards.add(drive + os.sep) # Ajoute 'X:\'
                        else: # POSIX: drive sera '', path_after_drive sera '/chemin/complet'
                            path_components = [c for c in norm_loc_path.split(os.sep) if c] # Enlève les vides
                            if path_components: # S'il y a au moins un composant
                                guard = os.sep + path_components[0] # Prend le premier répertoire après la racine, ex: '/data'
                                temp_guards.add(os.path.normpath(guard))
                            elif norm_loc_path == os.sep: # Cas de la racine elle-même
                                temp_guards.add(os.sep)


            active_plex_library_roots = list(temp_roots)
            deduced_base_paths_guards = list(temp_guards) if temp_guards else [os.path.normpath(os.path.abspath(os.sep))]

            current_app.logger.info(f"delete_item: Racines Plex détectées: {active_plex_library_roots}")
            current_app.logger.info(f"delete_item: Garde-fous de base déduits: {deduced_base_paths_guards}")
        except Exception as e_get_paths:
            current_app.logger.error(f"delete_item: Erreur récupération racines/garde-fous: {e_get_paths}. Nettoyage plus risqué.", exc_info=True)
            flash("Avertissement: Récupération des chemins Plex échouée. Nettoyage de dossier plus risqué.", "warning")
            # Laisser active_plex_library_roots et deduced_base_paths_guards comme listes vides (ou avec fallback si défini)
        # --- FIN RÉCUPÉRATION DYNAMIQUE ---

        item_to_delete = plex_server.fetchItem(rating_key)

        if item_to_delete:
            item_title_for_flash = item_to_delete.title
            media_filepath_to_cleanup = get_media_filepath(item_to_delete) # Utilisation de la fonction utils
            current_app.logger.info(f"DELETE_ITEM: Chemin récupéré via get_media_filepath: {media_filepath_to_cleanup}")

            current_app.logger.info(f"Suppression Plex de '{item_title_for_flash}' (ratingKey: {rating_key}) par '{session.get('plex_user_title', 'Inconnu')}'.")
            item_to_delete.delete()
            flash(f"« {item_title_for_flash} » supprimé de Plex.", "success")
            current_app.logger.info(f"'{item_title_for_flash}' (ratingKey: {rating_key}) supprimé de Plex.")

            if media_filepath_to_cleanup:
                            current_app.logger.info(f"DELETE_ITEM: Lancement du nettoyage pour: {media_filepath_to_cleanup} (Racines Plex: {active_plex_library_roots}, Gardes-fous: {deduced_base_paths_guards})") # Log amélioré
                            cleanup_parent_directory_recursively(media_filepath_to_cleanup,
                                                                 dynamic_plex_library_roots=active_plex_library_roots,
                                                                 base_paths_guards=deduced_base_paths_guards)
            else:
                current_app.logger.info(f"DELETE_ITEM: Aucun chemin de fichier pour {item_title_for_flash} (ratingKey: {rating_key}), nettoyage de répertoire ignoré.")
        else:
            flash(f"Item (ratingKey {rating_key}) non trouvé. Suppression annulée.", "warning")
            current_app.logger.warning(f"Item non trouvé avec ratingKey: {rating_key} dans delete_item.")

    except NotFound:
        flash(f"Item (ratingKey {rating_key}) non trouvé sur Plex. Peut-être déjà supprimé ?", "warning")
        current_app.logger.warning(f"NotFound lors de la suppression de ratingKey: {rating_key}")
    except Unauthorized:
        flash("Autorisation refusée. Le token Plex admin pourrait ne pas avoir les droits.", "danger")
        current_app.logger.error(f"Unauthorized lors de la suppression de ratingKey: {rating_key}")
    except BadRequest:
        flash(f"Requête incorrecte pour la suppression (ratingKey {rating_key}). Ne peut peut-être pas être supprimé.", "danger")
        current_app.logger.error(f"BadRequest lors de la suppression de ratingKey: {rating_key}", exc_info=True)
    except Exception as e:
        flash(f"Erreur lors de la suppression de « {item_title_for_flash} »: {e}", "danger")
        current_app.logger.error(f"Erreur inattendue suppression ratingKey {rating_key}: {e}", exc_info=True)

    return redirect(redirect_url)


@plex_editor_bp.route('/bulk_delete_items', methods=['POST'])
@login_required
def bulk_delete_items():
    # --- Début des logs de débogage initiaux ---
    print("--- PRINT: FONCTION bulk_delete_items APPELÉE ---")
    print(f"--- PRINT: Contenu du formulaire bulk_delete_items: {request.form}")
    current_app.logger.info("--- LOG: FONCTION bulk_delete_items APPELÉE ---")
    current_app.logger.debug(f"LOG: Contenu du formulaire bulk_delete_items: {request.form}")
    # --- Fin des logs de débogage initiaux ---

    if 'plex_user_id' not in session:
        flash("Session expirée. Veuillez vous reconnecter.", "danger")
        return redirect(url_for('plex_editor.index')) # (### MODIFICATION ICI ###) - Pointeur vers 'index'

    selected_keys_str_list = request.form.getlist('selected_item_keys')
    current_library_name = request.form.get('current_library_name')
    redirect_url = request.referrer or url_for('plex_editor.list_libraries') # (### MODIFICATION ICI ###) - Fallback plus logique

    if not selected_keys_str_list:
        flash("Aucun élément sélectionné pour suppression.", "warning")
        return redirect(redirect_url)

    selected_rating_keys = [int(k_str) for k_str in selected_keys_str_list if k_str.isdigit()]
    if not selected_rating_keys:
        flash("Aucune clé d'élément valide sélectionnée après filtrage.", "warning")
        return redirect(redirect_url)

    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')

    if not plex_url or not admin_token:
        flash("Configuration Plex admin manquante. Suppression groupée impossible.", "danger")
        return redirect(redirect_url)

    success_count = 0
    fail_count = 0
    failed_items_info = []
    # Variables pour les chemins dynamiques (récupérées une fois pour le lot)
    active_plex_library_roots = []
    deduced_base_paths_guards = []

    try:
        plex_server = PlexServer(plex_url, admin_token)
        current_app.logger.info(f"Suppression groupée: {len(selected_rating_keys)} items par '{session.get('plex_user_title', 'Inconnu')}'. Clés: {selected_rating_keys}")

        # --- RÉCUPÉRATION DYNAMIQUE DES RACINES ET GARDE-FOUS (une fois pour le lot) ---
        try:
            library_sections = plex_server.library.sections()
            temp_roots = set()
            temp_guards = set()
            for lib_sec in library_sections:
                if hasattr(lib_sec, 'locations') and lib_sec.locations:
                    for loc_path in lib_sec.locations:
                        norm_loc_path = os.path.normpath(loc_path)
                        temp_roots.add(norm_loc_path)
                        drive, _ = os.path.splitdrive(norm_loc_path)
                        if drive: temp_guards.add(drive + os.sep)
                        else:
                            path_components = [c for c in norm_loc_path.split(os.sep) if c]
                            if path_components: temp_guards.add(os.sep + path_components[0])
                            elif norm_loc_path == os.sep: temp_guards.add(os.sep)

            active_plex_library_roots = list(temp_roots)
            deduced_base_paths_guards = list(temp_guards) if temp_guards else [os.path.normpath(os.path.abspath(os.sep))]

            current_app.logger.info(f"bulk_delete_items: Racines Plex détectées: {active_plex_library_roots}")
            current_app.logger.info(f"bulk_delete_items: Garde-fous de base déduits: {deduced_base_paths_guards}")
        except Exception as e_get_paths:
            current_app.logger.error(f"bulk_delete_items: Erreur récupération racines/garde-fous: {e_get_paths}. Nettoyage plus risqué.", exc_info=True)
            flash("Avertissement: Récupération des chemins Plex échouée. Nettoyage de dossier plus risqué.", "warning")
        # --- FIN RÉCUPÉRATION DYNAMIQUE ---

        for r_key in selected_rating_keys:
            item_title_for_log = f"ratingKey {r_key}"
            media_filepath_to_cleanup_bulk = None
            try:
                item_to_delete = plex_server.fetchItem(r_key)
                if item_to_delete:
                    item_title_for_log = item_to_delete.title
                    media_filepath_to_cleanup_bulk = get_media_filepath(item_to_delete)
                    current_app.logger.info(f"BULK_DELETE: Chemin récupéré via get_media_filepath: {media_filepath_to_cleanup_bulk}")

                    item_to_delete.delete()
                    success_count += 1
                    current_app.logger.info(f"Supprimé de Plex (groupe): '{item_title_for_log}' (ratingKey: {r_key})")

                    if media_filepath_to_cleanup_bulk:
                        current_app.logger.info(f"BULK_DELETE: Lancement du nettoyage pour: {media_filepath_to_cleanup_bulk} (Racines Plex: {active_plex_library_roots}, Gardes-fous: {deduced_base_paths_guards})")
                        cleanup_parent_directory_recursively(media_filepath_to_cleanup_bulk,
                                                             dynamic_plex_library_roots=active_plex_library_roots,
                                                             base_paths_guards=deduced_base_paths_guards)
                    else:
                         current_app.logger.info(f"BULK_DELETE: Pas de chemin pour {item_title_for_log} (groupe), nettoyage dossier ignoré.")

            except NotFound:
                fail_count += 1
                failed_items_info.append(f"ratingKey {r_key} (non trouvé/déjà supprimé)")
                current_app.logger.warning(f"Item non trouvé (NotFound) lors de suppression groupée: {r_key}")
            except Exception as e_item_del:
                fail_count += 1
                title_err = item_title_for_log
                if title_err == f"ratingKey {r_key}":
                    try:
                        item_obj_for_error_log = plex_server.fetchItem(r_key)
                        if item_obj_for_error_log: title_err = item_obj_for_error_log.title
                    except:
                        pass
                failed_items_info.append(f"'{title_err}' (erreur: {type(e_item_del).__name__})")
                current_app.logger.error(f"Échec suppression (groupe) pour '{title_err}': {e_item_del}", exc_info=True)

        # Messages Flash après la boucle
        if success_count > 0:
            flash(f"{success_count} élément(s) supprimé(s) de Plex.", "success")
        if fail_count > 0:
            summary = ", ".join(failed_items_info[:3])
            if len(failed_items_info) > 3:
                summary += f", et {len(failed_items_info) - 3} autre(s)..."
            flash(f"Échec de suppression pour {fail_count} élément(s). Détails: {summary}.", "danger")

    except Unauthorized:
        flash("Autorisation refusée (token admin). Suppression groupée échouée.", "danger")
        current_app.logger.error("Unauthorized pour suppression groupée.")
    except Exception as e_bulk:
        flash(f"Erreur majeure suppression groupée: {e_bulk}", "danger")
        current_app.logger.error(f"Erreur majeure suppression groupée: {e_bulk}", exc_info=True)

    return redirect(redirect_url)

# (### SUPPRESSION ICI ###) - La ligne d'import qui était ici a été supprimée car elle est déjà en haut du fichier.


# --- ROUTE D'ARCHIVAGE DE FILM (VERSION CORRIGÉE) ---
@plex_editor_bp.route('/archive_movie', methods=['POST'])
@login_required
def archive_movie_route():
    data = request.get_json()
    rating_key = data.get('ratingKey')
    options = data.get('options', {})

    if not rating_key:
        return jsonify({'status': 'error', 'message': 'Missing ratingKey.'}), 400

    # ÉTAPE 1: Obtenir les deux connexions nécessaires
    admin_plex_server = get_plex_admin_server()
    user_plex_server = get_user_specific_plex_server()

    if not admin_plex_server or not user_plex_server:
        return jsonify({'status': 'error', 'message': 'Could not establish Plex connections.'}), 500

    try:
        # ÉTAPE 2: Récupérer l'objet film dans les deux contextes
        # Contexte admin pour les actions (suppression, scan) et les métadonnées fiables
        movie_admin_context = admin_plex_server.fetchItem(int(rating_key))
        if not movie_admin_context or movie_admin_context.type != 'movie':
            return jsonify({'status': 'error', 'message': 'Movie not found or not a movie item.'}), 404

        # Contexte utilisateur pour la seule vérification du statut de visionnage
        movie_user_context = user_plex_server.fetchItem(int(rating_key))
        if not movie_user_context.isWatched:
            return jsonify({'status': 'error', 'message': 'Movie is not marked as watched for the current user.'}), 400

        # --- Radarr Actions ---
        if options.get('unmonitor') or options.get('addTag'):
            radarr_movie = None

            # ### DÉBOGAGE DES GUIDs PLEX ###
            guids_to_check = [g.id for g in movie_admin_context.guids]
            current_app.logger.info(f"Recherche du film '{movie_admin_context.title}' dans Radarr avec les GUIDs suivants : {guids_to_check}")

            for guid_str in guids_to_check:
                current_app.logger.info(f"  -> Tentative avec le GUID : {guid_str}")
                radarr_movie = get_radarr_movie_by_guid(guid_str)
                if radarr_movie:
                    current_app.logger.info(f"  -> SUCCÈS ! Film trouvé dans Radarr avec le GUID {guid_str}. (Titre Radarr: {radarr_movie.get('title')})")
                    break
                else:
                    current_app.logger.info(f"  -> Échec avec le GUID {guid_str}.")

            if not radarr_movie:
                return jsonify({'status': 'error', 'message': 'Movie not found in Radarr.'}), 404

            if options.get('unmonitor'): radarr_movie['monitored'] = False
            if options.get('addTag'):
                tag_label = current_app.config.get('RADARR_TAG_ON_ARCHIVE', 'vu')
                tag_id = get_radarr_tag_id(tag_label)
                if tag_id and tag_id not in radarr_movie.get('tags', []):
                    radarr_movie['tags'].append(tag_id)

            if not update_radarr_movie(radarr_movie):
                return jsonify({'status': 'error', 'message': 'Failed to update movie in Radarr.'}), 500

        # --- File Deletion Action ---
        # On utilise l'objet admin pour être sûr d'avoir le bon chemin de fichier
        if options.get('deleteFiles'):
            media_filepath = get_media_filepath(movie_admin_context)
            if media_filepath and os.path.exists(media_filepath):
                try:
                    is_simulating = _is_dry_run_mode()
                    dry_run_prefix = "[SIMULATION] " if is_simulating else ""
                    current_app.logger.info(f"{dry_run_prefix}ARCHIVE: Tentative de suppression du fichier média : {media_filepath}")
                    if not is_simulating:
                        os.remove(media_filepath)
                        flash(f"Fichier '{os.path.basename(media_filepath)}' supprimé.", "success")
                        current_app.logger.info(f"ARCHIVE: Fichier '{media_filepath}' supprimé avec succès.")
                    else:
                        flash(f"[SIMULATION] Fichier '{os.path.basename(media_filepath)}' serait supprimé.", "info")

                    # Logique de nettoyage du dossier parent
                    library_sections = admin_plex_server.library.sections()
                    temp_roots = {os.path.normpath(loc) for lib in library_sections for loc in lib.locations}
                    temp_guards = {os.path.normpath(os.path.splitdrive(r)[0] + os.sep) if os.path.splitdrive(r)[0] else os.path.normpath(os.sep + r.split(os.sep)[1]) for r in temp_roots if r}
                    cleanup_parent_directory_recursively(
                        media_filepath,
                        dynamic_plex_library_roots=list(temp_roots),
                        base_paths_guards=list(temp_guards)
                    )
                except Exception as e_cleanup:
                    current_app.logger.error(f"ARCHIVE: Erreur durant le processus de nettoyage pour '{movie_admin_context.title}': {e_cleanup}", exc_info=True)
                    flash(f"Erreur inattendue durant le nettoyage pour '{movie_admin_context.title}'.", "danger")
            elif media_filepath:
                 current_app.logger.warning(f"ARCHIVE: Chemin '{media_filepath}' non trouvé sur le disque, nettoyage ignoré.")
            else:
                current_app.logger.warning(f"ARCHIVE: Chemin du fichier pour '{movie_admin_context.title}' non trouvé dans Plex, nettoyage ignoré.")

        # --- Déclencher un scan de la bibliothèque dans Plex ---
        # Cette partie est maintenant DANS le bloc `try` principal
        try:
            # On utilise l'objet movie_admin_context qui est lié à la connexion admin
            library_name = movie_admin_context.librarySectionTitle
            movie_library = admin_plex_server.library.section(library_name)
            current_app.logger.info(f"Déclenchement d'un scan de la bibliothèque '{movie_library.title}' dans Plex.")
            if not _is_dry_run_mode():
                movie_library.update()
                flash(f"Scan de la bibliothèque '{movie_library.title}' déclenché.", "info")
            else:
                 flash(f"[SIMULATION] Un scan de la bibliothèque '{movie_library.title}' serait déclenché.", "info")
        except Exception as e_scan:
            current_app.logger.error(f"Échec du déclenchement du scan Plex: {e_scan}", exc_info=True)
            flash("Échec du déclenchement du scan de la bibliothèque dans Plex.", "warning")

        return jsonify({'status': 'success', 'message': f"'{movie_admin_context.title}' successfully archived."})

    except NotFound:
        return jsonify({'status': 'error', 'message': f"Movie with ratingKey {rating_key} not found in Plex."}), 404
    except Exception as e:
        current_app.logger.error(f"Error archiving movie: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
# --- ROUTE POUR L'ARCHIVAGE DE SÉRIE COMPLÈTE ---
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
        admin_plex_server = get_plex_admin_server()
        if not admin_plex_server:
            return jsonify({'status': 'error', 'message': 'Could not get admin Plex connection.'}), 500

        main_account = admin_plex_server.myPlexAccount()
        user_plex_server = None

        if str(main_account.id) == user_id:
            user_plex_server = admin_plex_server
        else:
            user_to_impersonate = next((u for u in main_account.users() if str(u.id) == user_id), None)
            if user_to_impersonate:
                managed_user_token = user_to_impersonate.get_token(admin_plex_server.machineIdentifier)
                user_plex_server = PlexServer(current_app.config.get('PLEX_URL'), managed_user_token)
            else:
                return jsonify({'status': 'error', 'message': f"User with ID {user_id} not found."}), 404

        if not user_plex_server:
            return jsonify({'status': 'error', 'message': 'Could not create user-specific Plex server instance.'}), 500

        show = user_plex_server.fetchItem(int(rating_key))
        if not show or show.type != 'show':
            return jsonify({'status': 'error', 'message': 'Show not found or not a show item.'}), 404

        if show.viewedLeafCount != show.leafCount:
            error_msg = f"Not all episodes are marked as watched (Viewed: {show.viewedLeafCount}, Total: {show.leafCount})."
            return jsonify({'status': 'error', 'message': error_msg}), 400

        sonarr_series = next((s for g in show.guids if (s := get_sonarr_series_by_guid(g.id))), None)
        if not sonarr_series:
            return jsonify({'status': 'error', 'message': 'Show not found in Sonarr.'}), 404

        # --- Logique Sonarr (fonctionnait déjà) ---
        if options.get('unmonitor') or options.get('addTag'):
            full_series_data = get_sonarr_series_by_id(sonarr_series['id'])
            if not full_series_data: return jsonify({'status': 'error', 'message': 'Could not fetch full series details from Sonarr.'}), 500
            if options.get('unmonitor'): full_series_data['monitored'] = False
            if options.get('addTag'):
                tags_to_add = ['vu', 'vu-complet']
                for tag_label in tags_to_add:
                    tag_id = get_sonarr_tag_id(tag_label)
                    if tag_id and tag_id not in full_series_data.get('tags', []):
                        full_series_data['tags'].append(tag_id)
            if not update_sonarr_series(full_series_data):
                return jsonify({'status': 'error', 'message': 'Failed to update series in Sonarr.'}), 500

        # --- Logique de suppression de fichiers (RESTAURÉE) ---
        if options.get('deleteFiles'):
            episode_files = get_sonarr_episode_files(sonarr_series['id'])
            if episode_files is None:
                return jsonify({'status': 'error', 'message': 'Could not retrieve episode file list from Sonarr.'}), 500

            last_deleted_filepath = None
            deleted_count = 0
            for file_info in episode_files:
                media_filepath = file_info.get('path')
                if media_filepath and os.path.exists(media_filepath):
                    try:
                        if not _is_dry_run_mode(): os.remove(media_filepath)
                        last_deleted_filepath = media_filepath
                        deleted_count += 1
                        current_app.logger.info(f"ARCHIVE SHOW: {'[SIMULATION] ' if _is_dry_run_mode() else ''}Deleting file: {media_filepath}")
                    except Exception as e_file:
                        current_app.logger.error(f"Failed to delete file {media_filepath}: {e_file}")

            if last_deleted_filepath:
                # On a déjà 'admin_plex_server', on peut l'utiliser pour le nettoyage
                library_sections = admin_plex_server.library.sections()
                temp_roots = {os.path.normpath(loc) for lib in library_sections for loc in lib.locations}
                temp_guards = {os.path.normpath(os.path.splitdrive(r)[0] + os.sep) if os.path.splitdrive(r)[0] else os.path.normpath(os.sep + r.split(os.sep)[1]) for r in temp_roots if r}
                cleanup_parent_directory_recursively(last_deleted_filepath, list(temp_roots), list(temp_guards))
            
            flash(f"{deleted_count} fichier(s) supprimés (ou leur suppression simulée).", "success")

        return jsonify({'status': 'success', 'message': f"Série '{show.title}' archivée avec succès."})

    except NotFound:
        return jsonify({'status': 'error', 'message': f"Show with ratingKey {rating_key} not found."}), 404
    except Exception as e:
        current_app.logger.error(f"Error archiving show: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- FONCTION DE TRAITEMENT POUR LA GESTION DES SAISONS ---
def handle_manage_seasons_post(rating_key):
    """Traite les soumissions du formulaire de la page de gestion des saisons."""
    form_data = request.form
    seasons_to_monitor = set(form_data.getlist('monitored_seasons', type=int))
    seasons_to_delete = set(form_data.getlist('delete_seasons', type=int))

    current_app.logger.info(f"Gestion des saisons pour la série {rating_key}: Surveiller={seasons_to_monitor}, Supprimer={seasons_to_delete}")

    admin_plex_server = get_plex_admin_server()
    if not admin_plex_server:
        flash("Erreur de connexion admin à Plex.", "danger")
        return redirect(url_for('plex_editor.manage_seasons', rating_key=rating_key))

    try:
        show = admin_plex_server.fetchItem(rating_key)

        sonarr_series = next((s for g in show.guids if (s := get_sonarr_series_by_guid(g.id))), None)
        if not sonarr_series:
            flash("Série non trouvée dans Sonarr.", "danger")
            return redirect(url_for('plex_editor.manage_seasons', rating_key=rating_key))

        series_id = sonarr_series['id']
        full_series_data = get_sonarr_series_by_id(series_id)
        if not full_series_data:
            flash("Impossible de récupérer les détails de la série depuis Sonarr.", "danger")
            return redirect(url_for('plex_editor.manage_seasons', rating_key=rating_key))

        # --- ÉTAPE 1: Mettre à jour le monitoring ---
        monitoring_changed = False
        for season in full_series_data.get('seasons', []):
            is_monitored = season.get('seasonNumber') in seasons_to_monitor
            if season.get('monitored') != is_monitored:
                season['monitored'] = is_monitored
                monitoring_changed = True

        if monitoring_changed:
            if update_sonarr_series(full_series_data):
                flash("Statut de surveillance des saisons mis à jour dans Sonarr.", "success")
            else:
                flash("Échec de la mise à jour de la surveillance dans Sonarr.", "danger")

        # --- ÉTAPE 2: Supprimer les fichiers ---
        if seasons_to_delete:
            episode_files = get_sonarr_episode_files(series_id)
            if episode_files:
                files_to_delete = [f for f in episode_files if f.get('seasonNumber') in seasons_to_delete]
                deleted_count = 0
                last_deleted_filepath = None
                for file_info in files_to_delete:
                    filepath = file_info.get('path')
                    if filepath and os.path.exists(filepath):
                        try:
                            if not _is_dry_run_mode(): os.remove(filepath)
                            deleted_count += 1
                            last_deleted_filepath = filepath
                        except Exception as e:
                            current_app.logger.error(f"Impossible de supprimer le fichier {filepath}: {e}")

                if deleted_count > 0:
                    flash(f"{deleted_count} fichier(s) ont été supprimés (ou leur suppression simulée).", "success")

                if last_deleted_filepath:
                    library_sections = admin_plex_server.library.sections()
                    temp_roots = {os.path.normpath(loc) for lib in library_sections for loc in lib.locations}
                    temp_guards = {os.path.normpath(os.path.splitdrive(r)[0] + os.sep) if os.path.splitdrive(r)[0] else os.path.normpath(os.sep + r.split(os.sep)[1]) for r in temp_roots if r}
                    cleanup_parent_directory_recursively(last_deleted_filepath, list(temp_roots), list(temp_guards))

        # --- ÉTAPE 3: Déclencher un scan Plex ---
        try:
            show_library = admin_plex_server.library.section(show.librarySectionTitle)
            if not _is_dry_run_mode(): show_library.update()
            flash("Scan de la bibliothèque Plex déclenché.", "info")
        except Exception as e:
            current_app.logger.warning(f"Impossible de déclencher le scan Plex: {e}")

        return redirect(url_for('plex_editor.manage_seasons', rating_key=rating_key))

    except Exception as e:
        current_app.logger.error(f"Erreur dans handle_manage_seasons_post: {e}", exc_info=True)
        flash("Une erreur inattendue est survenue.", "danger")
        return redirect(url_for('plex_editor.manage_seasons', rating_key=rating_key))


# --- ROUTE PRINCIPALE POUR LA GESTION DES SAISONS ---
@plex_editor_bp.route('/manage_seasons/<int:rating_key>', methods=['GET', 'POST'])
@login_required
def manage_seasons(rating_key):
    if request.method == 'POST':
        return handle_manage_seasons_post(rating_key)

    # --- Logique GET ---
    user_plex_server = get_user_specific_plex_server()
    if not user_plex_server:
        return redirect(url_for('plex_editor.index'))

    try:
        show = user_plex_server.fetchItem(rating_key)
        if not show or show.type != 'show': abort(404)

        sonarr_series = next((s for g in show.guids if (s := get_sonarr_series_by_guid(g.id))), None)
        if not sonarr_series:
            return render_template('plex_editor/manage_seasons.html', show=show, seasons_data=[], library_name=show.librarySectionTitle, error_message="Série non trouvée dans Sonarr.")

        full_sonarr_series_data = get_sonarr_series_by_id(sonarr_series['id'])
        if not full_sonarr_series_data:
             return render_template('plex_editor/manage_seasons.html', show=show, seasons_data=[], library_name=show.librarySectionTitle, error_message="Impossible de récupérer les détails de Sonarr.")

        seasons_data = []
        for plex_season in show.seasons():
            sonarr_season_info = next((s for s in full_sonarr_series_data.get('seasons', []) if s.get('seasonNumber') == plex_season.seasonNumber), None)

            seasons_data.append({
                'title': plex_season.title,
                'index': plex_season.seasonNumber,
                'leafCount': plex_season.leafCount,
                'viewedLeafCount': plex_season.viewedLeafCount,
                'monitored': sonarr_season_info.get('monitored', False) if sonarr_season_info else False,
            })

        return render_template('plex_editor/manage_seasons.html',
                               show=show,
                               seasons_data=seasons_data,
                               library_name=show.librarySectionTitle,
                               error_message=None)

    except Exception as e:
        current_app.logger.error(f"Erreur dans manage_seasons (GET): {e}", exc_info=True)
        flash("Une erreur est survenue lors du chargement de la page.", "danger")
        return redirect(url_for('plex_editor.list_libraries'))
@plex_editor_bp.route('/reject_show', methods=['POST'])
@login_required
def reject_show_route():
    rating_key = request.get_json().get('ratingKey')
    if not rating_key:
        return jsonify({'status': 'error', 'message': 'Missing ratingKey.'}), 400

    admin_plex_server = get_plex_admin_server()
    if not admin_plex_server:
        return jsonify({'status': 'error', 'message': 'Could not connect to Plex server.'}), 500

    try:
        show = admin_plex_server.fetchItem(rating_key)

        sonarr_series = next((s for g in show.guids if (s := get_sonarr_series_by_guid(g.id))), None)
        if not sonarr_series:
            return jsonify({'status': 'error', 'message': 'Show not found in Sonarr.'}), 404

        # Mise à jour Sonarr
        series_id = sonarr_series['id']
        full_series_data = get_sonarr_series_by_id(series_id)
        full_series_data['monitored'] = False

        tag_label = 'rejeté' # Tu peux rendre ce tag configurable plus tard
        tag_id = get_sonarr_tag_id(tag_label)
        if tag_id and tag_id not in full_series_data.get('tags', []):
            full_series_data['tags'].append(tag_id)

        update_sonarr_series(full_series_data)

        # Suppression des fichiers
        episode_files = get_sonarr_episode_files(series_id)
        if episode_files:
            last_deleted_filepath = None
            for file_info in episode_files:
                filepath = file_info.get('path')
                if filepath and os.path.exists(filepath):
                    try:
                        if not _is_dry_run_mode(): os.remove(filepath)
                        last_deleted_filepath = filepath
                    except Exception as e:
                        current_app.logger.error(f"Impossible de supprimer le fichier {filepath}: {e}")

            # Nettoyage des dossiers après la suppression
            if last_deleted_filepath:
                current_app.logger.info(f"Lancement du nettoyage récursif pour le rejet à partir de {last_deleted_filepath}")
                library_sections = admin_plex_server.library.sections()
                temp_roots = {os.path.normpath(loc) for lib in library_sections for loc in lib.locations}
                temp_guards = {os.path.normpath(os.path.splitdrive(r)[0] + os.sep) if os.path.splitdrive(r)[0] else os.path.normpath(os.sep + r.split(os.sep)[1]) for r in temp_roots if r}
                cleanup_parent_directory_recursively(
                    last_deleted_filepath,
                    dynamic_plex_library_roots=list(temp_roots),
                    base_paths_guards=list(temp_guards)
                )

        # Scan Plex
        try:
            show_library = admin_plex_server.library.section(show.librarySectionTitle)
            if not _is_dry_run_mode(): show_library.update()
            flash("Scan de la bibliothèque Plex déclenché.", "info")
        except Exception as e:
            current_app.logger.warning(f"Impossible de déclencher le scan Plex: {e}")

        return jsonify({'status': 'success', 'message': f"Série '{show.title}' rejetée et supprimée."})

    except Exception as e:
        current_app.logger.error(f"Error rejecting show: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
# --- ROUTE API POUR RÉCUPÉRER LES DÉTAILS D'UN ITEM POUR LA MODALE ---
@plex_editor_bp.route('/api/media_details/<int:rating_key>')
@login_required
def get_media_details_for_modal(rating_key): # Renommé pour clarté, bien que le nom de la route soit le plus important
    """Récupère et retourne les détails d'un média pour la modale."""
    try:
        # Utilisation de get_plex_admin_server() car il est probable qu'il soit déjà configuré et utilisé ailleurs.
        # Si une instance PlexClient dédiée est nécessaire, il faudrait l'implémenter.
        # Pour l'instant, on part du principe que get_plex_admin_server() retourne une instance PlexServer compatible.
        plex_server_instance = get_plex_admin_server()
        if not plex_server_instance:
            current_app.logger.error(f"API get_media_details: Impossible d'obtenir une connexion admin Plex.")
            return jsonify({'error': 'Connexion au serveur Plex admin échouée.'}), 500

        item = plex_server_instance.fetchItem(rating_key)

        if not item:
            # fetchItem lève NotFound, donc ce bloc pourrait ne pas être atteint,
            # mais c'est une bonne pratique de le garder.
            return jsonify({'error': 'Média non trouvé'}), 404

        # Construire un dictionnaire avec toutes les infos nécessaires pour la modale
        # Adapter les noms des attributs aux vrais noms de l'API Plex via plexapi.
        details = {
            'title': getattr(item, 'title', 'Titre inconnu'),
            'originalTitle': getattr(item, 'originalTitle', None), # <-- AJOUTE CETTE LIGNE
            'year': getattr(item, 'year', ''),
            'summary': getattr(item, 'summary', 'Aucun résumé disponible.'),
            'tagline': getattr(item, 'tagline', ''), # Souvent appelé 'tagline' dans Plex
            'rating': getattr(item, 'rating', ''), # Note sur 10 (ex: 7.5)
            'genres': [genre.tag for genre in getattr(item, 'genres', [])],
            # admin_plex_server.url(item.thumb, includeToken=True) est la méthode correcte pour obtenir l'URL complète
            'poster_url': plex_server_instance.url(getattr(item, 'thumb', ''), includeToken=True) if getattr(item, 'thumb', '') else None,
            'duration_ms': getattr(item, 'duration', 0) # Durée en millisecondes
        }

        # Convertir la durée en format lisible (HH:MM:SS ou MM:SS)
        duration_ms = details.get('duration_ms', 0)
        if duration_ms > 0:
            seconds_total = int(duration_ms / 1000)
            hours = seconds_total // 3600
            minutes = (seconds_total % 3600) // 60
            seconds = seconds_total % 60
            if hours > 0:
                details['duration_readable'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                details['duration_readable'] = f"{minutes:02d}:{seconds:02d}"
        else:
            details['duration_readable'] = "N/A"

        return jsonify(details)

    except NotFound:
        current_app.logger.warning(f"API get_media_details: Média avec ratingKey {rating_key} non trouvé (NotFound Exception).")
        return jsonify({'error': f'Média avec ratingKey {rating_key} non trouvé.'}), 404
    except Unauthorized: # Au cas où le token admin n'est pas valide
        current_app.logger.error(f"API get_media_details: Autorisation refusée pour récupérer les détails de {rating_key}. Token admin invalide ?")
        return jsonify({'error': 'Autorisation refusée par le serveur Plex.'}), 401
    except Exception as e:
        current_app.logger.error(f"Erreur API lors de la récupération des détails pour {rating_key}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# Dans app/plex_editor/routes.py

# Dans app/plex_editor/routes.py

# Dans app/plex_editor/routes.py

@plex_editor_bp.route('/api/series_details/<int:rating_key>', methods=['POST'])
@login_required
def get_series_details_for_management(rating_key):
    """Récupère les détails complets d'une série pour la modale de gestion."""
    data = request.get_json()
    user_id = data.get('userId')

    if not user_id:
        return '<div class="alert alert-danger">Erreur: ID utilisateur manquant.</div>', 400

    try:
        # (La logique de connexion sans session est correcte et reste la même)
        # ...
        admin_plex_server_for_token = get_plex_admin_server()
        if not admin_plex_server_for_token: return ('<div class="alert alert-danger">Erreur: Connexion admin.</div>', 500)
        main_account = admin_plex_server_for_token.myPlexAccount()
        user_plex_server = None
        plex_url = current_app.config.get('PLEX_URL')
        if str(main_account.id) == user_id: user_plex_server = admin_plex_server_for_token
        else:
            user_to_impersonate = next((u for u in main_account.users() if str(u.id) == user_id), None)
            if user_to_impersonate:
                token = user_to_impersonate.get_token(admin_plex_server_for_token.machineIdentifier)
                user_plex_server = PlexServer(plex_url, token)
            else: return f'<div class="alert alert-danger">Erreur: Utilisateur {user_id} non trouvé.</div>', 404
        if not user_plex_server: return ('<div class="alert alert-danger">Erreur: Connexion Plex utilisateur.</div>', 500)

        series = user_plex_server.fetchItem(rating_key)
        if not series or series.type != 'show': return f'<div class="alert alert-warning">Série non trouvée.</div>', 404

        # (Logique Sonarr inchangée et correcte)
        sonarr_series_full_details = None; sonarr_series_id_val = None; is_monitored_global_status = False
        tvdb_id = next((g.id.replace('tvdb://', '') for g in series.guids if g.id.startswith('tvdb://')), None)
        if tvdb_id:
            sonarr_series_info = get_sonarr_series_by_guid(f"tvdb://{tvdb_id}")
            if sonarr_series_info: sonarr_series_id_val = sonarr_series_info.get('id')
            if sonarr_series_id_val:
                sonarr_series_full_details = get_sonarr_series_by_id(sonarr_series_id_val)
                if sonarr_series_full_details: is_monitored_global_status = sonarr_series_full_details.get('monitored', False)

        all_sonarr_episodes = get_sonarr_episodes_by_series_id(sonarr_series_id_val) if sonarr_series_id_val else []

        seasons_list = []
        total_series_size = 0; viewed_seasons_count = 0

        for season in series.seasons():
            if season.isWatched: viewed_seasons_count += 1
            sonarr_season_info = next((s for s in sonarr_series_full_details.get('seasons', []) if s.get('seasonNumber') == season.seasonNumber), None) if sonarr_series_full_details else None

            episodes_list_for_season = []
            total_season_size = 0
            for episode in season.episodes():
                # --- CORRECTION 1 : On restaure la taille depuis PLEX ---
                size_bytes = getattr(episode.media[0].parts[0], 'size', 0) if episode.media and episode.media[0].parts else 0
                total_season_size += size_bytes

                sonarr_episode_data = next((e for e in all_sonarr_episodes if e.get('seasonNumber') == episode.seasonNumber and e.get('episodeNumber') == episode.index), None)
                sonarr_file_id = sonarr_episode_data.get('episodeFileId', 0) if sonarr_episode_data else 0

                episodes_list_for_season.append({
                    'title': episode.title,
                    'episodeNumber': episode.index,
                    'ratingKey': episode.ratingKey,
                    'isWatched': episode.isWatched,
                    'size_on_disk': size_bytes,
                    'sonarr_episodeId': sonarr_episode_data.get('id') if sonarr_episode_data else None,
                    'sonarr_episodeFileId': sonarr_file_id,
                    'isMonitored_sonarr': sonarr_episode_data.get('monitored', False) if sonarr_episode_data else False
                })

            total_series_size += total_season_size

            seasons_list.append({
                'title': season.title, 'ratingKey': season.ratingKey,
                'seasonNumber': season.seasonNumber, 'total_episodes': season.leafCount,
                'viewed_episodes': season.viewedLeafCount,
                'is_monitored_season': sonarr_season_info.get('monitored', False) if sonarr_season_info else False,
                'total_size_on_disk': total_season_size, 'episodes': episodes_list_for_season
            })

        series_data = {
            'title': series.title, 'ratingKey': series.ratingKey,
            'plex_status': getattr(series, 'status', 'unknown'),
            'total_seasons_plex': series.childCount, 'viewed_seasons_plex': viewed_seasons_count,
            'is_monitored_global': is_monitored_global_status, 'sonarr_series_id': sonarr_series_id_val,
            'total_size_on_disk': total_series_size, 'seasons': seasons_list
        }

        return render_template('plex_editor/_series_management_modal_content.html', series=series_data)

    except NotFound:
        return f'<div class="alert alert-warning">Série {rating_key} non trouvée.</div>', 404
    except Exception as e:
        current_app.logger.error(f"Erreur API (series_details): {e}", exc_info=True)
        return f'<div class="alert alert-danger">Erreur serveur: {str(e)}</div>', 500
        
@plex_editor_bp.route('/api/season/<int:season_plex_id>/toggle_monitor', methods=['POST'])
@login_required
def toggle_season_monitoring(season_plex_id):
    """Active ou désactive la surveillance d'une saison spécifique dans Sonarr."""
    try:
        # On a besoin du contexte admin pour fetchItem et potentiellement pour les infos de la série parente
        admin_plex_server = get_plex_admin_server()
        if not admin_plex_server:
            return jsonify({'status': 'error', 'message': "Connexion admin Plex échouée."}), 500

        plex_season = admin_plex_server.fetchItem(season_plex_id)
        if not plex_season or plex_season.type != 'season':
            return jsonify({'status': 'error', 'message': "Saison Plex non trouvée ou type incorrect."}), 404

        plex_series = plex_season.parent
        if not plex_series:
            return jsonify({'status': 'error', 'message': "Série parente non trouvée pour cette saison."}), 404

        current_app.logger.info(f"Toggle monitor pour saison Plex '{plex_season.title}' (ID: {season_plex_id}) de la série '{plex_series.title}'.")

        # Trouver la série Sonarr correspondante
        sonarr_series_details = None
        tvdb_id = None
        for g in plex_series.guids:
            if g.id.startswith('tvdb://'):
                tvdb_id = g.id.replace('tvdb://', '')
                break

        if tvdb_id:
            # Tenter de récupérer la série Sonarr par son TVDB ID.
            # get_sonarr_series_by_guid s'attend à un GUID formaté comme 'tvdb://12345'
            sonarr_series_initial_info = get_sonarr_series_by_guid(f"tvdb://{tvdb_id}")
            if sonarr_series_initial_info and 'id' in sonarr_series_initial_info:
                 # Récupérer les détails complets de la série pour avoir l'état de toutes les saisons
                sonarr_series_details = get_sonarr_series_by_id(sonarr_series_initial_info['id'])
            else: # Tentative par titre/année si GUID échoue (moins fiable)
                current_app.logger.warning(f"Série Sonarr non trouvée par TVDB ID {tvdb_id} pour '{plex_series.title}'. Tentative par titre.")
                # Cette partie est plus complexe et sujette à erreurs, à implémenter avec prudence si nécessaire.
                # Pour l'instant, on considère que si non trouvé par TVDB ID, c'est un échec.

        if not sonarr_series_details:
            current_app.logger.error(f"Impossible de trouver la série '{plex_series.title}' dans Sonarr.")
            return jsonify({'status': 'error', 'message': f"Série '{plex_series.title}' non trouvée dans Sonarr."}), 404

        # Trouver la saison Sonarr et inverser son état 'monitored'
        target_sonarr_season_number = plex_season.seasonNumber
        sonarr_season_found = False
        new_monitored_state = False

        if 'seasons' in sonarr_series_details:
            for sonarr_s_data in sonarr_series_details['seasons']:
                if sonarr_s_data.get('seasonNumber') == target_sonarr_season_number:
                    current_monitored_state = sonarr_s_data.get('monitored', False)
                    sonarr_s_data['monitored'] = not current_monitored_state
                    new_monitored_state = sonarr_s_data['monitored']
                    sonarr_season_found = True
                    break

        if not sonarr_season_found:
            return jsonify({'status': 'error', 'message': f"Saison {target_sonarr_season_number} non trouvée dans les données Sonarr pour la série."}), 404

        # Mettre à jour la série dans Sonarr avec le nouvel état de la saison
        if update_sonarr_series(sonarr_series_details):
            status_text = "activée" if new_monitored_state else "désactivée"
            current_app.logger.info(f"Surveillance pour la saison Plex {season_plex_id} (Sonarr S{target_sonarr_season_number}) changée à '{status_text}'.")
            return jsonify({
                'status': 'success',
                'message': f"Surveillance pour la saison {plex_season.title} {status_text}.",
                'monitored': new_monitored_state
            })
        else:
            current_app.logger.error(f"Échec de la mise à jour de la série dans Sonarr pour saison {season_plex_id}.")
            return jsonify({'status': 'error', 'message': "Échec de la mise à jour dans Sonarr."}), 500

    except NotFound:
        current_app.logger.warning(f"API toggle_season_monitoring: Saison Plex avec ID {season_plex_id} non trouvée.")
        return jsonify({'status': 'error', 'message': f"Saison Plex ID {season_plex_id} non trouvée."}), 404
    except Exception as e:
        current_app.logger.error(f"Erreur API toggle_season_monitoring pour saison {season_plex_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@plex_editor_bp.route('/api/season/<int:season_plex_id>', methods=['DELETE'])
@login_required
def delete_season_files_and_unmonitor(season_plex_id):
    """
    Supprime les fichiers d'une saison via Sonarr, la passe en non-surveillée,
    et rafraîchit Plex.
    """
    try:
        admin_plex_server = get_plex_admin_server()
        if not admin_plex_server:
            return jsonify({'status': 'error', 'message': "Connexion admin Plex échouée."}), 500

        plex_season = admin_plex_server.fetchItem(season_plex_id)
        if not plex_season or plex_season.type != 'season':
            return jsonify({'status': 'error', 'message': "Saison Plex non trouvée ou type incorrect."}), 404

        plex_series = plex_season.show()
        if not plex_series:
            return jsonify({'status': 'error', 'message': "Série parente non trouvée pour cette saison."}), 404

        current_app.logger.info(f"Requête de suppression pour saison Plex '{plex_season.title}' (ID: {season_plex_id}) de la série '{plex_series.title}'.")

        # 1. Trouver la série Sonarr
        sonarr_series_details = None
        tvdb_id = next((g.id.replace('tvdb://', '') for g in plex_series.guids if g.id.startswith('tvdb://')), None)

        if tvdb_id:
            sonarr_series_initial_info = get_sonarr_series_by_guid(f"tvdb://{tvdb_id}")
            if sonarr_series_initial_info and 'id' in sonarr_series_initial_info:
                sonarr_series_details = get_sonarr_series_by_id(sonarr_series_initial_info['id'])

        if not sonarr_series_details:
            return jsonify({'status': 'error', 'message': f"Série '{plex_series.title}' non trouvée dans Sonarr."}), 404

        sonarr_series_id = sonarr_series_details['id']
        target_sonarr_season_number = plex_season.seasonNumber

        # 2. Mettre la saison en non-surveillée dans Sonarr
        sonarr_season_found_for_monitoring_update = False
        if 'seasons' in sonarr_series_details:
            for sonarr_s_data in sonarr_series_details['seasons']:
                if sonarr_s_data.get('seasonNumber') == target_sonarr_season_number:
                    sonarr_s_data['monitored'] = False
                    sonarr_season_found_for_monitoring_update = True
                    break

        if not sonarr_season_found_for_monitoring_update:
            # Ne pas bloquer si la saison n'est pas trouvée pour le monitoring, mais logguer.
            current_app.logger.warning(f"Saison {target_sonarr_season_number} non explicitement trouvée dans Sonarr pour mise à jour monitoring, suppression des fichiers continue.")

        # Il faut envoyer la mise à jour de la série Sonarr même si on va supprimer des fichiers ensuite
        # car la suppression d'épisodes ne change pas l'état de monitoring de la saison.
        if sonarr_season_found_for_monitoring_update: # Seulement si on a modifié quelque chose
            if not update_sonarr_series(sonarr_series_details):
                # Non bloquant pour la suppression, mais à noter.
                current_app.logger.warning(f"Échec de la mise à jour du monitoring de la saison {target_sonarr_season_number} dans Sonarr avant suppression des fichiers.")

        # 3. Supprimer les fichiers des épisodes de cette saison via Sonarr
        # Sonarr API v3 permet de supprimer les fichiers d'épisodes.
        # Il faut d'abord lister les fichiers des épisodes de la saison concernée.
        all_episode_files = get_sonarr_episode_files(sonarr_series_id)
        if all_episode_files is None: # Erreur de communication avec Sonarr
             return jsonify({'status': 'error', 'message': "Impossible de récupérer la liste des fichiers d'épisodes depuis Sonarr."}), 500

        episode_file_ids_to_delete = []
        for ep_file in all_episode_files:
            if ep_file.get('seasonNumber') == target_sonarr_season_number:
                episode_file_ids_to_delete.append(ep_file['id'])

        if not episode_file_ids_to_delete:
            current_app.logger.info(f"Aucun fichier d'épisode trouvé dans Sonarr pour la saison {target_sonarr_season_number} de la série '{plex_series.title}'.")
            # On continue pour scanner Plex, au cas où.
        else:
            # Supprimer les fichiers d'épisodes en bloc si l'API Sonarr le permet, sinon un par un.
            # L'API Sonarr /api/v3/episodeFile/{id} avec DELETE supprime un fichier.
            # Pour une suppression en masse, il y a /api/v3/episodeFile/bulk avec corps {"episodeFileIds": [ids]}
            from app.utils.arr_client import sonarr_delete_episode_files_bulk # Supposons que cette fonction existe

            # _is_dry_run_mode() n'est pas défini ici, on va supposer que ce n'est pas un dry run pour l'instant
            # ou alors il faudrait le passer en argument ou le récupérer depuis la config.
            # Pour l'instant, on effectue la suppression réelle.
            # TODO: Intégrer _is_dry_run_mode() si nécessaire

            is_simulating = _is_dry_run_mode() # Récupérer le mode dry_run
            dry_run_prefix = "[SIMULATION] " if is_simulating else ""

            current_app.logger.info(f"{dry_run_prefix}Tentative de suppression de {len(episode_file_ids_to_delete)} fichier(s) pour la saison {target_sonarr_season_number} via Sonarr.")
            if not is_simulating:
                if sonarr_delete_episode_files_bulk(episode_file_ids_to_delete):
                    current_app.logger.info(f"{len(episode_file_ids_to_delete)} fichier(s) de la saison {target_sonarr_season_number} supprimés via Sonarr.")
                else:
                    current_app.logger.error(f"Échec de la suppression en masse des fichiers de la saison {target_sonarr_season_number} via Sonarr.")
                    # On pourrait tenter une suppression individuelle ici en fallback, ou retourner une erreur.
                    return jsonify({'status': 'error', 'message': "Échec de la suppression des fichiers via Sonarr."}), 500
            else:
                 current_app.logger.info(f"[SIMULATION] {len(episode_file_ids_to_delete)} fichier(s) de la saison {target_sonarr_season_number} seraient supprimés via Sonarr.")

        # --- NOUVEAU : NETTOYAGE DU DOSSIER DE LA SAISON SI NÉCESSAIRE ---
        last_deleted_filepath = None
        if episode_file_ids_to_delete:
            # On a besoin d'un chemin de fichier pour démarrer le nettoyage
            # On prend le premier fichier de la liste pour trouver son chemin
            first_file_details = next((ep for ep in all_episode_files if ep['id'] == episode_file_ids_to_delete[0]), None)
            if first_file_details:
                last_deleted_filepath = first_file_details.get('path')

        if last_deleted_filepath and not is_simulating:
            try:
                current_app.logger.info("Lancement du nettoyage de dossier après suppression des fichiers de la saison.")
                # On a déjà 'admin_plex_server', on peut l'utiliser
                library_sections = admin_plex_server.library.sections()
                root_paths = {os.path.normpath(loc) for lib in library_sections for loc in lib.locations}
                guard_paths = {os.path.normpath(os.path.splitdrive(r)[0] + os.sep) if os.path.splitdrive(r)[0] else os.path.normpath(os.sep + r.split(os.sep)[1]) for r in root_paths if r}
                
                cleanup_parent_directory_recursively(last_deleted_filepath, list(root_paths), list(guard_paths))
            except Exception as e_cleanup:
                current_app.logger.error(f"Erreur pendant le nettoyage du dossier : {e_cleanup}", exc_info=True)
        # --- FIN DU NOUVEAU BLOC ---

        # 4. Déclencher un scan de la bibliothèque Plex
        try:
            plex_library = admin_plex_server.library.sectionByID(plex_series.librarySectionID)
            current_app.logger.info(f"Déclenchement d'un scan de la bibliothèque Plex '{plex_library.title}' après suppression de la saison.")
            if not _is_dry_run_mode(): # Respecter le dry_run pour le scan aussi
                plex_library.update()
            else:
                current_app.logger.info(f"[SIMULATION] Scan de la bibliothèque '{plex_library.title}' serait déclenché.")

        except Exception as e_scan:
            current_app.logger.error(f"Échec du déclenchement du scan Plex: {e_scan}", exc_info=True)
            # Ne pas retourner une erreur bloquante ici, la suppression a peut-être eu lieu.

        # La saison n'est pas supprimée de Plex elle-même, seulement ses fichiers et son monitoring.
        # L'utilisateur verra la saison sans épisodes (ou Plex la masquera après le scan).
        return jsonify({'status': 'success', 'message': f"Les fichiers de la saison '{plex_season.title}' ont été supprimés (ou leur suppression simulée) et la saison n'est plus surveillée."})

    except NotFound:
        current_app.logger.warning(f"API delete_season: Saison Plex avec ID {season_plex_id} non trouvée.")
        return jsonify({'status': 'error', 'message': f"Saison Plex ID {season_plex_id} non trouvée."}), 404
    except Exception as e:
        current_app.logger.error(f"Erreur API delete_season pour saison {season_plex_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@plex_editor_bp.route('/api/episodes/delete_bulk', methods=['POST'])
@login_required
def bulk_delete_episodes():
    """Supprime une liste de fichiers d'épisodes via Sonarr."""
    data = request.get_json()
    episode_file_ids = data.get('episodeFileIds', [])

    if not episode_file_ids:
        return jsonify({'status': 'warning', 'message': 'Aucun épisode sélectionné.'}), 400

    # On s'assure que les IDs sont bien des entiers
    try:
        episode_file_ids = [int(id) for id in episode_file_ids]
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Liste d_IDs invalide.'}), 400

    is_simulating = _is_dry_run_mode()
    dry_run_prefix = "[SIMULATION] " if is_simulating else ""

    current_app.logger.info(f"{dry_run_prefix}Demande de suppression pour {len(episode_file_ids)} fichier(s) via Sonarr.")

    if not is_simulating:
        # On importe la fonction utilitaire de arr_client
        from app.utils.arr_client import sonarr_delete_episode_files_bulk
        success = sonarr_delete_episode_files_bulk(episode_file_ids)
        if success:
            flash(f"{len(episode_file_ids)} fichier(s) d'épisode(s) ont été supprimés avec succès via Sonarr.", "success")
            return jsonify({'status': 'success', 'message': 'Fichiers supprimés.'})
        else:
            flash("Une erreur est survenue lors de la suppression des fichiers via Sonarr.", "danger")
            return jsonify({'status': 'error', 'message': 'Échec de la suppression via Sonarr.'}), 500
    else: # En mode simulation
        flash(f"[SIMULATION] {len(episode_file_ids)} fichier(s) d'épisode(s) seraient supprimés via Sonarr.", "info")
        return jsonify({'status': 'success', 'message': 'Suppression simulée.'})

@plex_editor_bp.route('/api/episodes/update_monitoring', methods=['POST'])
@login_required
def update_episodes_monitoring():
    data = request.get_json()
    episodes_to_update = data.get('episodes', [])
    if not episodes_to_update:
        return jsonify({'status': 'warning', 'message': 'Aucune donnée reçue.'}), 400

    # On importe la NOUVELLE fonction
    from app.utils.arr_client import sonarr_update_episodes_monitoring_bulk

    # On regroupe les épisodes par statut
    to_monitor = [ep.get('episodeId') for ep in episodes_to_update if ep.get('monitored') is True and ep.get('episodeId')]
    to_unmonitor = [ep.get('episodeId') for ep in episodes_to_update if ep.get('monitored') is False and ep.get('episodeId')]

    success = True
    if to_monitor:
        if not sonarr_update_episodes_monitoring_bulk(to_monitor, True):
            success = False
    if to_unmonitor:
        if not sonarr_update_episodes_monitoring_bulk(to_unmonitor, False):
            success = False

    if success:
        flash(f"{len(episodes_to_update)} statut(s) de monitoring mis à jour.", "success")
        return jsonify({'status': 'success', 'message': 'Mise à jour réussie.'})

    return jsonify({'status': 'error', 'message': 'Une ou plusieurs mises à jour ont échoué.'}), 500

@plex_editor_bp.route('/api/series/<int:sonarr_series_id>/toggle_monitor_global', methods=['POST'])
@login_required
def toggle_global_series_monitoring(sonarr_series_id):
    """Active ou désactive la surveillance globale d'une série dans Sonarr."""
    try:
        if not sonarr_series_id:
            return jsonify({'status': 'error', 'message': "ID de série Sonarr manquant."}), 400

        current_app.logger.info(f"Toggle monitor global pour série Sonarr ID: {sonarr_series_id}.")

        sonarr_series = get_sonarr_series_by_id(sonarr_series_id)
        if not sonarr_series:
            return jsonify({'status': 'error', 'message': f"Série Sonarr avec ID {sonarr_series_id} non trouvée."}), 404

        current_monitored_status = sonarr_series.get('monitored', False)
        sonarr_series['monitored'] = not current_monitored_status
        new_monitored_state = sonarr_series['monitored']

        # Mettre à jour la série dans Sonarr
        if update_sonarr_series(sonarr_series):
            status_text = "activée" if new_monitored_state else "désactivée"
            current_app.logger.info(f"Surveillance globale pour la série Sonarr {sonarr_series_id} changée à '{status_text}'.")
            return jsonify({
                'status': 'success',
                'message': f"Surveillance globale {status_text} pour la série.",
                'monitored': new_monitored_state
            })
        else:
            current_app.logger.error(f"Échec de la mise à jour de la série Sonarr {sonarr_series_id} pour le monitoring global.")
            return jsonify({'status': 'error', 'message': "Échec de la mise à jour du statut de surveillance global dans Sonarr."}), 500

    except Exception as e:
        current_app.logger.error(f"Erreur API toggle_global_series_monitoring pour série Sonarr ID {sonarr_series_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@plex_editor_bp.route('/update_season_monitoring', methods=['POST'])
@login_required
def update_season_monitoring():
    data = request.get_json()
    series_id = data.get('sonarrSeriesId')
    season_number = data.get('seasonNumber')
    status = data.get('monitored')

    if series_id is None or season_number is None or status is None:
        return jsonify({'status': 'error', 'message': 'Données manquantes.'}), 400

    from app.utils.arr_client import sonarr_update_season_monitoring

    if sonarr_update_season_monitoring(series_id, season_number, status):
        return jsonify({'status': 'success', 'message': 'Statut de la saison mis à jour.'})

    return jsonify({'status': 'error', 'message': 'Échec de la mise à jour dans Sonarr.'}), 500

@plex_editor_bp.route('/api/episodes/update_monitoring_single', methods=['POST'])
@login_required
def update_single_episode_monitoring():
    data = request.get_json()
    episode_id = data.get('episodeId')
    status = data.get('monitored')

    if episode_id is None or status is None:
        return jsonify({'status': 'error', 'message': 'Données manquantes.'}), 400

    # On importe la fonction que nous avions déjà créée
    from app.utils.arr_client import sonarr_update_episode_monitoring

    if sonarr_update_episode_monitoring(episode_id, status):
        return jsonify({'status': 'success', 'message': 'Statut de l_épisode mis à jour.'})

    return jsonify({'status': 'error', 'message': 'Échec de la mise à jour dans Sonarr.'}), 500

# --- Gestionnaires d'erreur ---
#@app.errorhandler(404)
#def page_not_found(e):
#    user_title = session.get('plex_user_title')
#    current_app.logger.warning(f"Erreur 404: {request.url}, Description: {getattr(e, 'description', 'N/A')}, User: {user_title}")
#    return render_template('plex_editor/404.html', error=e, user_title=user_title), 404

#@app.errorhandler(500)
#def internal_server_error(e):
#    user_title = session.get('plex_user_title')
#    current_app.logger.error(f"Erreur 500: {request.url}, Erreur: {e}, User: {user_title}", exc_info=True)
#    flash("Une erreur interne imprévue est survenue. L'administrateur a été notifié.", "danger")
#    return render_template('plex_editor/500.html', error=e, user_title=user_title), 500