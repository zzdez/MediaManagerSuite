#app/search_ui/routes.py

from flask import render_template, request, flash, redirect, url_for, current_app, jsonify # Ajout de redirect et url_for ET current_app ET jsonify
from . import search_ui_bp
from app.utils.prowlarr_client import search_prowlarr
from app.utils.arr_client import search_sonarr_by_title, search_radarr_by_title # MODIFIED: Removed ArrClient
from app.utils.media_status_checker import check_media_status # Ajout de l'import
from app.utils.plex_client import get_user_specific_plex_server # MOVED IMPORT HERE
# Utiliser le login_required défini dans app/__init__.py pour la cohérence
from app import login_required
from app.utils.media_status_checker import check_media_status as util_check_media_status # Alias to avoid name collision

@search_ui_bp.route('/', methods=['GET'])
@login_required
def search_page():
    query = request.args.get('query', '').strip()
    results = None
    
    if query:
        # --- TRAITEMENT DES RÉSULTATS PROWLARR (SIMPLIFIÉ) ---
        # La vérification du statut Plex/Sonarr/Radarr est maintenant gérée par une route API séparée.
        raw_results = search_prowlarr(query)
        if raw_results is not None:
            # On ne vérifie plus le statut ici. On passe les résultats bruts.
            # Le template s'attend à 'results' qui est une liste de dictionnaires.
            # Chaque dictionnaire doit contenir au moins 'title' et 'guid' pour le nouveau bouton.
            results = raw_results
            # Assurez-vous que `search_prowlarr` retourne bien 'guid' pour chaque résultat.
            # Si ce n'est pas le cas, il faudra l'ajouter ou l'adapter.
            # Pour l'instant, on assume que Prowlarr fournit cela.
        else:
            flash("Erreur de communication avec Prowlarr.", "danger")
            results = []

    return render_template('search_ui/search.html', title="Recherche", results=results, query=query)


@search_ui_bp.route('/check_media_status', methods=['POST'])
@login_required
def check_media_status_api():
    data = request.json
    guid = data.get('guid') # guid is available from Prowlarr, but util_check_media_status primarily uses title
    title = data.get('title') # This is the release_title from Prowlarr

    if not title:
        current_app.logger.warn("/check_media_status - Titre manquant dans la requête POST.")
        return jsonify({'text': 'Titre manquant', 'status_class': 'text-danger'}), 400

    try:
        # Call the checker utility. It will use empty Plex caches by default.
        status_info_raw = util_check_media_status(release_title=title)

        current_app.logger.debug(f"Résultat de util_check_media_status pour '{title}' (GUID: {guid}): {status_info_raw}")

        status_label = status_info_raw.get('status', 'Indéterminé')
        # 'details' from util_check_media_status is usually the parsed title like "Movie Title (2023)" or "Show S01E01"
        details_text = status_info_raw.get('details', title)

        # Construct the text to display
        if status_label in ['Déjà Présent', 'Non Trouvé (Radarr)', 'Série non trouvée', 'Erreur Analyse', 'Indéterminé']:
            # For these statuses, the label itself is descriptive enough.
            final_text = status_label
        else:
            # For other statuses like "Manquant (Surveillé)", "Non Surveillé", include details.
            final_text = f"{status_label}: {details_text}"

        badge_color = status_info_raw.get('badge_color', 'secondary')
        status_class_map = {
            'success': 'text-success',  # e.g., Déjà Présent
            'warning': 'text-warning',  # e.g., Manquant (Surveillé)
            'danger': 'text-danger',    # e.g., Erreur Analyse
            'secondary': 'text-body-secondary', # e.g., Non Surveillé, Indéterminé (Bootstrap 5.3 class for muted text)
            'dark': 'text-body-secondary' # e.g., Non Trouvé (Radarr/Sonarr)
            # 'info', 'primary' are not typically returned by current util_check_media_status
        }
        status_class = status_class_map.get(badge_color, 'text-body-secondary') # Default to muted text

        # Override if the status itself indicates an error more strongly
        if status_info_raw.get('status') == 'Erreur Analyse':
             status_class = 'text-danger'
             final_text = "Erreur d'analyse du statut" # More user-friendly
        elif "erreur" in status_label.lower() and status_label != 'Erreur Analyse': # Catch other potential error strings
            status_class = 'text-danger'
            # final_text is already set to status_label which would contain "erreur..."

        current_app.logger.info(f"Statut API pour '{title}': text='{final_text}', class='{status_class}'")
        return jsonify({'text': final_text, 'status_class': status_class})

    except Exception as e:
        current_app.logger.error(f"Erreur API dans /check_media_status pour '{title}' (GUID: {guid}): {e}", exc_info=True)
        return jsonify({'text': 'Erreur serveur interne', 'status_class': 'text-danger'}), 500


# La route /api/prepare_mapping_details a été supprimée car elle n'est plus utilisée.

# Note: La route /results n'est plus explicitement nécessaire si /search gère tout.
# Si vous souhaitez la conserver pour une raison spécifique (ex: liens directs vers les résultats),
# assurez-vous que sa logique est cohérente avec celle de search_page ou qu'elle redirige.
# Pour l'instant, je vais la commenter pour éviter la duplication de logique.
# Si vous voulez la garder, il faudra la mettre à jour également.

# @search_ui_bp.route('/results')
# @login_required
# def search_results():
#     """Exécute la recherche et affiche les résultats."""
#     query = request.args.get('query', '').strip()
#     if not query:
#         flash("Veuillez entrer un terme à rechercher.", "warning")
#         return redirect(url_for('search_ui.search_page'))

#     raw_results = search_prowlarr(query)

#     if raw_results is None:
#         flash("Erreur de communication avec Prowlarr.", "danger")
#         results = []
#     elif not raw_results:
#         results = []
#     else:
#         # Enrichir chaque résultat avec les informations de statut
#         for result in raw_results:
#             result['status_info'] = check_media_status(result['title'])
#         results = raw_results

#     return render_template('search_ui/search.html', title=f"Résultats pour \"{query}\"", results=results, query=query)

import requests
import json # Added json import
from flask import jsonify
from app.utils.rtorrent_client import add_torrent_data_and_get_hash_robustly, add_magnet_and_get_hash_robustly
from app.utils.mapping_manager import add_or_update_torrent_in_map
# Imports for new logic in download_and_map
from app.utils.arr_client import (
    get_sonarr_series_by_id, update_sonarr_series, update_radarr_movie,
    _radarr_api_request, # Kept for direct movie detail fetching by ID for existing items
    add_series_by_title_to_sonarr, add_movie_by_title_to_radarr,
    parse_media_name # Used for parsing release_name to get title/year for new adds
)
# Removed: add_new_series_to_sonarr, add_new_movie_to_radarr (now called by add_*_by_title_to_* functions in arr_client)
# Removed: search_sonarr_by_title, search_radarr_by_title (now called by add_*_by_title_to_* functions in arr_client)
# Removed: from guessit import guessit (functionality now encapsulated in arr_client.parse_media_name)


@search_ui_bp.route('/download-and-map', methods=['POST'])
@login_required
def download_and_map():
    data = request.get_json()
    release_name = data.get('releaseName') # Prowlarr release title
    download_link = data.get('downloadLink')
    indexer_id = data.get('indexerId')
    guid = data.get('guid') # Prowlarr GUID, might contain tvdb/tmdb/imdb id
    instance_type = data.get('instanceType') # 'sonarr' or 'radarr'
    media_id_from_js = data.get('mediaId') # Sonarr/Radarr internal ID, or external TVDB/TMDB ID, or 'NEW_ITEM_FROM_PROWLARR'
    action_type = data.get('actionType', 'map_existing') # 'map_existing' or 'add_then_map'

    current_app.logger.info(f"Download&Map: release='{release_name}', media_id='{media_id_from_js}', action='{action_type}', instance_type='{instance_type}'")

    if not all([release_name, download_link, indexer_id, guid, instance_type, media_id_from_js]):
        missing_params = [p for p,v in {
            "releaseName": release_name, "downloadLink": download_link, "indexerId": indexer_id,
            "guid": guid, "instanceType": instance_type, "mediaId": media_id_from_js
        }.items() if not v]
        return jsonify({'status': 'error', 'message': f'Données manquantes dans la requête: {", ".join(missing_params)}'}), 400

    actual_media_id_for_mapping = None
    internal_instance_type = None # Will be 'sonarr' or 'radarr'

    if instance_type_from_js == 'episode':
        internal_instance_type = 'sonarr'
    elif instance_type_from_js == 'movie':
        internal_instance_type = 'radarr'
    else:
        current_app.logger.warning(f"Download&Map: instanceType '{instance_type_from_js}' from JS is not 'episode' or 'movie'. Attempting to parse from release_name.")
        parsed_for_type = parse_media_name(release_name) # from arr_client
        if parsed_for_type['type'] == 'tv': # parse_media_name returns 'tv' for series
            internal_instance_type = 'sonarr'
            current_app.logger.info(f"Inferred instance_type as 'sonarr' for release '{release_name}' based on its name.")
        elif parsed_for_type['type'] == 'movie':
            internal_instance_type = 'radarr'
            current_app.logger.info(f"Inferred instance_type as 'radarr' for release '{release_name}' based on its name.")
        else:
            return jsonify({'status': 'error', 'message': f"Type d'instance ('{instance_type_from_js}') non reconnu et impossible à déduire de '{release_name}'."}), 400

    current_app.logger.info(f"Download&Map: internal_instance_type set to '{internal_instance_type}'")

    try: # This try-except block is for ID determination and media addition/update
        if action_type == 'add_then_map':
            # Check if media_id_from_js indicates a new item
            if (isinstance(media_id_from_js, str) and "NEW_ITEM" in media_id_from_js.upper()):
                current_app.logger.info(f"Download&Map: Processing 'add_then_map' for NEW_ITEM. Release: '{release_name}', Instance: {internal_instance_type}")

                parsed_release_info = parse_media_name(release_name) # from arr_client
                if not parsed_release_info or not parsed_release_info.get('title'):
                    raise ValueError(f"Impossible de parser le titre depuis la release '{release_name}' pour l'ajout.")

                item_title_to_add = parsed_release_info['title']
                item_year_to_add = parsed_release_info.get('year') # Can be None
                current_app.logger.info(f"Download&Map: Titre parsé pour ajout: '{item_title_to_add}', Année: {item_year_to_add}")

                added_media = None
                if internal_instance_type == 'sonarr':
                    added_media = add_series_by_title_to_sonarr(item_title_to_add, item_year_to_add)
                elif internal_instance_type == 'radarr':
                    added_media = add_movie_by_title_to_radarr(item_title_to_add, item_year_to_add)
                # No else needed, internal_instance_type is validated

                if added_media and added_media.get('id'):
                    actual_media_id_for_mapping = added_media.get('id')
                    current_app.logger.info(f"Download&Map: Média '{item_title_to_add}' ajouté à {internal_instance_type} avec ID {actual_media_id_for_mapping}.")
                else:
                    raise ValueError(f"Échec de l'ajout de '{item_title_to_add}' à {internal_instance_type} (pas d'ID retourné ou échec).")

            else: # media_id_from_js is an existing Sonarr/Radarr ID (even if actionType is add_then_map)
                current_app.logger.info(f"Download&Map: 'add_then_map' avec mediaId '{media_id_from_js}'. Traitement comme ID existant.")
                try:
                    internal_id_candidate = int(media_id_from_js)
                except (ValueError, TypeError): # Handle cases where media_id_from_js might be None or non-integer string
                    raise ValueError(f"ID média '{media_id_from_js}' invalide pour 'add_then_map' sur un item existant.")

                item_details = None
                if internal_instance_type == 'sonarr':
                    item_details = get_sonarr_series_by_id(internal_id_candidate)
                elif internal_instance_type == 'radarr':
                    item_details = _radarr_api_request('GET', f'movie/{internal_id_candidate}')

                if item_details and item_details.get('id'):
                    actual_media_id_for_mapping = item_details.get('id')
                    if not item_details.get('monitored', False):
                        current_app.logger.info(f"Download&Map: Item ID {actual_media_id_for_mapping} ({internal_instance_type}) trouvé mais non surveillé. Mise à jour...")
                        item_details['monitored'] = True
                        if internal_instance_type == 'sonarr' and 'seasons' in item_details:
                            for season in item_details['seasons']: season['monitored'] = True

                        update_success = False
                        if internal_instance_type == 'sonarr': update_success = update_sonarr_series(item_details)
                        elif internal_instance_type == 'radarr': update_success = update_radarr_movie(item_details)
                        if not update_success: current_app.logger.warning(f"Échec de la mise à jour du statut surveillé pour ID {actual_media_id_for_mapping}.")
                    else:
                         current_app.logger.info(f"Download&Map: Item ID {actual_media_id_for_mapping} ({internal_instance_type}) déjà surveillé.")
                else:
                    raise ValueError(f"Média ID {media_id_from_js} (entier) non trouvé dans {internal_instance_type} pour 'add_then_map'.")

        elif action_type == 'map_existing':
            if media_id_from_js is None:
                 raise ValueError("ID média manquant pour 'map_existing'.")
            try:
                actual_media_id_for_mapping = int(media_id_from_js)
            except (ValueError, TypeError): # Handle None or non-integer string
                raise ValueError(f"ID média invalide pour 'map_existing': {media_id_from_js}")
            current_app.logger.info(f"Download&Map: 'map_existing' pour ID {actual_media_id_for_mapping} ({internal_instance_type}).")
            # Consider adding monitoring check/update here as well if an existing item might not be monitored.

        else:
            raise ValueError(f"Type d'action inconnu: {action_type}")

        if actual_media_id_for_mapping is None:
            raise ValueError("Impossible de déterminer l'ID média interne final.")

    except ValueError as ve: # Catches ValueErrors from ID determination, parsing, or arr_client add functions
        current_app.logger.error(f"Download&Map: Erreur (ValueError) dans la phase d'identification/ajout du média pour '{release_name}': {ve}", exc_info=False) # exc_info=False for cleaner log for ValueErrors
        return jsonify({'status': 'error', 'message': str(ve)}), 400
    # The global try...except Exception as e (outside this diff) will catch other unexpected errors.

    # --- Step 2: Proceed with torrent download using actual_media_id_for_mapping ---
    # This part of the code (downloading torrent, rtorrent interaction, mapping file update)
    # remains largely the same as before, but uses `actual_media_id_for_mapping` and `internal_instance_type`.
    current_app.logger.info(f"Download&Map: Procédure de téléchargement pour ID {actual_media_id_for_mapping}, Release: '{release_name}'")
    torrent_hash = None

    # --- Step 2: Proceed with torrent download using actual_media_id_for_mapping for labels ---
    torrent_hash = None
    error_msg_add = None
    torrent_data = None

    # Use final actual_media_id_for_mapping for consistent rTorrent label
    label_for_rtorrent = f"mms-{instance_type}-{actual_media_id_for_mapping}"

    target_download_path_rtorrent = None
    if instance_type == 'sonarr':
        target_download_path_rtorrent = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_SONARR_PATH') # Updated config key
    elif instance_type == 'radarr':
        target_download_path_rtorrent = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_RADARR_PATH') # Updated config key

    if not target_download_path_rtorrent:
        current_app.logger.warning(f"Aucun chemin de destination rTorrent configuré pour instanceType '{instance_type}' via SEEDBOX_RTORRENT_INCOMING_SONARR_PATH/RADARR_PATH. Le torrent sera téléchargé dans le répertoire par défaut de rTorrent.")
        # Pas besoin de retourner une erreur, rTorrent utilisera son défaut.

    try:
        # CAS 1: Lien Magnet
        if download_link.startswith("magnet:"):
            current_app.logger.info(f"Download&Map: Traitement direct du lien magnet pour '{release_name}': {download_link}")
            torrent_hash, error_msg_add = add_magnet_and_get_hash_robustly(
                download_link,
                label=label_for_rtorrent,
                destination_path=target_download_path_rtorrent
            )
        # CAS 2: Lien de téléchargement de fichier .torrent (HTTP/S)
        else:
            current_app.logger.info(f"Download&Map: Téléchargement du fichier .torrent pour '{release_name}' depuis URL: {download_link}, IndexerID: {indexer_id}, GUID: {guid}")

            ygg_indexer_id_config = current_app.config.get('YGG_INDEXER_ID')

            # Logique de téléchargement unifiée (similaire à download_torrent_proxy)
            if str(ygg_indexer_id_config) == str(indexer_id):
                # --- CAS SPÉCIAL YGG ---
                current_app.logger.info(f"Download&Map: Détection de YGG (ID: {indexer_id}). Utilisation de la méthode de téléchargement directe via GUID.")
                ygg_cookie = current_app.config.get('YGG_COOKIE')
                ygg_user_agent = current_app.config.get('YGG_USER_AGENT')
                ygg_base_url = current_app.config.get('YGG_BASE_URL')

                if not all([ygg_cookie, ygg_user_agent, ygg_base_url]):
                    raise ValueError("Configuration YGG manquante (YGG_COOKIE, YGG_USER_AGENT, ou YGG_BASE_URL).")

                try:
                    split_guid = guid.split('?id=')
                    if len(split_guid) > 1:
                        release_id_ygg = split_guid[1].split('&')[0]
                    else:
                        raise IndexError("Format de GUID YGG inattendu, '?id=' non trouvé.")
                except IndexError:
                    raise ValueError(f"Impossible d'extraire l'ID de la release depuis le GUID YGG : {guid}")

                final_ygg_download_url = f"{ygg_base_url.rstrip('/')}/engine/download_torrent?id={release_id_ygg}"
                headers = {'User-Agent': ygg_user_agent, 'Cookie': ygg_cookie}

                current_app.logger.info(f"Download&Map (YGG): Appel de l'URL YGG directe : {final_ygg_download_url}")
                response = requests.get(final_ygg_download_url, headers=headers, timeout=45, allow_redirects=True)
            else:
                # --- CAS STANDARD POUR LES AUTRES INDEXERS ---
                current_app.logger.info(f"Download&Map: Indexer standard (ID: {indexer_id}). Utilisation du lien Prowlarr direct: {download_link}")
                standard_user_agent = current_app.config.get('YGG_USER_AGENT', 'Mozilla/5.0') # Fallback User-Agent
                headers = {'User-Agent': standard_user_agent}
                response = requests.get(download_link, headers=headers, timeout=45, allow_redirects=True)

            response.raise_for_status() # Lève une exception pour les statuts HTTP 4xx/5xx
            content_type = response.headers.get('Content-Type', '').lower()
            if 'application/x-bittorrent' not in content_type and 'application/octet-stream' not in content_type:
                preview = response.text[:200] if response.content else ""
                raise ValueError(f"La réponse n'est pas un fichier .torrent valide. Content-Type: '{content_type}'. Contenu: '{preview}...'")

            torrent_data = response.content
            if not torrent_data:
                raise ValueError("Le contenu du fichier .torrent téléchargé est vide.")
            current_app.logger.info(f"Download&Map: Fichier .torrent de {len(torrent_data)} bytes téléchargé avec succès pour '{release_name}'.")

            # Ajout à rTorrent en utilisant les données du torrent
            torrent_hash, error_msg_add = add_torrent_data_and_get_hash_robustly(
                torrent_data,
                release_name, # filename_for_rtorrent
                label=label_for_rtorrent,
                destination_path=target_download_path_rtorrent
            )

        # --- Traitement commun après tentative d'ajout (magnet ou données) ---
        if error_msg_add or not torrent_hash:
            final_error_msg = error_msg_add or f"Erreur inconnue lors de l'ajout du torrent '{release_name}' à rTorrent ou de la récupération du hash."
            current_app.logger.error(f"Download&Map: Échec final de l'ajout/récupération hash pour '{release_name}'. Message: {final_error_msg}")
            return jsonify({'status': 'error', 'message': final_error_msg}), 500

        current_app.logger.info(f"Download&Map: Torrent '{release_name}' ajouté à rTorrent. Hash '{torrent_hash}' récupéré. Tentative de mapping.")

        # --- Suite du mapping ---
        map_label_mms = f"mms-search-{instance_type}-{media_id}" # Label spécifique pour le mapping MMS

        # Le chemin de téléchargement sur le seedbox pour le mapping.
        # Si target_download_path_rtorrent a été défini, rTorrent devrait l'utiliser comme base.
        # Sinon, rTorrent utilise son chemin par défaut. Le mapping doit refléter cela.
        # Pour être robuste, on ne peut pas toujours prédire le chemin exact si rTorrent a des règles complexes (ex: via label).
        # On utilise une convention : <rTorrent_configured_path_for_type>/<release_name> ou <rTorrent_default_path>/<release_name>
        # Il est crucial que `add_or_update_torrent_in_map` enregistre un `seedbox_download_path` qui sera scannable par le SeedboxImporter.

        # Tentative de construction du seedbox_dl_path pour le mapping:
        # Si SEEDBOX_RTORRENT_INCOMING_SONARR_PATH/RADARR_PATH est défini, on l'utilise comme base.
        base_map_path = target_download_path_rtorrent
        if not base_map_path:
            # Si aucun chemin spécifique n'est défini, rTorrent utilisera son chemin par défaut global.
            # MMS ne peut pas connaître ce chemin par défaut de manière fiable sans configuration supplémentaire.
            # Utiliser un placeholder ou logguer une erreur plus sévère si ce chemin est critique.
            current_app.logger.warning(f"Download&Map: Chemin de téléchargement rTorrent non spécifiquement configuré pour '{instance_type}'. Le mapping se basera sur un chemin par défaut hypothétique '/downloads/torrents', ce qui peut être incorrect.")
            base_map_path = "/downloads/torrents" # Fallback très générique, potentiellement incorrect.

        seedbox_dl_path_for_map = f"{base_map_path.rstrip('/')}/{release_name}"

        current_app.logger.info(f"Download&Map: Chemin de téléchargement estimé pour le mapping: '{seedbox_dl_path_for_map}'")

        map_success = add_or_update_torrent_in_map(
            torrent_hash=torrent_hash,
            release_name=release_name,
            app_type=instance_type,
            target_id=str(media_id),
            label=map_label_mms,
            seedbox_download_path=seedbox_dl_path_for_map, # Chemin sur le seedbox où le contenu sera
            original_torrent_name=f"{release_name}.torrent" # Nom du fichier .torrent (ou une approximation)
        )

        if not map_success:
            current_app.logger.error(f"Download&Map: Torrent '{release_name}' (hash: {torrent_hash}) ajouté à rTorrent, mais l'écriture du mapping a échoué.")
            # Le torrent est dans rTorrent, mais le mapping a échoué. L'utilisateur doit être informé.
            return jsonify({'status': 'warning', 'message': f"Torrent '{release_name}' ajouté à rTorrent, mais le mapping a échoué. Le téléchargement démarrera mais le post-traitement automatique pourrait ne pas fonctionner."}), 200 # OK, mais avec un avertissement

        final_message = f"Torrent '{release_name}' (hash: {torrent_hash[:8]}...) ajouté à rTorrent et mappé avec succès pour {instance_type} ID {media_id} !"
        current_app.logger.info(f"Download&Map: {final_message}")
        return jsonify({'status': 'success', 'message': final_message})

    except requests.exceptions.RequestException as req_e:
        current_app.logger.error(f"Download&Map: Erreur de requête ({type(req_e).__name__}) lors du téléchargement du .torrent pour '{release_name}': {req_e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f"Erreur réseau ou du serveur distant lors du téléchargement du .torrent: {req_e}"}), 502
    except ValueError as val_e: # Pour les erreurs de configuration, de contenu invalide, ou GUID
        current_app.logger.error(f"Download&Map: Erreur de valeur ({type(val_e).__name__}) pour '{release_name}': {val_e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f"Erreur de configuration, de données invalides ou de GUID: {val_e}"}), 400
    except Exception as e:
        current_app.logger.error(f"Download&Map: Erreur majeure pour '{release_name}': {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f"Erreur serveur inattendue lors du traitement de '{release_name}': {str(e)}"}), 500

@search_ui_bp.route('/api/search-arr', methods=['GET'])
def search_arr_proxy():
    query = request.args.get('query')
    media_type = request.args.get('type') # 'sonarr' ou 'radarr'

    if not query:
        return jsonify({'error': 'Le terme de recherche est manquant'}), 400

    arr_results = []
    try:
        if media_type == 'sonarr':
            arr_results = search_sonarr_by_title(query)
        elif media_type == 'radarr':
            arr_results = search_radarr_by_title(query)
        else:
            return jsonify({'error': 'Type de média invalide'}), 400
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la recherche {media_type} pour '{query}': {e}")
        return jsonify({'error': f'Erreur de communication avec {media_type.capitalize()}'}), 500

    detailed_results = []
    if arr_results:
        for item in arr_results:
            # Pour chaque item, on construit un dictionnaire propre
            is_added = item.get('id') and item.get('id') > 0

            # Déterminer l'ID à utiliser : l'ID interne si le média est déjà ajouté, sinon l'ID externe
            media_id = item.get('id') if is_added else (item.get('tvdbId') or item.get('tmdbId'))

            # Extraire l'URL du poster
            poster_url = None
            for img in item.get('images', []):
                if img.get('coverType') == 'poster' and (img.get('remoteUrl') or img.get('url')):
                    # Radarr utilise parfois 'remoteUrl', Sonarr utilise 'url' dans certaines réponses de lookup
                    poster_url = img.get('remoteUrl') or img.get('url')
                    break

            details = {
                'id': media_id,
                'title': item.get('title'),
                'year': item.get('year'),
                'overview': item.get('overview', 'Aucun résumé disponible.'),
                'status': item.get('status', 'Inconnu'), # ex: 'continuing' ou 'ended'
                # Le nombre de saisons n'est pertinent que pour Sonarr
                'seasons': len(item.get('seasons', [])) if media_type == 'sonarr' and item.get('seasons') is not None else 'N/A',
                'poster': poster_url,
                'isAdded': is_added # Pour que le frontend sache si le média est déjà dans la bibliothèque
            }
            detailed_results.append(details)

    return jsonify(detailed_results)

# Imports nécessaires pour la nouvelle route download_torrent
from flask import Response, stream_with_context
# requests est déjà importé plus haut dans le fichier
# current_app est déjà importé
# login_required est déjà importé
# request est déjà importé via 'from flask import ..., request, ...'

@search_ui_bp.route('/download_torrent_proxy')
@login_required
def download_torrent_proxy():
    url = request.args.get('url') # C'est le 'downloadLink' de Prowlarr
    release_name = request.args.get('release_name', 'download.torrent')
    indexer_id = request.args.get('indexer_id')
    guid = request.args.get('guid') # On a besoin du GUID maintenant

    if not all([url, release_name, indexer_id, guid]):
        current_app.logger.error(f"Proxy download: Paramètres manquants. Reçu: url='{url}', release_name='{release_name}', indexer_id='{indexer_id}', guid='{guid}'")
        return "Erreur: Paramètres manquants (url, release_name, indexer_id, guid).", 400

    ygg_indexer_id = current_app.config.get('YGG_INDEXER_ID')

    # S'assurer que release_name n'a pas déjà .torrent pour éviter .torrent.torrent
    if release_name.lower().endswith('.torrent'):
        base_name = release_name[:-len('.torrent')]
    else:
        base_name = release_name
    # Nettoyer le nom de base pour les caractères invalides et remplacer les espaces
    clean_base_name = "".join(c if c.isalnum() or c in [' ', '.', '_', '-'] else '_' for c in base_name)
    final_filename = f"{clean_base_name.replace(' ', '_')}.torrent"


    try:
        # STRATÉGIE D'AIGUILLAGE BASÉE SUR L'ID DE L'INDEXER
        if str(ygg_indexer_id) == str(indexer_id):
            # --- CAS SPÉCIAL YGG ---
            current_app.logger.info(f"Proxy download: Détection de YGG (ID: {indexer_id}). Utilisation de la méthode de téléchargement directe via GUID.")

            ygg_cookie = current_app.config.get('YGG_COOKIE')
            ygg_user_agent = current_app.config.get('YGG_USER_AGENT')
            ygg_base_url = current_app.config.get('YGG_BASE_URL') # Doit être https://www.yggtorrent.top par défaut

            if not all([ygg_cookie, ygg_user_agent, ygg_base_url]):
                missing_configs = []
                if not ygg_cookie: missing_configs.append("YGG_COOKIE")
                if not ygg_user_agent: missing_configs.append("YGG_USER_AGENT")
                if not ygg_base_url: missing_configs.append("YGG_BASE_URL")
                error_msg = f"Configuration YGG manquante pour {', '.join(missing_configs)}."
                current_app.logger.error(f"Proxy download (YGG): {error_msg}")
                raise ValueError(error_msg)

            # Extraire l'ID de la release depuis le GUID
            # Exemple de GUID YGG: https://yggapi.eu/torrent?id=1234567 ou yggtorrent.com/torrent?id=12345
            # On cherche "?id="
            try:
                # Simple split, pourrait être rendu plus robuste avec regex si les formats de GUID varient beaucoup
                split_guid = guid.split('?id=')
                if len(split_guid) > 1:
                    release_id_ygg = split_guid[1].split('&')[0] # Prend ce qui suit id= et avant un éventuel &
                else:
                    raise IndexError("Format de GUID YGG inattendu, '?id=' non trouvé.")
                current_app.logger.info(f"Proxy download (YGG): ID de release extrait du GUID '{guid}': '{release_id_ygg}'")
            except IndexError:
                current_app.logger.error(f"Proxy download (YGG): Impossible d'extraire l'ID de la release depuis le GUID YGG : {guid}")
                raise ValueError(f"Impossible d'extraire l'ID de la release depuis le GUID YGG : {guid}")

            # Construire l'URL de téléchargement directe
            # S'assurer que ygg_base_url se termine par / et que engine ne commence pas par /
            # ou l'inverse, pour éviter double // ou absence de /
            final_ygg_download_url = f"{ygg_base_url.rstrip('/')}/engine/download_torrent?id={release_id_ygg}"

            headers = {
                'User-Agent': ygg_user_agent,
                'Cookie': ygg_cookie
                # Les en-têtes Accept et Accept-Language du test précédent peuvent être ajoutés si nécessaire,
                # mais souvent pour un téléchargement direct de fichier, ils ne sont pas cruciaux.
            }

            current_app.logger.info(f"Proxy download (YGG): Appel de l'URL YGG directe : {final_ygg_download_url}")
            response = requests.get(final_ygg_download_url, headers=headers, timeout=45, allow_redirects=True) # allow_redirects=True est important

        else:
            # --- CAS STANDARD POUR LES AUTRES INDEXERS ---
            current_app.logger.info(f"Proxy download: Indexer standard (ID: {indexer_id}). Utilisation du lien Prowlarr direct: {url}")
            # Utiliser un User-Agent générique mais standard pour les autres
            standard_user_agent = current_app.config.get('YGG_USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36')
            headers = {
                'User-Agent': standard_user_agent
            }
            response = requests.get(url, headers=headers, timeout=45, allow_redirects=True)

        # --- TRAITEMENT COMMUN DE LA RÉPONSE ---
        current_app.logger.info(f"Proxy download: Réponse reçue. Statut: {response.status_code}. URL Finale (après redirections éventuelles): {response.url}")
        response.raise_for_status() # Lève une exception pour les statuts HTTP 4xx/5xx

        content_type = response.headers.get('Content-Type', '').lower()
        current_app.logger.info(f"Proxy download: Content-Type de la réponse: '{content_type}'")

        # Vérification du Content-Type. Certains indexers peuvent retourner application/octet-stream.
        if 'application/x-bittorrent' not in content_type and 'application/octet-stream' not in content_type:
            preview = response.text[:500] if response.content else ""
            current_app.logger.error(f"Proxy download: La réponse n'est pas un fichier .torrent valide. Content-Type: '{content_type}'. Début du contenu: '{preview}'")
            raise ValueError(f"La réponse n'est pas un fichier .torrent valide. Content-Type: '{content_type}'. Vérifiez les logs pour un aperçu du contenu.")

        torrent_data = response.content
        current_app.logger.info(f"Proxy download: Fichier .torrent de {len(torrent_data)} bytes téléchargé avec succès.")

        return Response(
            torrent_data,
            mimetype='application/x-bittorrent',
            headers={'Content-Disposition': f'attachment;filename="{final_filename}"'}
        )

    except requests.exceptions.RequestException as req_e:
        current_app.logger.error(f"Proxy download: Erreur de requête ({type(req_e).__name__}) : {req_e}", exc_info=True)
        return Response(f"Erreur de réseau ou du serveur distant lors de la tentative de téléchargement: {req_e}", status=502) # Bad Gateway
    except ValueError as val_e: # Pour les erreurs de configuration ou de contenu invalide, ou GUID
        current_app.logger.error(f"Proxy download: Erreur de valeur ({type(val_e).__name__}) : {val_e}", exc_info=True)
        return Response(f"Erreur de configuration, de données invalides ou de GUID: {val_e}", status=400) # Bad Request
    except Exception as e:
        current_app.logger.error(f"Proxy download: Erreur inattendue ({type(e).__name__}) : {e}", exc_info=True)
        return Response(f"Une erreur serveur inattendue est survenue: {e}", status=500)

@search_ui_bp.route('/download-torrent')
@login_required
def download_torrent():
    """
    Acts as a proxy to download a .torrent file from a URL provided by Prowlarr.
    NOTE: This is the OLDER version, kept for reference or specific use cases if any.
    The new '/download_torrent_proxy' is generally preferred.
    """
    torrent_url = request.args.get('url')
    release_name_arg = request.args.get('release_name')

    if not torrent_url:
        # Devrait être une réponse Flask, ex: Response("...", status=400) ou jsonify
        return Response("URL de téléchargement manquante.", status=400)

    # Construire le nom de fichier
    if release_name_arg:
        # Nettoyer et s'assurer que le nom se termine par .torrent
        filename_base = "".join(c if c.isalnum() or c in [' ', '.', '_', '-'] else '_' for c in release_name_arg)
        if filename_base.lower().endswith('.torrent'):
            filename_base = filename_base[:-len('.torrent')]
        filename = f"{filename_base}.torrent".replace(' ', '_')
    else:
        # Essayer d'extraire de l'URL Prowlarr si 'file=' est présent, sinon nom par défaut
        # Exemple d'URL Prowlarr: http://...&file=MonFichier.torrent
        if 'file=' in torrent_url:
            try:
                extracted_name = torrent_url.split('file=')[1].split('&')[0]
                # Nettoyer et s'assurer que le nom se termine par .torrent
                filename_base = "".join(c if c.isalnum() or c in [' ', '.', '_', '-'] else '_' for c in extracted_name)
                if filename_base.lower().endswith('.torrent'):
                    filename_base = filename_base[:-len('.torrent')]
                filename = f"{filename_base}.torrent".replace(' ', '_')
            except Exception:
                filename = "downloaded.torrent"
        else:
            filename = "downloaded.torrent"

    current_app.logger.info(f"Proxying .torrent download (old route) from: {torrent_url} as filename: {filename}")

    try:
        # On utilise stream=True pour ne pas charger tout le fichier en mémoire sur le serveur
        # allow_redirects=True est le défaut, ce qui est bien ici.
        # requests gérera les redirections HTTP. S'il rencontre un schéma non supporté (magnet) après redirection, il lèvera une erreur.
        req = requests.get(torrent_url, stream=True, timeout=30) # Augmentation du timeout pour être sûr
        req.raise_for_status() # Lève une exception si le statut n'est pas 200-299

        # Vérifier si le Content-Type de la réponse finale est bien un torrent
        # Ceci est une protection supplémentaire. Si Prowlarr/indexer renvoie du HTML/JSON d'erreur avec un statut 200, on le bloque.
        content_type_final = req.headers.get('Content-Type', '').lower()
        if not ('application/x-bittorrent' in content_type_final or
                'application/octet-stream' in content_type_final or # Certains serveurs utilisent octet-stream
                filename.endswith('.torrent')): # Si le nom de fichier final (après extraction) se termine par .torrent
            current_app.logger.warning(f"Proxy download (old route): Content-Type inattendu '{content_type_final}' pour {torrent_url} (filename: {filename}). Arrêt.")
            # On pourrait essayer de lire un peu pour voir si c'est une erreur JSON/HTML connue, mais pour l'instant, on est strict.
            return Response(f"Contenu inattendu reçu de l'URL distante. Type: {content_type_final}", status=502) # Bad Gateway

        # On renvoie la réponse au navigateur
        return Response(
            stream_with_context(req.iter_content(chunk_size=1024)),
            headers={
                'Content-Type': 'application/x-bittorrent', # On force le type pour le client
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )

    except requests.exceptions.InvalidSchema as e_schema:
        # Spécifiquement pour les cas où une redirection mène à un magnet:
        current_app.logger.error(f"Erreur de schéma (souvent magnet) lors du téléchargement du .torrent (old route) depuis {torrent_url}: {e_schema}")
        return Response(f"Impossible de télécharger : le lien pointe vers un type non supporté (ex: magnet) : {e_schema}", status=400)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Erreur lors du téléchargement du .torrent (old route) depuis {torrent_url}: {e}")
        # Renvoyer l'erreur de manière plus structurée, peut-être en fonction du type d'erreur 'e'
        status_code = 502 # Bad Gateway par défaut pour les erreurs de requête vers un autre serveur
        if isinstance(e, requests.exceptions.HTTPError):
            status_code = e.response.status_code if e.response is not None else 500
        elif isinstance(e, requests.exceptions.ConnectTimeout) or isinstance(e, requests.exceptions.ReadTimeout):
            status_code = 504 # Gateway Timeout

        return Response(f"Impossible de télécharger le fichier .torrent : {e}", status=status_code)
    except Exception as ex_generic:
        current_app.logger.error(f"Erreur générique inattendue lors du téléchargement du .torrent (old route) {torrent_url}: {ex_generic}", exc_info=True)
        return Response(f"Erreur serveur inattendue lors de la tentative de téléchargement.", status=500)
