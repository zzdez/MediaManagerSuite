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

# Importer les utils spécifiques à plex_editor
from .utils import cleanup_parent_directory_recursively, get_media_filepath, _is_dry_run_mode
# Importer les utils globaux/partagés
from app.utils.arr_client import (
    get_radarr_tag_id, get_radarr_movie_by_guid, update_radarr_movie,
    get_sonarr_tag_id, get_sonarr_series_by_guid, get_sonarr_series_by_id,
    update_sonarr_series, get_sonarr_episode_files
)

# --- Fonctions Utilitaires ---

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

def get_plex_admin_server():
    """Helper pour obtenir une connexion admin à Plex. Retourne None en cas d'échec."""
    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')
    if not plex_url or not admin_token:
        current_app.logger.error("get_plex_admin_server: Configuration Plex admin manquante.")
        flash("Configuration Plex admin manquante.", "danger")
        return None
    try:
        return PlexServer(plex_url, admin_token)
    except Exception as e:
        current_app.logger.error(f"Erreur de connexion au serveur Plex admin: {e}", exc_info=True)
        flash("Erreur de connexion au serveur Plex admin.", "danger")
        return None
# ### NOUVELLE FONCTION HELPER POUR LE CONTEXTE UTILISATEUR ###
def get_user_specific_plex_server():
    """
    Returns a PlexServer instance connected as the user in session.
    Handles impersonation for managed users. Returns None on failure.
    """
    if 'plex_user_id' not in session:
        flash("Session utilisateur invalide. Veuillez vous reconnecter.", "danger")
        return None

    plex_url = current_app.config.get('PLEX_URL')
    admin_token = current_app.config.get('PLEX_TOKEN')

    try:
        plex_admin_server = PlexServer(plex_url, admin_token)
        main_account = get_main_plex_account_object()
        if not main_account: return None

        user_id_in_session = session.get('plex_user_id')

        if str(main_account.id) == user_id_in_session:
            current_app.logger.debug("Contexte: Utilisateur Principal (Admin).")
            return plex_admin_server

        user_to_impersonate = next((u for u in main_account.users() if str(u.id) == user_id_in_session), None)
        if user_to_impersonate:
            try:
                managed_user_token = user_to_impersonate.get_token(plex_admin_server.machineIdentifier)
                current_app.logger.debug(f"Contexte: Emprunt d'identité pour '{user_to_impersonate.title}'.")
                return PlexServer(plex_url, managed_user_token)
            except Exception as e:
                current_app.logger.error(f"Échec de l'emprunt d'identité pour {user_to_impersonate.title}: {e}")
                flash(f"Impossible d'emprunter l'identité de {user_to_impersonate.title}. Action annulée.", "danger")
                return None
        else:
            flash(f"Utilisateur de la session non trouvé. Reconnexion requise.", "warning")
            return None

    except Exception as e:
        current_app.logger.error(f"Erreur majeure lors de l'obtention de la connexion utilisateur Plex : {e}", exc_info=True)
        return None
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
@plex_editor_bp.route('/library/<path:library_name>')
@login_required
def show_library(library_name):
    if 'plex_user_id' not in session:
        flash("Veuillez sélectionner un utilisateur.", "info")
    user_specific_plex_server = get_user_specific_plex_server()
    if not user_specific_plex_server:
        # Rediriger si la connexion échoue
        return redirect(url_for('plex_editor.index'))

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
        'note_filter_value': request.args.get('note_filter_value', ''),
        'date_filter_type': request.args.get('date_filter_type', 'aucun'),
        'date_filter_value': request.args.get('date_filter_value', ''),
        'viewdate_filter_type': request.args.get('viewdate_filter_type', 'aucun'),
        'viewdate_filter_value': request.args.get('viewdate_filter_value', '')
    }

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

    # ### NOUVELLE LOGIQUE POUR LA DATE DE VISIONNAGE (BLOC À INSÉRER) ###
    viewdate_type = current_filters_from_url.get('viewdate_filter_type')
    viewdate_value = current_filters_from_url.get('viewdate_filter_value')

    if viewdate_type and viewdate_type != 'aucun':
        try:
            if viewdate_type == 'viewed_recent_days':
                if viewdate_value.isdigit() and int(viewdate_value) > 0:
                    search_args['lastViewedAt>>='] = f"{int(viewdate_value)}d"
                elif viewdate_value:
                    raise ValueError("Nombre de jours invalide")

            elif viewdate_type in ['viewed_before_date', 'viewed_after_date']:
                if viewdate_value:
                    # On est un peu plus flexible sur le format de date ici aussi
                    parsed_date = None
                    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y'):
                        try:
                            parsed_date = datetime.strptime(viewdate_value, fmt)
                            break
                        except ValueError:
                            continue

                    if not parsed_date:
                        raise ValueError("Format de date non reconnu")

                    date_str_for_api = parsed_date.strftime('%Y-%m-%d')
                    if viewdate_type == 'viewed_before_date':
                        search_args['lastViewedAt<<='] = date_str_for_api
                    else: # viewed_after_date
                        search_args['lastViewedAt>>='] = date_str_for_api
                else:
                    raise ValueError("Date manquante")

        except ValueError as e_viewdate:
            flash(f"Valeur pour date de visionnage invalide ('{viewdate_value}'): {e_viewdate}. Filtre ignoré.", "warning")
            current_filters_from_url['viewdate_filter_type'] = 'aucun'
            current_filters_from_url['viewdate_filter_value'] = ''
    # ### FIN DU NOUVEAU BLOC ###

    sort_order = request.args.get('sort', 'addedAt:desc')
    search_args['sort'] = sort_order
    current_app.logger.info(f"show_library: Arguments finaux pour API search(): {search_args}")
    # ### NOUVELLE LOGIQUE DE FILTRAGE SPÉCIAL POUR LES SÉRIES VUES ###
    filter_fully_watched_shows_in_python = False
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

                    # ### ON ACTIVE NOTRE FILTRE SI NÉCESSAIRE ###
                    if library_object.type == 'show' and current_filters_from_url['vu'] == 'vu':
                        filter_fully_watched_shows_in_python = True
                        # Note: `search_args['unwatched'] = False` est déjà défini plus haut, c'est parfait.
                        current_app.logger.info("Filtre spécial activé: Séries entièrement vues (post-filtrage Python).")

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
            return redirect(url_for('plex_editor.index')) # (### MODIFICATION ICI ###) - Pointeur vers 'index'
        except Exception as e_outer:
            plex_error_message = f"Erreur majeure: {e_outer}"
            current_app.logger.error(f"show_library: Erreur majeure inattendue: {e_outer}", exc_info=True)
            flash("Erreur majeure inattendue.", 'danger')
            items_from_plex_api = []

        items_filtered_final = []
        if items_from_plex_api is not None:
            # On applique d'abord le filtre des séries vues si nécessaire
            if filter_fully_watched_shows_in_python:
                intermediate_list = [show for show in items_from_plex_api if show.leafCount == show.viewedLeafCount]
                current_app.logger.info(f"Filtrage Python 'Séries Vues': {len(intermediate_list)}/{len(items_from_plex_api)} séries restantes.")
            else:
                intermediate_list = items_from_plex_api

        # Ensuite, on applique le filtre des notes sur la liste déjà filtrée
        if filter_for_non_notes_in_python:
            items_filtered_final = [item for item in intermediate_list if item.userRating is None]
            current_app.logger.info(f"Filtrage Python 'Non Notés': {len(items_filtered_final)}/{len(intermediate_list)} éléments.")
        else:
            items_filtered_final = intermediate_list

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
            if library_name and "Bibliothèque" not in plex_error_message :
                flash(f"Erreur lors de l'accès à la bibliothèque '{library_name}'.", "danger")

# --- Ligne de débogage à ajouter ici ---
    current_app.logger.info(f"DEBUG_TAG: La valeur de RADARR_TAG_ON_ARCHIVE est '{current_app.config.get('RADARR_TAG_ON_ARCHIVE')}'")
    # --- Fin de la ligne de débogage ---

    return render_template('plex_editor/library.html',
                           title=f"Bibliothèque {library_name or 'Inconnue'} - {user_title_in_session}",
                           library_name=library_name,
                           library_obj=library_object,
                           items=items_filtered_final,
                           current_filters=current_filters_from_url,
                           plex_error=plex_error_message,
                           user_title=user_title_in_session,
                           config=current_app.config)

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