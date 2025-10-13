# app/plex_editor/routes.py
# -*- coding: utf-8 -*-

import os
from flask import (render_template, current_app, flash, abort, url_for,
                   redirect, request, session)
from datetime import datetime

# Importer le Blueprint
from . import plex_editor_bp # '.' signifie depuis le package actuel

# Importer les utils spécifiques à plex_editor
# Si utils.py est dans le même dossier plex_editor:
from .utils import cleanup_parent_directory_recursively, get_media_filepath
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound, Unauthorized, BadRequest

# --- Fonction Utilitaire get_main_plex_account_object() ---
# (Votre code - Inchangé)
def get_main_plex_account_object():
    plex_url = current_app.config.get('PLEX_URL')
    plex_token = current_app.config.get('PLEX_TOKEN')
    if not plex_url or not plex_token:
        current_app.logger.error("get_main_plex_account_object: Configuration Plex (URL/Token) manquante.")
        flash("Configuration Plex (URL/Token) du serveur principal manquante.", "danger")
        return None
    try:
        plex_admin_server = PlexServer(plex_url, plex_token)
        main_account = plex_admin_server.myPlexAccount()
        return main_account
    except Unauthorized:
        current_app.logger.error("get_main_plex_account_object: Token Plex principal invalide ou expiré.")
        flash("Token Plex principal invalide ou expiré. Impossible d'accéder aux informations du compte.", "danger")
        session.clear()
        return None
    except Exception as e:
        current_app.logger.error(f"get_main_plex_account_object: Erreur inattendue: {e}", exc_info=True)
        flash("Erreur inattendue lors de la récupération des informations du compte Plex principal.", "danger")
        return None

# --- Route select_user ---
# (Votre code - Inchangé)
@plex_editor_bp.route('/', methods=['GET', 'POST'])
def index():
    users_list = []
    plex_error_message = None
    main_plex_account = get_main_plex_account_object()
    if not main_plex_account:
        # Note: 'plex_editor/select_user.html' est toujours le bon template à rendre ici
        return render_template('plex_editor/select_user.html', title="Sélectionner l'Utilisateur", users=users_list, plex_error=plex_error_message or "Impossible de charger les utilisateurs.")

    if request.method == 'POST':
        user_id_selected = request.form.get('user_id')
        user_title_selected = request.form.get('user_title_hidden')
        if user_id_selected and user_title_selected:
            session['plex_user_id'] = user_id_selected
            session['plex_user_title'] = user_title_selected
            current_app.logger.info(f"Utilisateur '{user_title_selected}' (ID: {user_id_selected}) sélectionné.")
            flash(f"Utilisateur '{user_title_selected}' sélectionné avec succès.", 'success')
            # Redirection vers la liste des bibliothèques après sélection
            return redirect(url_for('plex_editor.list_libraries'))
        else:
            flash("Sélection invalide. Veuillez choisir un utilisateur.", 'warning')
            current_app.logger.warning("index (select_user): Soumission du formulaire avec données manquantes.")
    
    # Bloc try/except pour le GET request (lister les utilisateurs)
    try:
        main_title = main_plex_account.title or main_plex_account.username or f"Principal (ID: {main_plex_account.id})"
        users_list.append({'id': str(main_plex_account.id), 'title': main_title})
        for user in main_plex_account.users():
            managed_title = user.title or f"Géré (ID: {user.id})"
            users_list.append({'id': str(user.id), 'title': managed_title})
        current_app.logger.debug(f"index (select_user): Liste des utilisateurs pour sélection: {len(users_list)}.")
    except Exception as e:
        current_app.logger.error(f"index (select_user): Erreur lors de la construction de la liste des utilisateurs: {e}", exc_info=True)
        plex_error_message = "Erreur lors de la récupération de la liste des utilisateurs."
        flash(plex_error_message, "danger")

    return render_template('plex_editor/select_user.html',
                           title="Sélectionner l'Utilisateur Plex",
                           users=users_list,
                           plex_error=plex_error_message)

# --- Route index ---
# (Votre code - Inchangé)
@plex_editor_bp.route('/')
@plex_editor_bp.route('/index')
def index():
    if 'plex_user_id' not in session:
        flash("Veuillez d'abord sélectionner un utilisateur Plex.", "info")
        return redirect(url_for('plex_editor.select_user'))
    user_title = session.get('plex_user_title', 'Utilisateur Inconnu')
    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')
    libraries = []
    plex_error_message = None
    if not plex_url or not admin_token:
        flash('Erreur: Configuration Plex du serveur principal (URL/Token) manquante.', 'danger')
        plex_error_message = "Configuration Plex manquante"
    else:
        try:
            plex_server_admin_conn = PlexServer(plex_url, admin_token)
            libraries = plex_server_admin_conn.library.sections()
            current_app.logger.debug(f"index: Récupération de {len(libraries)} bibliothèques pour l'utilisateur '{user_title}'.")
            flash(f'Connecté au serveur Plex: {plex_server_admin_conn.friendlyName} (Utilisateur actuel: {user_title})', 'success')
        except Unauthorized:
            flash('Erreur: Token Plex principal invalide ou expiré. Veuillez vérifier la configuration.', 'danger')
            plex_error_message = "Token principal invalide"
            current_app.logger.error("index: Token Plex principal invalide. Redirection vers select_user.")
            session.clear()
            return redirect(url_for('plex_editor.select_user'))
        except Exception as e:
            current_app.logger.error(f"index: Erreur de connexion à Plex ({plex_url}): {e}", exc_info=True)
            flash(f"Erreur de connexion au serveur Plex. Vérifiez l'URL et la disponibilité.", 'danger')
            plex_error_message = str(e)
    return render_template('plex_editor/index.html',
                           title=f'Accueil - {user_title}',
                           libraries=libraries,
                           plex_error=plex_error_message,
                           user_title=user_title)

# --- Route show_library ---
# (Votre code avec l'initialisation de final_context_user_title et la logique des filtres - Inchangé)
@plex_editor_bp.route('/library/<path:library_name>')
def show_library(library_name):
    if 'plex_user_id' not in session:
        flash("Veuillez sélectionner un utilisateur.", "info")
        return redirect(url_for('plex_editor.select_user'))

    user_id_in_session = session.get('plex_user_id')
    user_title_in_session = session.get('plex_user_title', 'Utilisateur Inconnu')
    final_context_user_title = user_title_in_session

    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')

    items_from_plex_api = None
    library_object = None
    plex_error_message = None

    current_filters_from_url = {
        'vu': request.args.get('vu', 'tous'),
        'note_filter_type': request.args.get('note_filter_type', 'toutes'),
        'note_filter_value': request.args.get('note_filter_value', type=float),
        'date_filter_type': request.args.get('date_filter_type', 'aucun'),
        'date_filter_value': request.args.get('date_filter_value', '')
    }
    current_app.logger.debug(f"show_library: Filtres URL initiaux: {current_filters_from_url}")

    search_args = {}
    filter_for_non_notes_in_python = False

    if current_filters_from_url['vu'] == 'vu': search_args['unwatched'] = False
    elif current_filters_from_url['vu'] == 'nonvu': search_args['unwatched'] = True

    note_type = current_filters_from_url['note_filter_type']
    note_value_from_form = current_filters_from_url['note_filter_value']
    if note_type == 'non_notes':
        filter_for_non_notes_in_python = True
        current_app.logger.info("Filtre de note: 'Non Notés Uniquement' activé (post-filtrage Python).")
    elif note_type in ['note_exacte', 'note_min', 'note_max']:
        if note_value_from_form is not None:
            if note_type == 'note_exacte': search_args['userRating'] = note_value_from_form
            elif note_type == 'note_min': search_args['userRating>>='] = note_value_from_form
            elif note_type == 'note_max': search_args['userRating<<='] = note_value_from_form
            current_app.logger.info(f"Filtre de note API: {note_type} = {note_value_from_form}")
        else:
            flash(f"Veuillez fournir une valeur de note pour le filtre '{note_type}'. Filtre ignoré.", "warning")
            current_filters_from_url['note_filter_type'] = 'toutes'

    date_type_from_form = current_filters_from_url.get('date_filter_type', 'aucun')
    date_value_str_from_form = current_filters_from_url.get('date_filter_value', '')
    current_app.logger.debug(f"Traitement filtre date flexible: type='{date_type_from_form}', value='{date_value_str_from_form}'")
    try:
        if date_type_from_form == 'ajout_recent_jours':
            if date_value_str_from_form.isdigit() and int(date_value_str_from_form) > 0:
                search_args['addedAt>>='] = f"{int(date_value_str_from_form)}d"
                current_app.logger.info(f"Filtre date API: ajout_recent_jours = {search_args['addedAt>>=']}")
            elif date_value_str_from_form: raise ValueError("Nombre de jours invalide")
        elif date_type_from_form == 'ajout_avant_date':
            if date_value_str_from_form:
                parsed_date = None
                for fmt in ('%Y/%m/%d', '%Y-%m-%d'):
                    try: parsed_date = datetime.strptime(date_value_str_from_form, fmt); break
                    except ValueError: continue
                if parsed_date: search_args['addedAt<<'] = parsed_date.strftime('%Y-%m-%d')
                else: raise ValueError("Format de date non reconnu (YYYY/MM/DD ou YYYY-MM-DD)")
                current_app.logger.info(f"Filtre date API: ajout_avant_date (addedAt<<) = {search_args['addedAt<<']}")
        elif date_type_from_form == 'ajout_apres_date':
            if date_value_str_from_form:
                parsed_date = None
                for fmt in ('%Y/%m/%d', '%Y-%m-%d'):
                    try: parsed_date = datetime.strptime(date_value_str_from_form, fmt); break
                    except ValueError: continue
                if parsed_date: search_args['addedAt>>='] = parsed_date.strftime('%Y-%m-%d')
                else: raise ValueError("Format de date non reconnu")
                current_app.logger.info(f"Filtre date API: ajout_apres_date (addedAt>>=) = {search_args['addedAt>>=']}")
        elif date_type_from_form == 'sortie_annee':
            if date_value_str_from_form.isdigit() and len(date_value_str_from_form) == 4:
                 search_args['year'] = int(date_value_str_from_form)
                 current_app.logger.info(f"Filtre date API: sortie_annee (year) = {search_args['year']}")
            elif date_value_str_from_form: raise ValueError("Année invalide (YYYY)")
        elif date_type_from_form == 'sortie_avant_annee':
            if date_value_str_from_form.isdigit() and len(date_value_str_from_form) == 4:
                search_args['year<<'] = int(date_value_str_from_form)
                current_app.logger.info(f"Filtre date API: sortie_avant_annee (year<<) = {search_args['year<<']}")
            elif date_value_str_from_form: raise ValueError("Année invalide")
        elif date_type_from_form == 'sortie_apres_annee':
            if date_value_str_from_form.isdigit() and len(date_value_str_from_form) == 4:
                search_args['year>>='] = int(date_value_str_from_form)
                current_app.logger.info(f"Filtre date API: sortie_apres_annee (year>>=) = {search_args['year>>=']}")
            elif date_value_str_from_form: raise ValueError("Année invalide")
    except ValueError as e_date_flex:
         flash(f"Valeur invalide ('{date_value_str_from_form}') pour le filtre de date '{date_type_from_form}': {e_date_flex}. Filtre ignoré.", "warning")
         current_filters_from_url['date_filter_type'] = 'aucun'
         current_filters_from_url['date_filter_value'] = ''
         current_app.logger.warning(f"Erreur de valeur pour filtre date flexible: {e_date_flex}")

    sort_order = request.args.get('sort', 'addedAt:desc')
    search_args['sort'] = sort_order
    current_app.logger.info(f"show_library: Arguments finaux pour API search(): {search_args}")

    if not plex_url or not admin_token:
        flash('Erreur: Configuration Plex du serveur principal (URL/Token) manquante.', 'danger')
        plex_error_message = "Configuration Plex manquante"
    else:
        try:
            plex_server_admin_conn = PlexServer(plex_url, admin_token)
            user_specific_plex_server = None
            main_plex_account_obj = get_main_plex_account_object()
            if not main_plex_account_obj:
                 current_app.logger.error("show_library: Impossible de récupérer l'objet compte principal.")
                 plex_error_message = plex_error_message or "Erreur compte principal Plex."
            else:
                main_account_id_str = str(main_plex_account_obj.id)
                if user_id_in_session and user_id_in_session != main_account_id_str:
                    user_to_impersonate_obj = next((u for u in main_plex_account_obj.users() if str(u.id) == user_id_in_session), None)
                    if user_to_impersonate_obj:
                        try:
                            managed_user_token = user_to_impersonate_obj.get_token(plex_server_admin_conn.machineIdentifier)
                            user_specific_plex_server = PlexServer(plex_url, managed_user_token)
                            final_context_user_title = user_to_impersonate_obj.title
                            current_app.logger.info(f"Emprunt d'identité réussi pour '{final_context_user_title}'.")
                        except Exception as e_impersonate:
                            current_app.logger.error(f"Échec emprunt d'identité pour '{user_title_in_session}': {e_impersonate}", exc_info=True)
                            flash(f"Avertissement: Emprunt d'identité pour '{user_title_in_session}' échoué. Tentative de switchUser.", "warning")
                            user_specific_plex_server = plex_server_admin_conn
                            try:
                                user_specific_plex_server.switchUser(user_to_impersonate_obj.title)
                                final_context_user_title = user_to_impersonate_obj.title
                                current_app.logger.info(f"Fallback sur switchUser pour '{final_context_user_title}' réussi.")
                            except Exception as e_switch:
                                current_app.logger.error(f"Échec du fallback switchUser pour '{user_title_in_session}': {e_switch}. Utilisation contexte admin.", exc_info=True)
                                final_context_user_title = main_plex_account_obj.title
                                flash(f"Basculement vers '{user_title_in_session}' échoué. Contexte admin utilisé.", "danger")
                    else:
                        current_app.logger.warning(f"Utilisateur géré ID {user_id_in_session} ('{user_title_in_session}') non trouvé. Contexte admin utilisé.")
                        flash(f"Utilisateur '{user_title_in_session}' non trouvé. Contexte admin utilisé.", "warning")
                        user_specific_plex_server = plex_server_admin_conn
                        final_context_user_title = main_plex_account_obj.title
                else:
                    current_app.logger.info(f"Recherche dans le contexte du compte principal '{final_context_user_title}'.")
                    user_specific_plex_server = plex_server_admin_conn

                if user_specific_plex_server:
                    try:
                        library_object = user_specific_plex_server.library.section(library_name)
                        current_app.logger.info(f"Exécution de library.search sur '{library_object.title}' pour utilisateur '{final_context_user_title}' avec args: {search_args}")
                        items_from_plex_api = library_object.search(**search_args)
                    except NotFound:
                        plex_error_message = f"Bibliothèque '{library_name}' non trouvée."
                        current_app.logger.warning(f"show_library: {plex_error_message}")
                        items_from_plex_api = []
                        library_object = None
                    except BadRequest as e_br:
                        plex_error_message = f"Filtre invalide: {e_br}"
                        current_app.logger.error(f"show_library: BadRequest lors de la recherche: {e_br}", exc_info=True)
                        flash(f"Erreur dans les filtres: {e_br}", "danger")
                        items_from_plex_api = []
                    except Exception as e_s:
                        plex_error_message = f"Erreur de recherche: {e_s}"
                        current_app.logger.error(f"show_library: Erreur pendant recherche: {e_s}", exc_info=True)
                        flash("Erreur pendant la recherche.", "danger")
                        items_from_plex_api = []
                else:
                    plex_error_message = plex_error_message or "Erreur critique: Connexion Plex non préparée."
                    current_app.logger.critical("show_library: user_specific_plex_server est None avant recherche.")
                    items_from_plex_api = []

        except Unauthorized:
            plex_error_message = "Token Plex principal invalide."
            current_app.logger.error("show_library: Unauthorized (token admin). Redirection.", exc_info=True)
            flash(plex_error_message, 'danger')
            session.clear()
            return redirect(url_for('plex_editor.select_user'))
        except Exception as e_outer:
            plex_error_message = f"Erreur majeure: {e_outer}"
            current_app.logger.error(f"show_library: Erreur majeure inattendue: {e_outer}", exc_info=True)
            flash("Erreur majeure inattendue.", 'danger')
            items_from_plex_api = []

    items_filtered_final = []
    if items_from_plex_api is not None:
        if filter_for_non_notes_in_python:
            items_filtered_final = [item for item in items_from_plex_api if item.userRating is None]
            current_app.logger.info(f"Filtrage Python 'Non Notés': {len(items_filtered_final)}/{len(items_from_plex_api)} éléments.")
        else:
            items_filtered_final = items_from_plex_api

        if library_object:
            applied_filters_str_parts = []
            if 'unwatched' in search_args: applied_filters_str_parts.append(f"Vu/Non Vu: {'Non Vus' if search_args['unwatched'] else 'Vus'}")
            else: applied_filters_str_parts.append("Vu/Non Vu: Tous")
            if filter_for_non_notes_in_python: applied_filters_str_parts.append("Note: Non Notés Uniquement")
            elif 'userRating' in search_args : applied_filters_str_parts.append(f"Note = {search_args['userRating']}")
            elif 'userRating>>=' in search_args: applied_filters_str_parts.append(f"Note ≥ {search_args['userRating>>=']}")
            elif 'userRating<<=' in search_args: applied_filters_str_parts.append(f"Note ≤ {search_args['userRating<<=']}")
            else: applied_filters_str_parts.append("Note: Toutes")
            if 'addedAt<<' in search_args: applied_filters_str_parts.append(f"Ajouté avant {search_args['addedAt<<']}")
            if 'addedAt>>=' in search_args: applied_filters_str_parts.append(f"Ajouté depuis/après {search_args['addedAt>>=']}")
            if 'year' in search_args: applied_filters_str_parts.append(f"Sorti en {search_args['year']}")
            applied_filters_str = ", ".join(applied_filters_str_parts)
            flash_message = f"Affichage de {len(items_filtered_final)} éléments de '{library_object.title}' pour '{final_context_user_title}'. Filtres: {applied_filters_str}."
            if filter_for_non_notes_in_python and items_from_plex_api and len(items_from_plex_api) != len(items_filtered_final) :
                flash_message += f" ({len(items_from_plex_api)} avant filtre 'Non Notés')."
            flash(flash_message, 'info')
    elif not plex_error_message and library_object:
        flash(f"Aucun élément trouvé dans '{library_object.title}' pour '{final_context_user_title}' avec les filtres.", "info")
    elif plex_error_message and not library_object :
        if library_name and "Bibliothèque" not in plex_error_message : # CORRECTION: vérifier library_name
            flash(f"Erreur lors de l'accès à la bibliothèque '{library_name}'.", "danger")
        # elif not library_name and "Bibliothèque" not in plex_error_message: # Cette condition est moins utile ici
        #      flash(f"Erreur lors de l'accès à une bibliothèque non spécifiée.", "danger")


    return render_template('plex_editor/library.html',
                           title=f"Bibliothèque {library_name or 'Inconnue'} - {user_title_in_session}",
                           library_name=library_name,
                           library_obj=library_object,
                           items=items_filtered_final,
                           current_filters=current_filters_from_url,
                           plex_error=plex_error_message,
                           user_title=user_title_in_session)

@plex_editor_bp.route('/delete_item/<int:rating_key>', methods=['POST'])
def delete_item(rating_key):
    # --- Début des logs de débogage initiaux ---
    print(f"--- PRINT: FONCTION delete_item APPELÉE pour rating_key: {rating_key} ---")
    print(f"--- PRINT: Contenu du formulaire delete_item: {request.form}")
    current_app.logger.info(f"--- LOG: FONCTION delete_item APPELÉE pour rating_key: {rating_key} ---")
    current_app.logger.debug(f"LOG: Contenu du formulaire delete_item: {request.form}")
    # --- Fin des logs de débogage initiaux ---

    if 'plex_user_id' not in session:
        flash("Session expirée. Veuillez vous reconnecter.", "danger")
        return redirect(url_for('plex_editor.select_user'))

    current_library_name = request.form.get('current_library_name')
    redirect_url = request.referrer or url_for('show_library', library_name=current_library_name or 'index')

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
                                                                 base_paths_guards=deduced_base_paths_guards) # <<< CORRECTION ICI
            else:
                current_app.logger.info(f"DELETE_ITEM: Aucun chemin de fichier pour {item_title_for_flash} (ratingKey: {rating_key}), nettoyage de répertoire ignoré.")
        else:
            flash(f"Item (ratingKey {rating_key}) non trouvé. Suppression annulée.", "warning")
            current_app.logger.warning(f"Item non trouvé avec ratingKey: {rating_key} dans delete_item.")

    except NotFound: # ... (reste de votre gestion d'erreur)
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

# --- Route pour la suppression groupée d'éléments ---
@plex_editor_bp.route('/bulk_delete_items', methods=['POST'])
def bulk_delete_items():
    # --- Début des logs de débogage initiaux ---
    print("--- PRINT: FONCTION bulk_delete_items APPELÉE ---")
    print(f"--- PRINT: Contenu du formulaire bulk_delete_items: {request.form}")
    current_app.logger.info("--- LOG: FONCTION bulk_delete_items APPELÉE ---")
    current_app.logger.debug(f"LOG: Contenu du formulaire bulk_delete_items: {request.form}")
    # --- Fin des logs de débogage initiaux ---

    if 'plex_user_id' not in session: # ... (reste de votre logique de session, récupération des clés, etc.)
        flash("Session expirée. Veuillez vous reconnecter.", "danger")
        return redirect(url_for('plex_editor.select_user'))

    selected_keys_str_list = request.form.getlist('selected_item_keys')
    current_library_name = request.form.get('current_library_name')
    redirect_url = request.referrer or url_for('show_library', library_name=current_library_name or 'index')

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
                        current_app.logger.info(f"BULK_DELETE: Lancement du nettoyage pour: {media_filepath_to_cleanup_bulk} (Racines Plex: {active_plex_library_roots}, Gardes-fous: {deduced_base_paths_guards})") # Log amélioré
                        cleanup_parent_directory_recursively(media_filepath_to_cleanup_bulk,
                                                             dynamic_plex_library_roots=active_plex_library_roots,
                                                             base_paths_guards=deduced_base_paths_guards) # <<< CORRECTION ICI
                    else:
                         current_app.logger.info(f"BULK_DELETE: Pas de chemin pour {item_title_for_log} (groupe), nettoyage dossier ignoré.")

                # Si fetchItem ne trouve rien, il lève NotFound, donc pas de 'else' ici après 'if item_to_delete:'

            except NotFound: # Bloc except pour NotFound
                fail_count += 1
                failed_items_info.append(f"ratingKey {r_key} (non trouvé/déjà supprimé)")
                current_app.logger.warning(f"Item non trouvé (NotFound) lors de suppression groupée: {r_key}")
            except Exception as e_item_del: # Bloc except pour autres erreurs sur cet item
                fail_count += 1
                title_err = item_title_for_log # Utiliser le titre qu'on avait, ou le ratingKey
                # Si l'erreur s'est produite avant d'avoir le titre (ex: dans fetchItem mais pas NotFound)
                if title_err == f"ratingKey {r_key}":
                    try: # Tentative de récupérer le titre pour un log plus clair
                        item_obj_for_error_log = plex_server.fetchItem(r_key) # Attention, peut re-lever NotFound
                        if item_obj_for_error_log: title_err = item_obj_for_error_log.title
                    except: # Ignorer si on ne peut pas récupérer le titre ici
                        pass
                failed_items_info.append(f"'{title_err}' (erreur: {type(e_item_del).__name__})")
                current_app.logger.error(f"Échec suppression (groupe) pour '{title_err}': {e_item_del}", exc_info=True)

        # Messages Flash après la boucle
        if success_count > 0:
            flash(f"{success_count} élément(s) supprimé(s) de Plex.", "success")
        if fail_count > 0:
            summary = ", ".join(failed_items_info[:3]) # Afficher les 3 premiers échecs
            if len(failed_items_info) > 3:
                summary += f", et {len(failed_items_info) - 3} autre(s)..."
            flash(f"Échec de suppression pour {fail_count} élément(s). Détails: {summary}.", "danger")

    except Unauthorized: # Ce except est pour le try externe qui englobe la connexion plex_server et la boucle
        flash("Autorisation refusée (token admin). Suppression groupée échouée.", "danger")
        current_app.logger.error("Unauthorized pour suppression groupée.")
    except Exception as e_bulk: # Ce except est pour le try externe
        flash(f"Erreur majeure suppression groupée: {e_bulk}", "danger")
        current_app.logger.error(f"Erreur majeure suppression groupée: {e_bulk}", exc_info=True)

    return redirect(redirect_url)
from app.utils.arr_client import get_radarr_tag_id, get_radarr_movie_by_guid, update_radarr_movie
from .utils import cleanup_deleted_item_files # Assurez-vous que cette importation existe déjà

@plex_editor_bp.route('/archive_movie', methods=['POST'])
def archive_movie_route():
    data = request.get_json()
    rating_key = data.get('ratingKey')
    options = data.get('options', {})

    if not rating_key:
        return jsonify({'status': 'error', 'message': 'Missing ratingKey.'}), 400

    try:
        plex = get_plex_instance()
        movie = plex.fetchItem(int(rating_key))

        if not movie or movie.type != 'movie':
            return jsonify({'status': 'error', 'message': 'Movie not found or not a movie item.'}), 404

        if not movie.isWatched:
            return jsonify({'status': 'error', 'message': 'Movie is not marked as watched in Plex.'}), 400

        # --- Radarr Actions ---
        if options.get('unmonitor') or options.get('addTag'):
            # Find movie in Radarr
            radarr_movie = None
            for guid_obj in movie.guids:
                radarr_movie = get_radarr_movie_by_guid(guid_obj.id)
                if radarr_movie:
                    break

            if not radarr_movie:
                return jsonify({'status': 'error', 'message': 'Movie not found in Radarr.'}), 404

            # Prepare update payload
            if options.get('unmonitor'):
                radarr_movie['monitored'] = False
                current_app.logger.info(f"Setting '{movie.title}' to unmonitored in Radarr.")

            if options.get('addTag'):
                tag_label = current_app.config['RADARR_TAG_ON_ARCHIVE']
                tag_id = get_radarr_tag_id(tag_label)
                if tag_id:
                    if tag_id not in radarr_movie['tags']:
                        radarr_movie['tags'].append(tag_id)
                        current_app.logger.info(f"Adding tag '{tag_label}' to '{movie.title}' in Radarr.")
                else:
                    return jsonify({'status': 'error', 'message': f"Could not find or create tag '{tag_label}' in Radarr."}), 500

            # Send update to Radarr
            update_result = update_radarr_movie(radarr_movie)
            if not update_result:
                return jsonify({'status': 'error', 'message': 'Failed to update movie in Radarr.'}), 500

        # --- File Deletion Action ---
        if options.get('deleteFiles'):
            current_app.logger.info(f"Starting file cleanup for movie: {movie.title}")
            # NOTE: Assurez-vous que la fonction cleanup_deleted_item_files est adaptée
            # pour prendre un objet `movie` et un mode `real`.
            # Le 'dry_run=False' est crucial ici.
            cleanup_results = cleanup_deleted_item_files([movie], dry_run=False)
            current_app.logger.info(f"Cleanup results for {movie.title}: {cleanup_results}")


        return jsonify({'status': 'success', 'message': f"'{movie.title}' successfully archived."})

    except Exception as e:
        current_app.logger.error(f"Error archiving movie: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

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
#    return render_template('plex_editor/500.html', error=e, user_title=user_title), 500# app/plex_editor/routes.py
# -*- coding: utf-8 -*-

import os
from flask import (render_template, current_app, flash, abort, url_for,
                   redirect, request, session, jsonify)
from datetime import datetime

# Importer le Blueprint
from . import plex_editor_bp # '.' signifie depuis le package actuel

# Importer les utils spécifiques à plex_editor
from .utils import cleanup_parent_directory_recursively, get_media_filepath
from plexapi.server import PlexServer
from plexapi.exceptions import NotFound, Unauthorized, BadRequest

# NOUVEAU: Importer le client API pour Radarr
from app.utils.arr_client import get_radarr_tag_id, get_radarr_movie_by_guid, update_radarr_movie

# --- Fonctions Utilitaires (Plex & Fichiers) ---

def get_plex_instance():
    """Récupère l'instance Plex pour l'utilisateur sélectionné en session."""
    user_id = session.get('plex_user_id')
    plex_url = current_app.config.get('PLEX_URL')
    plex_token = current_app.config.get('PLEX_TOKEN')

    if not all([user_id, plex_url, plex_token]):
        current_app.logger.warning("get_plex_instance: Données de session ou de config manquantes.")
        abort(401) # Non autorisé si les infos ne sont pas complètes

    try:
        if str(user_id) == str(current_app.config.get('PLEX_MAIN_ACCOUNT_ID')):
            return PlexServer(plex_url, plex_token)
        else:
            main_account = PlexServer(plex_url, plex_token).myPlexAccount()
            user_account = main_account.user(userID=user_id)
            return PlexServer(plex_url, user_account.get_token(PlexServer(plex_url, plex_token).machineIdentifier))
    except Exception as e:
        current_app.logger.error(f"get_plex_instance: Impossible de se connecter à Plex pour user {user_id}: {e}")
        flash(f"Impossible de se connecter à Plex pour l'utilisateur sélectionné. Veuillez réessayer.", "danger")
        abort(500)

def get_main_plex_account_object():
    plex_url = current_app.config.get('PLEX_URL')
    plex_token = current_app.config.get('PLEX_TOKEN')
    if not plex_url or not plex_token:
        current_app.logger.error("get_main_plex_account_object: Configuration Plex (URL/Token) manquante.")
        flash("Configuration Plex (URL/Token) du serveur principal manquante.", "danger")
        return None
    try:
        plex_admin_server = PlexServer(plex_url, plex_token)
        main_account = plex_admin_server.myPlexAccount()
        # On stocke l'ID du compte principal pour une réutilisation future
        current_app.config['PLEX_MAIN_ACCOUNT_ID'] = main_account.id
        return main_account
    except Unauthorized:
        current_app.logger.error("get_main_plex_account_object: Token Plex principal invalide ou expiré.")
        flash("Token Plex principal invalide ou expiré.", "danger")
        session.clear()
        return None
    except Exception as e:
        current_app.logger.error(f"get_main_plex_account_object: Erreur inattendue: {e}", exc_info=True)
        flash("Erreur inattendue lors de la récupération des informations du compte Plex principal.", "danger")
        return None

def _delete_plex_item_and_files(item_to_delete, dry_run=False):
    """
    NOUVELLE FONCTION HELPER
    Logique centralisée pour supprimer un item de Plex et ses fichiers.
    Retourne un dictionnaire avec les résultats.
    """
    results = {'title': item_to_delete.title, 'status': 'pending', 'deleted_files': [], 'cleaned_dirs': []}
    
    # 1. Obtenir les chemins des fichiers
    filepaths = get_media_filepath(item_to_delete)
    if not filepaths:
        results['status'] = 'error'
        results['message'] = "Aucun chemin de fichier trouvé pour cet item."
        current_app.logger.warning(f"Aucun chemin trouvé pour '{item_to_delete.title}'.")
        return results

    # 2. Supprimer les fichiers
    for path in filepaths:
        if os.path.exists(path):
            try:
                if not dry_run:
                    os.remove(path)
                results['deleted_files'].append(path)
                current_app.logger.info(f"{'[DRY RUN] ' if dry_run else ''}Fichier supprimé: {path}")
            except OSError as e:
                results['status'] = 'error'
                results['message'] = f"Erreur de suppression du fichier {path}: {e}"
                current_app.logger.error(f"Erreur OS lors de la suppression de {path}: {e}")
                return results # Arrêter en cas d'erreur de suppression

    # 3. Supprimer l'item de la base de données Plex
    try:
        if not dry_run:
            item_to_delete.delete()
        current_app.logger.info(f"{'[DRY RUN] ' if dry_run else ''}Item '{item_to_delete.title}' supprimé de Plex.")
    except Exception as e:
        results['status'] = 'error'
        results['message'] = f"Erreur de suppression de l'item Plex: {e}"
        current_app.logger.error(f"Erreur lors de la suppression de '{item_to_delete.title}' de Plex: {e}")
        return results

    # 4. Nettoyer les dossiers parents vides (si au moins un fichier a été supprimé)
    if filepaths:
        parent_dir = os.path.dirname(filepaths[0])
        cleanup_results = cleanup_parent_directory_recursively(parent_dir, dry_run=dry_run)
        results['cleaned_dirs'] = cleanup_results
        current_app.logger.info(f"{'[DRY RUN] ' if dry_run else ''}Nettoyage des dossiers pour '{item_to_delete.title}': {cleanup_results}")
    
    results['status'] = 'success'
    return results

# --- Routes Principales du Blueprint ---

@plex_editor_bp.route('/', methods=['GET', 'POST'])
def index():
    # ... (le code que vous aviez déjà, renommé en 'index') ...
    # ... (je le remets ici pour être complet, avec la correction de la redirection)
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
            current_app.logger.warning("index (select_user): Soumission du formulaire avec données manquantes.")
    try:
        main_title = main_plex_account.title or main_plex_account.username or f"Principal (ID: {main_plex_account.id})"
        users_list.append({'id': str(main_plex_account.id), 'title': main_title})
        for user in main_plex_account.users():
            managed_title = user.title or f"Géré (ID: {user.id})"
            users_list.append({'id': str(user.id), 'title': managed_title})
        current_app.logger.debug(f"index (select_user): Liste des utilisateurs pour sélection: {len(users_list)}.")
    except Exception as e:
        current_app.logger.error(f"index (select_user): Erreur lors de la construction de la liste des utilisateurs: {e}", exc_info=True)
        plex_error_message = "Erreur lors de la récupération de la liste des utilisateurs."
        flash(plex_error_message, "danger")

    return render_template('plex_editor/select_user.html',
                           title="Sélectionner l'Utilisateur Plex",
                           users=users_list,
                           plex_error=plex_error_message)


# AJOUTEZ ICI VOS AUTRES ROUTES: list_libraries, show_library, etc.
# Je ne les ai pas, donc je ne peux pas les inclure, mais assurez-vous qu'elles sont là.
# ...

# --- Routes de Suppression (MODIFIÉES pour utiliser le helper) ---

@plex_editor_bp.route('/delete_item/<int:rating_key>', methods=['POST'])
def delete_item(rating_key):
    library_name = request.form.get('current_library_name', 'inconnue')
    try:
        plex = get_plex_instance()
        item = plex.fetchItem(rating_key)
        
        result = _delete_plex_item_and_files(item, dry_run=False)

        if result['status'] == 'success':
            flash(f"'{item.title}' a été supprimé avec succès.", "success")
        else:
            flash(f"Erreur lors de la suppression de '{item.title}': {result.get('message', 'Erreur inconnue')}", "danger")

    except NotFound:
        flash(f"L'élément avec l'ID {rating_key} n'a pas été trouvé.", "warning")
    except Exception as e:
        flash(f"Une erreur est survenue: {e}", "danger")
        current_app.logger.error(f"Erreur dans delete_item: {e}", exc_info=True)
        
    return redirect(url_for('plex_editor.show_library', library_name=library_name))


@plex_editor_bp.route('/bulk_delete', methods=['POST'])
def bulk_delete_items():
    item_keys = request.form.getlist('selected_item_keys')
    library_name = request.form.get('current_library_name', 'inconnue')
    
    if not item_keys:
        flash("Aucun élément sélectionné pour la suppression.", "warning")
        return redirect(url_for('plex_editor.show_library', library_name=library_name))

    plex = get_plex_instance()
    success_count = 0
    error_count = 0
    
    for key in item_keys:
        try:
            item = plex.fetchItem(int(key))
            result = _delete_plex_item_and_files(item, dry_run=False)
            if result['status'] == 'success':
                success_count += 1
            else:
                error_count += 1
                flash(f"Erreur sur '{item.title}': {result.get('message', 'Erreur inconnue')}", "danger")
        except NotFound:
            error_count += 1
            flash(f"Item avec ID {key} non trouvé.", "warning")
        except Exception as e:
            error_count += 1
            flash(f"Erreur inattendue sur item ID {key}: {e}", "danger")

    flash(f"{success_count} élément(s) supprimé(s) avec succès. {error_count} erreur(s).",
          "success" if error_count == 0 else "warning")

    return redirect(url_for('plex_editor.show_library', library_name=library_name, **request.args))


# --- NOUVELLE ROUTE POUR L'ARCHIVAGE ---

@plex_editor_bp.route('/archive_movie', methods=['POST'])
def archive_movie_route():
    data = request.get_json()
    rating_key = data.get('ratingKey')
    options = data.get('options', {})

    if not rating_key:
        return jsonify({'status': 'error', 'message': 'Missing ratingKey.'}), 400

    try:
        plex = get_plex_instance()
        movie = plex.fetchItem(int(rating_key))
        
        if not movie or movie.type != 'movie':
            return jsonify({'status': 'error', 'message': 'Movie not found or not a movie item.'}), 404

        if not movie.isWatched:
            return jsonify({'status': 'error', 'message': 'Movie is not marked as watched in Plex.'}), 400

        # --- Radarr Actions ---
        if options.get('unmonitor') or options.get('addTag'):
            radarr_movie = None
            for guid_obj in movie.guids:
                radarr_movie = get_radarr_movie_by_guid(guid_obj.id)
                if radarr_movie: break
            
            if not radarr_movie:
                return jsonify({'status': 'error', 'message': 'Movie not found in Radarr.'}), 404
            
            if options.get('unmonitor'):
                radarr_movie['monitored'] = False
            
            if options.get('addTag'):
                tag_label = current_app.config['RADARR_TAG_ON_ARCHIVE']
                tag_id = get_radarr_tag_id(tag_label)
                if tag_id and tag_id not in radarr_movie.get('tags', []):
                    radarr_movie['tags'].append(tag_id)
                elif not tag_id:
                    return jsonify({'status': 'error', 'message': f"Could not find or create tag '{tag_label}' in Radarr."}), 500

            if not update_radarr_movie(radarr_movie):
                return jsonify({'status': 'error', 'message': 'Failed to update movie in Radarr.'}), 500

        # --- File Deletion Action ---
        if options.get('deleteFiles'):
            current_app.logger.info(f"Starting file cleanup for archived movie: {movie.title}")
            # On ne supprime que les fichiers, pas l'item de Plex !
            filepaths = get_media_filepath(movie)
            for path in filepaths:
                if os.path.exists(path):
                    os.remove(path)
                    current_app.logger.info(f"Deleted file for archive: {path}")
            
            # Et on nettoie les dossiers parents vides
            if filepaths:
                parent_dir = os.path.dirname(filepaths[0])
                cleanup_parent_directory_recursively(parent_dir, dry_run=False)

        return jsonify({'status': 'success', 'message': f"'{movie.title}' successfully archived."})

    except Exception as e:
        current_app.logger.error(f"Error archiving movie: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500