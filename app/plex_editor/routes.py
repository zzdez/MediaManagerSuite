# app/plex_editor/routes.py
# -*- coding: utf-8 -*-

import os
from app import login_required
from flask import (render_template, current_app, flash, abort, url_for,
                   redirect, request, session, jsonify)
from datetime import datetime
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
    update_sonarr_series, get_sonarr_episode_files,
    get_all_sonarr_series # <--- AJOUT ICI
)

# --- Routes du Blueprint ---

@plex_editor_bp.route('/', methods=['GET', 'POST'])
@login_required
def index(): # (### MODIFICATION ICI ###) - Le nom de la fonction est maintenant 'index'
    """Page d'accueil du module, pour sélectionner l'utilisateur Plex."""
    users_list = []
    plex_error_message = None
    main_plex_account = get_main_plex_account_object()
    if not main_plex_account:
        return render_template('plex_editor/select_user.html', title="Sélectionner l'Utilisateur", users=users_list, plex_error=plex_error_message or "Impossible de charger les utilisateurs.")

    if request.method == 'POST':
        user_id_selected = request.form.get('user_id')
        user_title_selected = request.form.get('user_title_hidden')
        if user_id_selected and user_title_selected:
            session['plex_user_id'] = user_id_selected
            session['plex_user_title'] = user_title_selected
            current_app.logger.info(f"Utilisateur '{user_title_selected}' (ID: {user_id_selected}) sélectionné.")
            flash(f"Utilisateur '{user_title_selected}' sélectionné avec succès.", 'success')
            return redirect(url_for('plex_editor.list_libraries'))
        else:
            flash("Sélection invalide. Veuillez choisir un utilisateur.", 'warning')
            current_app.logger.warning("index: Soumission du formulaire avec données manquantes.") # (### MODIFICATION ICI ###) - Log mis à jour

    try:
        main_title = main_plex_account.title or main_plex_account.username or f"Principal (ID: {main_plex_account.id})"
        users_list.append({'id': str(main_plex_account.id), 'title': main_title})
        for user in main_plex_account.users():
            managed_title = user.title or f"Géré (ID: {user.id})"
            users_list.append({'id': str(user.id), 'title': managed_title})
    except Exception as e:
        current_app.logger.error(f"index: Erreur lors de la construction de la liste des utilisateurs: {e}", exc_info=True) # (### MODIFICATION ICI ###) - Log mis à jour
        plex_error_message = "Erreur lors de la récupération de la liste des utilisateurs."
        flash(plex_error_message, "danger")

    return render_template('plex_editor/select_user.html',
                           title="Sélectionner l'Utilisateur Plex",
                           users=users_list,
                           plex_error=plex_error_message)

@plex_editor_bp.route('/libraries')
@login_required
def list_libraries():
    """Affiche la liste des bibliothèques Plex disponibles."""
    if 'plex_user_id' not in session:
        flash("Veuillez d'abord sélectionner un utilisateur Plex.", "info")
        return redirect(url_for('plex_editor.index')) # (### MODIFICATION ICI ###) - Pointeur vers la nouvelle fonction 'index'

    user_title = session.get('plex_user_title', 'Utilisateur Inconnu')
    plex_server = get_plex_admin_server()
    libraries = []
    plex_error_message = None

    if plex_server:
        try:
            libraries = plex_server.library.sections()
            flash(f'Connecté au serveur Plex: {plex_server.friendlyName} (Utilisateur actuel: {user_title})', 'success')
        except Exception as e:
            plex_error_message = str(e)
            current_app.logger.error(f"list_libraries: Erreur de récupération des bibliothèques: {e}", exc_info=True)
            flash(f"Erreur de récupération des bibliothèques : {e}", 'danger')
    else:
        plex_error_message = "Impossible de se connecter au serveur Plex."

    return render_template('plex_editor/index.html',
                           title=f'Bibliothèques - {user_title}',
                           libraries=libraries,
                           plex_error=plex_error_message,
                           user_title=user_title)
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

    if not rating_key:
        return jsonify({'status': 'error', 'message': 'Missing ratingKey.'}), 400

    user_plex_server = get_user_specific_plex_server()
    if not user_plex_server:
        return jsonify({'status': 'error', 'message': 'Could not get user-specific Plex connection.'}), 500

    try:
        show = user_plex_server.fetchItem(int(rating_key))
        if not show or show.type != 'show':
            return jsonify({'status': 'error', 'message': 'Show not found or not a show item.'}), 404

        if show.viewedLeafCount != show.leafCount:
            error_msg = f"Not all episodes are marked as watched in Plex (Viewed: {show.viewedLeafCount}, Total: {show.leafCount})."
            return jsonify({'status': 'error', 'message': error_msg}), 400

        sonarr_series = None
        for guid_obj in show.guids:
            sonarr_series = get_sonarr_series_by_guid(guid_obj.id)
            if sonarr_series: break

        if not sonarr_series:
            return jsonify({'status': 'error', 'message': 'Show not found in Sonarr.'}), 404

        if sonarr_series.get('status', 'continuing') != 'ended':
            return jsonify({'status': 'error', 'message': f"Cannot archive. Show '{show.title}' is not 'ended' in Sonarr."}), 400

        if options.get('unmonitor') or options.get('addTag'):
            series_id = sonarr_series['id']
            full_series_data = get_sonarr_series_by_id(series_id)
            if not full_series_data:
                return jsonify({'status': 'error', 'message': 'Could not fetch full series details from Sonarr.'}), 500

            if options.get('unmonitor'):
                full_series_data['monitored'] = False
            if options.get('addTag'):
                vu_tag_id = get_sonarr_tag_id('vu')
                vu_complet_tag_id = get_sonarr_tag_id('vu-complet')
                if vu_tag_id and vu_tag_id not in full_series_data.get('tags', []):
                    full_series_data['tags'].append(vu_tag_id)
                if vu_complet_tag_id and vu_complet_tag_id not in full_series_data.get('tags', []):
                    full_series_data['tags'].append(vu_complet_tag_id)

            if not update_sonarr_series(full_series_data):
                return jsonify({'status': 'error', 'message': 'Failed to update series in Sonarr.'}), 500

        if options.get('deleteFiles'):
            episode_files = get_sonarr_episode_files(sonarr_series['id'])
            if episode_files is None:
                return jsonify({'status': 'error', 'message': 'Could not retrieve episode file list.'}), 500

            last_deleted_filepath = None
            for file_info in episode_files:
                media_filepath = file_info.get('path')
                if media_filepath and os.path.exists(media_filepath):
                    try:
                        if not _is_dry_run_mode(): os.remove(media_filepath)
                        last_deleted_filepath = media_filepath
                        current_app.logger.info(f"ARCHIVE SHOW: {'[SIMULATION] ' if _is_dry_run_mode() else ''}Deleting file: {media_filepath}")
                    except Exception as e_file:
                        current_app.logger.error(f"Failed to delete file {media_filepath}: {e_file}")

            if last_deleted_filepath:
                admin_plex_server = get_plex_admin_server()
                if admin_plex_server:
                    library_sections = admin_plex_server.library.sections()
                    temp_roots = {os.path.normpath(loc) for lib in library_sections for loc in lib.locations}
                    temp_guards = {os.path.normpath(os.path.splitdrive(r)[0] + os.sep) if os.path.splitdrive(r)[0] else os.path.normpath(os.sep + r.split(os.sep)[1]) for r in temp_roots if r}
                    cleanup_parent_directory_recursively(last_deleted_filepath, list(temp_roots), list(temp_guards))

        try:
            admin_plex_server = get_plex_admin_server()
            if admin_plex_server:
                show_library = admin_plex_server.library.section(show.librarySectionTitle)
                if not _is_dry_run_mode(): show_library.update()
                flash(f"Scan de la bibliothèque '{show_library.title}' déclenché.", "info")
        except Exception as e_scan:
            current_app.logger.error(f"Échec du déclenchement du scan Plex: {e_scan}")

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
# --- ROUTE API POUR RÉCUPÉRER LES DÉTAILS D'UN ITEM (VERSION FINALE) ---
@plex_editor_bp.route('/details/<int:rating_key>')
@login_required
def get_item_details(rating_key):
    # On récupère les deux contextes
    admin_plex_server = get_plex_admin_server()
    user_plex_server = get_user_specific_plex_server()
    if not admin_plex_server or not user_plex_server:
        return jsonify({'status': 'error', 'message': 'Plex server connection failed.'}), 500

    try:
        # On récupère l'objet dans le contexte ADMIN pour les métadonnées générales
        item_admin = admin_plex_server.fetchItem(rating_key)
        # On récupère le même objet dans le contexte UTILISATEUR pour les données personnelles
        item_user = user_plex_server.fetchItem(rating_key)

        if not item_admin:
            abort(404)

        # On construit le dictionnaire de base avec les infos de l'objet ADMIN
        details = {
            'type': item_admin.type,
            'title': item_admin.title,
            'year': item_admin.year,
            'summary': item_admin.summary,
            'rating': item_admin.rating,
            'poster_url': admin_plex_server.url(item_admin.thumb, includeToken=True) if item_admin.thumb else None,
            'genres': [genre.tag for genre in item_admin.genres[:4]],
            'actors': [actor.tag for actor in item_admin.actors[:8]],
            # On utilise les données de l'objet UTILISATEUR pour les infos personnelles
            'user_rating': item_user.userRating,
        }

        if item_admin.type == 'movie':
            details['duration_min'] = round(item_admin.duration / 60000) if item_admin.duration else None
            details['directors'] = [director.tag for director in item_admin.directors]

        elif item_admin.type == 'show':
            details['duration_min'] = round(item_admin.duration / 60000) if item_admin.duration else None
            details['directors'] = []
            details['added_at'] = item_admin.addedAt.strftime('%d/%m/%Y') if item_admin.addedAt else 'N/A'
            details['originally_available_at'] = item_admin.originallyAvailableAt.strftime('%Y-%m-%d') if item_admin.originallyAvailableAt else 'N/A'
            # On utilise les données de l'objet UTILISATEUR pour les comptes d'épisodes
            details['leaf_count'] = item_user.leafCount
            details['viewed_leaf_count'] = item_user.viewedLeafCount

            # Le reste (infos Sonarr) peut continuer d'utiliser les guids de l'objet admin
            sonarr_series = next((s for g in item_admin.guids if 'tvdb' in g.id and (s := get_sonarr_series_by_guid(g.id))), None)
            if sonarr_series:
                details['sonarr_status'] = sonarr_series.get('status', 'N/A').capitalize()
                stats = sonarr_series.get('statistics', {})
                details['sonarr_season_count'] = stats.get('seasonCount', 0)
            else:
                details['sonarr_status'] = 'Non trouvé dans Sonarr'
                details['sonarr_season_count'] = item_admin.childCount

        return jsonify({'status': 'success', 'details': details})

    except NotFound:
        return jsonify({'status': 'error', 'message': 'Item not found in Plex.'}), 404
    except Exception as e:
        current_app.logger.error(f"Erreur dans get_item_details pour ratingKey {rating_key}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An internal error occurred.'}), 500
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