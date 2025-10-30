# app/search_ui/__init__.py

import logging
from flask import Blueprint, render_template, request, flash, jsonify, Response, stream_with_context, current_app, url_for, session
from app.auth import login_required
from config import Config
from app.utils import arr_client
from Levenshtein import distance as levenshtein_distance
from app.utils.arr_client import parse_media_name
from app.utils.prowlarr_client import search_prowlarr
from app.utils.config_manager import load_search_categories, load_filter_options
from app.utils.release_parser import parse_release_data
from app.utils.tmdb_client import TheMovieDBClient
from app.utils.tvdb_client import CustomTVDBClient

# 1. Définition du Blueprint (seul code global avec les imports "sûrs")
search_ui_bp = Blueprint(
    'search_ui',
    __name__,
    template_folder='templates',
    static_folder='static'
)

# 2. Toutes les routes. Les imports "à risque" sont maintenant DANS les fonctions.

@search_ui_bp.route('/api/search/get_session_queries', methods=['GET'])
@login_required
def get_session_queries():
    """Récupère et supprime les requêtes de recherche stockées dans la session."""
    queries = session.pop('missing_episodes_queries', None)
    if queries:
        return jsonify({'queries': queries})
    return jsonify({'queries': []})

@search_ui_bp.route('/', methods=['GET'])
@login_required
def search_page():
    """Affiche la page de recherche principale."""
    return render_template('search_ui/search.html')

# --- API Routes ---

@search_ui_bp.route('/api/media/search', methods=['POST'])
@login_required
def media_search():
    """Recherche des médias (films ou séries) via les API externes (TMDb/TVDB) et enrichit avec le statut du trailer."""
    from app.utils import trailer_manager # Import local
    from app.utils.media_info_manager import media_info_manager

    data = request.get_json()
    query = data.get('query')
    media_type_search = data.get('media_type', 'movie')

    if not query:
        return jsonify({"error": "La requête de recherche est vide."}), 400

    try:
        results = []
        if media_type_search == 'movie':
            client = TheMovieDBClient()
            search_results = client.search_movie(query, lang='fr-FR')
            for item in search_results:
                external_id = item.get('id')
                trailer_status = trailer_manager.get_trailer_status('movie', external_id) if external_id else 'NONE'
                media_details = media_info_manager.get_media_details('movie', external_id) if external_id else {}
                results.append({
                    'id': external_id,
                    'title': item.get('title'),
                    'original_title': item.get('original_title'),
                    'year': item.get('release_date', 'N/A')[:4],
                    'overview': item.get('overview'),
                    'poster': item.get('poster_path'),
                    'trailer_status': trailer_status,
                    'details': media_details
                })
        elif media_type_search == 'tv':
            client = CustomTVDBClient()
            search_results = client.search_and_translate_series(query, lang='fra')
            for item in search_results:
                external_id = item.get('tvdb_id')
                trailer_status = trailer_manager.get_trailer_status('tv', external_id) if external_id else 'NONE'
                media_details = media_info_manager.get_media_details('tv', external_id) if external_id else {}
                results.append({
                    'id': external_id,
                    'title': item.get('name'),
                    'original_title': item.get('original_name'),
                    'year': item.get('year'),
                    'overview': item.get('overview'),
                    'poster': item.get('poster_url'),
                    'trailer_status': trailer_status,
                    'details': media_details
                })
        else:
            return jsonify({"error": "Type de média non supporté."}), 400

        return jsonify(results)

    except Exception as e:
        current_app.logger.error(f"Erreur dans /api/media/search: {e}", exc_info=True)
        return jsonify({"error": f"Erreur serveur lors de la recherche de média : {e}"}), 500

@search_ui_bp.route('/api/prowlarr/search', methods=['POST'])
@login_required
def prowlarr_search():
    data = request.get_json()
    queries = data.get('queries')
    query = data.get('query')

    # Unifier les deux types de requêtes en s'assurant que 'queries' est toujours une liste
    if query:
        queries = [query]

    if not queries:
        return jsonify({"error": "La requête est vide."}), 400

    search_type = data.get('search_type', 'sonarr')

    # 1. Charger les configurations
    filter_options = load_filter_options()
    search_config = load_search_categories()
    category_ids = search_config.get(f"{search_type}_categories", [])

    # 2. On envoie la requête de base à Prowlarr
    all_raw_results = []
    for query in queries:
        raw_results = search_prowlarr(query=query, categories=category_ids)
        if raw_results:
            all_raw_results.extend(raw_results)

    if not all_raw_results:
        return jsonify({"error": "Erreur de communication avec Prowlarr ou aucun résultat."}), 500

    # Dédoublonnage des résultats basé sur le GUID
    unique_results = []
    seen_guids = set()
    for result in all_raw_results:
        guid = result.get('guid')
        if guid and guid not in seen_guids:
            unique_results.append(result)
            seen_guids.add(guid)
    all_raw_results = unique_results

    # 3. Enrichir les résultats en utilisant le nouveau parseur centralisé
    enriched_results = []
    for result in all_raw_results:
        release_title = result.get('title', '')
        parsed_data = parse_release_data(release_title)

        # Fusionner les données parsées avec le résultat original de Prowlarr
        final_result = {**result, **parsed_data}

        # --- Filtre intelligent pour ne garder que les résultats pertinents ---
        if search_type == 'sonarr':
            # Pour les séries, on garde les épisodes, les packs de saison et les collections
            if not (final_result['is_episode'] or final_result['is_season_pack'] or final_result['is_collection']):
                continue
        elif search_type == 'radarr':
            # Pour les films, on garde les collections ou les releases avec une année
            # (pour exclure les épisodes de séries qui pourraient matcher par titre)
            if not (final_result['is_collection'] or final_result['year'] is not None):
                continue

        # Le champ 'is_special' est encore géré ici car il dépend de 'season' et 'episode'
        final_result['is_special'] = (
            final_result['season'] == 0 or
            (isinstance(final_result.get('episode'), int) and final_result.get('episode') > 50 and final_result.get('season') is not None)
        )

        enriched_results.append(final_result)

    # 4. Construire la réponse finale
    response_data = {
        'results': enriched_results,
        'filter_options': filter_options
    }

    return jsonify(response_data)


@search_ui_bp.route('/api/search/lookup', methods=['POST'])
def api_search_lookup():
    data = request.get_json()
    search_term = data.get('term')
    media_type = data.get('media_type')
    media_id = data.get('media_id') # Nouveau champ pour la recherche par ID

    if not media_type or (not search_term and not media_id):
        return jsonify({'error': 'Titre ou ID du média requis.'}), 400

    final_results = []
    clean_title = ""

    # Cas 1: Recherche par ID (prioritaire)
    if media_id:
        current_app.logger.info(f"Recherche par ID: {media_id}, Type: {media_type}")
        # Note: Cette partie nécessite que vos clients Arr puissent chercher par ID externe.
        # On simule un résultat pour l'instant, en attendant d'avoir la bonne fonction.
        # Pour que cela marche, il faudra une fonction comme `get_sonarr_series_by_tvdbid`
        if media_type == 'tv':
            # Simuler une recherche qui retourne un seul item
            api_response = arr_client.search_sonarr_by_title(f"tvdb:{media_id}")
            if api_response: final_results = api_response
        elif media_type == 'movie':
            api_response = arr_client.search_radarr_by_title(f"tmdb:{media_id}")
            if api_response: final_results = api_response

        if final_results:
            final_results[0]['is_best_match'] = True # L'ID est toujours le meilleur résultat
            clean_title = final_results[0].get('title', '')


    # Cas 2: Recherche par Titre
    elif search_term:
        current_app.logger.info(f"Recherche par Titre: {search_term}, Type: {media_type}")
        parsed_info = parse_media_name(search_term)
        clean_title = parsed_info.get('title', search_term).lower()
        year = parsed_info.get('year')

        api_response = []
        if media_type == 'tv':
            api_response = arr_client.search_sonarr_by_title(clean_title)
        elif media_type == 'movie':
            api_response = arr_client.search_radarr_by_title(clean_title)

        if api_response:
            scored_results = []
            for item in api_response:
                item_title = item.get('title', '').lower()
                score = levenshtein_distance(clean_title, item_title)
                if clean_title == item_title: score -= 10
                if year and item.get('year') and year != item.get('year'): score += 20
                scored_results.append({'score': score, 'data': item})

            sorted_results = sorted(scored_results, key=lambda x: x['score'])
            final_results = [result['data'] for result in sorted_results]

            if final_results:
                final_results[0]['is_best_match'] = True

    # Déterminer le format de la réponse
    render_as_html = request.args.get('render_html', 'false').lower() == 'true'

    # Enrichir les résultats avec le statut du trailer
    from app.utils import trailer_manager # Import local
    for item in final_results:
        item_media_type = 'tv' if item.get('tvdbId') else 'movie'
        external_id = item.get('tvdbId') or item.get('tmdbId')
        item['trailer_status'] = trailer_manager.get_trailer_status(item_media_type, external_id) if external_id else 'NONE'

    if render_as_html:
        return render_template(
            'search_ui/_media_result_list.html',
            candidates=final_results,
            media_type=media_type
        )
    else:
        return jsonify({
            'results': final_results,
            'cleaned_query': clean_title or search_term
        })
    
# Dans app/search_ui/__init__.py, remplacez SEULEMENT cette fonction :

@search_ui_bp.route('/api/enrich/details', methods=['POST'])
def enrich_details():
    from app.utils.tvdb_client import CustomTVDBClient
    from app.utils.tmdb_client import TheMovieDBClient
    from flask import current_app

    data = request.get_json()
    media_id = data.get('media_id')
    media_type = data.get('media_type')

    if not media_id or not media_type:
        return jsonify({'error': 'ID ou type de média manquant'}), 400

    try:
        if media_type == 'tv':
            client = CustomTVDBClient()
            details = client.get_series_details_by_id(media_id, lang='fra')
            if not details: return jsonify({'error': 'Série non trouvée'}), 404

            # === LA CORRECTION FINALE ET DÉCISIVE EST ICI ===
            # On ne reconstruit PAS l'URL. On prend celle fournie par la bibliothèque.
            poster_url = details.get('image', '') 
            
            formatted_details = {
                'id': details.get('id'),
                'title': details.get('name') or details.get('seriesName'),
                'year': details.get('year'),
                'overview': details.get('overview'),
                'poster': poster_url,
                'status': details.get('status', {}).get('name', 'Inconnu')
            }
            return jsonify(formatted_details)

        elif media_type == 'movie':
            client = TheMovieDBClient()
            details = client.get_movie_details(media_id, lang='fr-FR')
            if not details: return jsonify({'error': 'Film non trouvé'}), 404

            # On formate la sortie pour qu'elle soit identique à celle des séries
            formatted_details = {
                'id': details.get('id'),
                'title': details.get('title'),
                'year': details.get('year'),
                'overview': details.get('overview'),
                'poster': details.get('poster'), # Le client construit déjà l'URL complète
                'status': details.get('status', 'Inconnu')
            }
            return jsonify(formatted_details)

    except Exception as e:
        current_app.logger.error(f"Erreur dans enrich_details: {e}", exc_info=True)
        return jsonify({'error': f"Erreur serveur : {e}"}), 500

@search_ui_bp.route('/api/media/check_existence', methods=['POST'])
@login_required
def check_media_existence():
    data = request.get_json()
    media_id = data.get('media_id')
    media_type = data.get('media_type')

    if not media_id or not media_type:
        return jsonify({'error': 'ID ou type de média manquant'}), 400

    try:
        media_info = None
        if media_type == 'tv':
            plex_guid = f"tvdb://{media_id}"
            media_info = arr_client.get_sonarr_series_by_guid(plex_guid)
        elif media_type == 'movie':
            plex_guid = f"tmdb:{media_id}"
            media_info = arr_client.get_radarr_movie_by_guid(plex_guid)

        if media_info and media_info.get('id'):
            return jsonify({
                'exists': True,
                'internal_id': media_info.get('id'), # ID interne de Sonarr/Radarr
                'title': media_info.get('title'),
                'path': media_info.get('path')
            })
        else:
            return jsonify({'exists': False})

    except Exception as e:
        current_app.logger.error(f"Erreur dans /api/media/check_existence: {e}", exc_info=True)
        return jsonify({'error': f"Erreur serveur : {e}"}), 500

# NOTE: Les autres routes de l'ancien fichier 'routes.py' comme '/download-and-map', etc.
# doivent aussi être migrées ici en utilisant le même pattern d'imports locaux si elles
# sont toujours utilisées. Pour l'instant, je me concentre sur le strict nécessaire pour
# faire fonctionner la recherche et la modale.

# =====================================================================
# ROUTES ADDITIONNELLES RESTAURÉES
# =====================================================================

@search_ui_bp.route('/check_media_status', methods=['POST'])
@login_required
def check_media_status_api():
    # Imports locaux
    from app.utils.media_status_checker import check_media_status as util_check_media_status

    data = request.json
    title = data.get('title')

    if not title:
        return jsonify({'text': 'Titre manquant', 'status_class': 'text-danger'}), 400

    try:
        # 1. On récupère le dictionnaire complet depuis notre fonction utilitaire
        status_info = util_check_media_status(release_title=title)

        # 2. On prépare le champ 'text' pour les cas simples (compatibilité)
        status_info['text'] = status_info.get('details', status_info.get('status', 'Indéterminé'))
        
        # 3. On s'assure que la classe CSS est présente
        badge_color = status_info.get('badge_color', 'secondary')
        status_class_map = {
            'success': 'text-success', 'warning': 'text-warning',
            'danger': 'text-danger', 'secondary': 'text-body-secondary',
            'dark': 'text-body-secondary'
        }
        status_info['status_class'] = status_class_map.get(badge_color, 'text-body-secondary')

        # 4. On renvoie le dictionnaire ENTIER, qui inclut 'status_details' s'il existe
        return jsonify(status_info)

    except Exception as e:
        current_app.logger.error(f"Erreur API dans /check_media_status pour '{title}': {e}", exc_info=True)
        return jsonify({'text': 'Erreur serveur interne', 'status_class': 'text-danger'}), 500



@search_ui_bp.route('/api/prepare_mapping_details', methods=['POST'])
@login_required
def prepare_mapping_details():
    # Imports locaux
    from app.utils.arr_client import parse_media_name, search_sonarr_by_title, search_radarr_by_title
    # Note: L'utilisation de CustomTVDBClient et TheMovieDBClient est retirée au profit du nouveau système de lazy loading

    data = request.json
    release_title = data.get('title')

    if not release_title:
        return jsonify({'error': 'Titre manquant'}), 400

    parsed_info = parse_media_name(release_title)
    media_type = 'series' if parsed_info['type'] == 'tv' else 'movie'

    candidates = []
    if media_type == 'series':
        candidates = search_sonarr_by_title(parsed_info['title'])
    else: # 'movie'
        candidates = search_radarr_by_title(parsed_info['title'])

    # Ceci retourne la liste des candidats non-enrichis, qui sera enrichie côté client au besoin.
    return render_template('search_ui/_mapping_selection_list.html', candidates=candidates)


def _process_single_release(release_details, final_app_type, final_target_id):
    """
    Traite une seule release: télécharge, ajoute à rTorrent et mappe.
    Retourne (True, message) en cas de succès, (False, message) en cas d'échec.
    """
    import requests
    import urllib.parse
    from pathlib import Path
    from app.utils.rtorrent_client import (
        _decode_bencode_name,
        add_magnet_and_get_hash_robustly,
        add_torrent_data_and_get_hash_robustly
    )
    from app.utils.mapping_manager import add_or_update_torrent_in_map

    logger = current_app.logger
    release_name_original = release_details.get('releaseName')
    download_link = release_details.get('downloadLink')
    indexer_id = release_details.get('indexerId')
    guid = release_details.get('guid')

    logger.info(f"Début du traitement pour la release: '{release_name_original}'")

    try:
        # 1. Déterminer le label et le chemin de destination
        if final_app_type == 'sonarr':
            rtorrent_label = current_app.config.get('RTORRENT_LABEL_SONARR')
            rtorrent_download_dir = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_SONARR_PATH')
        else:
            rtorrent_label = current_app.config.get('RTORRENT_LABEL_RADARR')
            rtorrent_download_dir = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_RADARR_PATH')

        if not rtorrent_label or not rtorrent_download_dir:
            return False, f"Config rTorrent manquante pour {final_app_type}."

        # 2. Ajouter le torrent et obtenir le hash
        actual_hash = None
        release_name_for_map = release_name_original

        if download_link.startswith('magnet:'):
            actual_hash = add_magnet_and_get_hash_robustly(
                magnet_link=download_link,
                label=rtorrent_label,
                destination_path=rtorrent_download_dir
            )
            parsed_magnet = urllib.parse.parse_qs(urllib.parse.urlparse(download_link).query)
            display_names = parsed_magnet.get('dn')
            if display_names and display_names[0]:
                release_name_for_map = display_names[0].strip()
        else: # Fichier .torrent
            try:
                proxy_url = url_for('search_ui.download_torrent_proxy', _external=True)
                params = {'url': download_link, 'release_name': release_name_original, 'indexer_id': indexer_id, 'guid': guid}
                session_cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
                cookies = {session_cookie_name: request.cookies.get(session_cookie_name)}
                response = requests.get(proxy_url, params=params, cookies=cookies, timeout=60)
                response.raise_for_status()
                torrent_content_bytes = response.content
            except requests.exceptions.HTTPError as e:
                # Si le proxy a renvoyé une erreur (ex: cookie invalide), on la propage
                error_message_from_proxy = e.response.text
                logger.error(f"Erreur du proxy de téléchargement pour '{release_name_original}': {error_message_from_proxy}")
                return False, error_message_from_proxy
            
            release_name_for_map = _decode_bencode_name(torrent_content_bytes) or release_name_original.replace('.torrent', '').strip()
            actual_hash = add_torrent_data_and_get_hash_robustly(
                torrent_content_bytes=torrent_content_bytes,
                filename_for_rtorrent=f"{release_name_original}.torrent",
                label=rtorrent_label,
                destination_path=rtorrent_download_dir
            )

        # 3. Gérer le résultat
        if actual_hash:
            logger.info(f"Torrent '{release_name_for_map}' ajouté. Hash: {actual_hash}. Sauvegarde de l'association.")
            folder_name = release_name_for_map
            add_or_update_torrent_in_map(
                release_name=release_name_for_map,
                torrent_hash=actual_hash,
                status='pending_download',
                seedbox_download_path=None,
                folder_name=folder_name,
                app_type=final_app_type,
                target_id=final_target_id,
                label=rtorrent_label,
                original_torrent_name=release_name_original
            )
            return True, f"Torrent '{release_name_original}' ajouté et mappé avec succès."
        else:
            msg = f"Torrent '{release_name_original}' ajouté, mais son hash n'a pas pu être récupéré. Mapping échoué."
            logger.warning(msg)
            return False, msg

    except Exception as e:
        logger.error(f"Erreur dans _process_single_release pour '{release_name_original}': {e}", exc_info=True)
        return False, f"Erreur serveur inattendue pour '{release_name_original}': {str(e)}"

@search_ui_bp.route('/download-and-map', methods=['POST'])
@login_required
def download_and_map():
    logger = current_app.logger
    data = request.get_json()

    instance_type = data.get('instanceType')
    media_id = data.get('mediaId')

    if not all([data.get('releaseName'), data.get('downloadLink'), instance_type, media_id]):
        return jsonify({'status': 'error', 'message': 'Données manquantes.'}), 400

    # Logique pour déterminer le type final et l'ID interne (inchangée)
    final_app_type = None
    final_target_id = str(media_id)
    series_info = arr_client.get_sonarr_series_by_guid(f"tvdb://{media_id}")
    if series_info and series_info.get('id'):
        final_app_type = 'sonarr'
        final_target_id = str(series_info.get('id'))
    else:
        movie_info = arr_client.get_radarr_movie_by_guid(f"tmdb:{media_id}")
        if movie_info and movie_info.get('id'):
            final_app_type = 'radarr'
            final_target_id = str(movie_info.get('id'))
    if not final_app_type:
        final_app_type = 'sonarr' if instance_type == 'tv' else 'radarr'

    success, message = _process_single_release(data, final_app_type, final_target_id)

    if success:
        return jsonify({'status': 'success', 'message': message})
    else:
        return jsonify({'status': 'error', 'message': message}), 500

@search_ui_bp.route('/batch-download-and-map', methods=['POST'])
@login_required
def batch_download_and_map():
    logger = current_app.logger
    data = request.get_json()

    releases = data.get('releases')
    instance_type = data.get('instanceType')
    media_id = data.get('mediaId')

    if not all([releases, instance_type, media_id]):
        return jsonify({'status': 'error', 'message': 'Données manquantes (releases, instanceType ou mediaId).'}), 400

    # Déterminer le type final et l'ID interne une seule fois pour tout le lot
    final_app_type = None
    final_target_id = str(media_id)
    series_info = arr_client.get_sonarr_series_by_guid(f"tvdb://{media_id}")
    if series_info and series_info.get('id'):
        final_app_type = 'sonarr'
        final_target_id = str(series_info.get('id'))
    else:
        movie_info = arr_client.get_radarr_movie_by_guid(f"tmdb:{media_id}")
        if movie_info and movie_info.get('id'):
            final_app_type = 'radarr'
            final_target_id = str(movie_info.get('id'))
    if not final_app_type:
        final_app_type = 'sonarr' if instance_type == 'tv' else 'radarr'

    processed_count = 0
    for release in releases:
        # La fonction _process_single_release attend un dictionnaire avec des clés spécifiques
        release_details_for_processing = {
            'releaseName': release.get('releaseName'),
            'downloadLink': release.get('downloadLink'),
            'indexerId': release.get('indexerId'),
            'guid': release.get('guid')
        }
        success, message = _process_single_release(release_details_for_processing, final_app_type, final_target_id)
        if not success:
            # Arrêt à la première erreur
            error_message = f"Échec du lot après {processed_count} succès. Erreur sur '{release.get('releaseName')}': {message}"
            logger.error(error_message)
            return jsonify({'status': 'error', 'message': error_message}), 500
        processed_count += 1

    success_message = f"{processed_count} releases ont été ajoutées et mappées avec succès."
    logger.info(success_message)
    return jsonify({'status': 'success', 'message': success_message})

# =====================================================================
# ROUTES DE PROXY DE TÉLÉCHARGEMENT RESTAURÉES
# =====================================================================

@search_ui_bp.route('/download_torrent_proxy')
@login_required
def download_torrent_proxy():
    # Imports locaux
    import requests

    url = request.args.get('url')
    release_name = request.args.get('release_name', 'download.torrent')
    indexer_id = request.args.get('indexer_id')
    guid = request.args.get('guid')

    if not all([url, release_name, indexer_id, guid]):
        current_app.logger.error(f"Proxy download: Paramètres manquants.")
        return Response("Erreur: Paramètres manquants.", status=400)

    ygg_indexer_id = current_app.config.get('YGG_INDEXER_ID')
    final_filename = f"{release_name.replace(' ', '_')}.torrent"

    try:
        if str(ygg_indexer_id) == str(indexer_id):
            from app.utils.cookie_manager import get_ygg_cookie_status
            cookie_status = get_ygg_cookie_status()

            if not cookie_status["is_valid"]:
                error_message = f"Cookie YGG invalide ou expiré. Message : {cookie_status.get('status_message', 'Veuillez le mettre à jour.')}"
                current_app.logger.warning(f"Proxy download: {error_message}")
                return Response(error_message, status=400)

            ygg_user_agent = current_app.config.get('YGG_USER_AGENT')
            ygg_base_url = current_app.config.get('YGG_BASE_URL')

            if not all([ygg_user_agent, ygg_base_url]):
                raise ValueError("Configuration YGG (USER_AGENT, BASE_URL) manquante.")

            release_id_ygg = guid.split('?id=')[1].split('&')[0]
            final_ygg_download_url = f"{ygg_base_url.rstrip('/')}/engine/download_torrent?id={release_id_ygg}"
            headers = {'User-Agent': ygg_user_agent, 'Cookie': cookie_status["cookie_string"]}
            response = requests.get(final_ygg_download_url, headers=headers, timeout=45, allow_redirects=True)
        else:
            standard_user_agent = current_app.config.get('YGG_USER_AGENT', 'Mozilla/5.0')
            headers = {'User-Agent': standard_user_agent}
            response = requests.get(url, headers=headers, timeout=45, allow_redirects=True)

        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        if 'application/x-bittorrent' not in content_type and 'application/octet-stream' not in content_type:
            raise ValueError(f"La réponse n'est pas un fichier .torrent valide. Content-Type: '{content_type}'.")

        return Response(
            response.content,
            mimetype='application/x-bittorrent',
            headers={'Content-Disposition': f'attachment;filename="{final_filename}"'}
        )
    except Exception as e:
        current_app.logger.error(f"Proxy download: Erreur pour '{release_name}': {e}", exc_info=True)
        return Response(f"Une erreur est survenue lors du proxy de téléchargement: {e}", status=500)

@search_ui_bp.route('/api/add/manual', methods=['POST'])
@login_required
def manual_add_media():
    data = request.get_json()
    media_id = data.get('media_id')
    media_type = data.get('media_type') # 'tv' ou 'movie'
    title = data.get('title', '') # Titre optionnel

    if not media_id or not media_type:
        return jsonify({'status': 'error', 'message': 'ID du média ou type manquant.'}), 400

    try:
        # Récupérer les configurations par défaut
        if media_type == 'tv':
            root_folder = current_app.config.get('DEFAULT_SONARR_ROOT_FOLDER')
            profile_id = current_app.config.get('DEFAULT_SONARR_PROFILE_ID')
            lang_profile_id = current_app.config.get('DEFAULT_SONARR_LANGUAGE_PROFILE_ID')
            if not all([root_folder, profile_id, lang_profile_id]):
                raise ValueError("Configuration Sonarr par défaut manquante.")

            # Ajoute la série via son TVDB ID
            added_item = arr_client.add_new_series_to_sonarr(
                tvdb_id=int(media_id),
                title=title, # Le titre est surtout pour le log, Sonarr se base sur l'ID
                quality_profile_id=profile_id,
                language_profile_id=lang_profile_id,
                root_folder_path=root_folder
            )

        elif media_type == 'movie':
            root_folder = current_app.config.get('DEFAULT_RADARR_ROOT_FOLDER')
            profile_id = current_app.config.get('DEFAULT_RADARR_PROFILE_ID')
            if not all([root_folder, profile_id]):
                raise ValueError("Configuration Radarr par défaut manquante.")

            # Ajoute le film via son TMDb ID
            added_item = arr_client.add_new_movie_to_radarr(
                tmdb_id=int(media_id),
                title=title,
                quality_profile_id=profile_id,
                root_folder_path=root_folder
            )
        else:
             return jsonify({'status': 'error', 'message': 'Type de média non supporté.'}), 400

        if added_item and added_item.get('id'):
            return jsonify({
                'status': 'success',
                'message': f"'{added_item.get('title')}' ajouté avec succès à {media_type.capitalize()}!",
                'added_item': added_item
            })
        else:
            raise Exception("L'ajout a échoué. Réponse invalide de l'API Arr.")

    except Exception as e:
        current_app.logger.error(f"Erreur durant l'ajout manuel: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

@search_ui_bp.route('/api/add_to_arr', methods=['POST'])
@login_required
def add_to_arr():
    data = request.get_json()
    media_type = data.get('media_type')
    media_id = data.get('id')
    search_on_add = data.get('search_on_add', False)

    if not media_type or not media_id:
        return jsonify({'success': False, 'message': 'Type de média ou ID manquant.'}), 400

    try:
        if media_type == 'tv':
            from app.utils.tvdb_client import CustomTVDBClient
            tvdb_client = CustomTVDBClient()
            series_details = tvdb_client.get_series_details_by_id(media_id)
            if not series_details:
                return jsonify({'success': False, 'message': f"Impossible de trouver les détails pour la série TVDB ID: {media_id}"}), 404

            title = series_details.get('seriesName') or series_details.get('name')

            root_folder_path = current_app.config.get('DEFAULT_SONARR_ROOT_FOLDER')
            quality_profile_id = current_app.config.get('DEFAULT_SONARR_PROFILE_ID')
            language_profile_id = current_app.config.get('DEFAULT_SONARR_LANGUAGE_PROFILE_ID')

            if not all([root_folder_path, quality_profile_id, language_profile_id]):
                 return jsonify({'success': False, 'message': 'Configuration Sonarr par défaut manquante.'}), 500

            added_series = arr_client.add_new_series_to_sonarr(
                tvdb_id=int(media_id),
                title=title,
                quality_profile_id=int(quality_profile_id),
                language_profile_id=int(language_profile_id),
                root_folder_path=root_folder_path,
                search_for_missing_episodes=search_on_add
            )
            if added_series and added_series.get('id'):
                return jsonify({'success': True, 'message': f"Série '{title}' ajoutée avec succès."})
            else:
                return jsonify({'success': False, 'message': f"Échec de l'ajout de la série '{title}' à Sonarr."})

        elif media_type == 'movie':
            from app.utils.tmdb_client import TheMovieDBClient
            tmdb_client = TheMovieDBClient()
            movie_details = tmdb_client.get_movie_details(media_id)
            if not movie_details:
                return jsonify({'success': False, 'message': f"Impossible de trouver les détails pour le film TMDB ID: {media_id}"}), 404

            title = movie_details.get('title')

            root_folder_path = current_app.config.get('DEFAULT_RADARR_ROOT_FOLDER')
            quality_profile_id = current_app.config.get('DEFAULT_RADARR_PROFILE_ID')

            if not all([root_folder_path, quality_profile_id]):
                 return jsonify({'success': False, 'message': 'Configuration Radarr par défaut manquante.'}), 500

            added_movie = arr_client.add_new_movie_to_radarr(
                tmdb_id=int(media_id),
                title=title,
                quality_profile_id=int(quality_profile_id),
                root_folder_path=root_folder_path,
                search_for_movie=search_on_add
            )
            if added_movie and added_movie.get('id'):
                return jsonify({'success': True, 'message': f"Film '{title}' ajouté avec succès."})
            else:
                return jsonify({'success': False, 'message': f"Échec de l'ajout du film '{title}' à Radarr."})

        else:
            return jsonify({'success': False, 'message': f"Type de média inconnu: {media_type}"}), 400

    except Exception as e:
        current_app.logger.error(f"Erreur dans add_to_arr: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@search_ui_bp.route('/api/media/get_details', methods=['GET'])
@login_required
def get_media_details():
    """Récupère les détails enrichis pour un seul média."""
    from app.utils.media_info_manager import media_info_manager

    media_type = request.args.get('media_type')
    external_id = request.args.get('external_id')

    if not media_type or not external_id:
        return jsonify({"error": "Paramètres media_type et external_id requis."}), 400

    try:
        details = media_info_manager.get_media_details(media_type, int(external_id))
        return jsonify(details)
    except Exception as e:
        current_app.logger.error(f"Erreur dans /api/media/get_details: {e}", exc_info=True)
        return jsonify({"error": f"Erreur serveur : {e}"}), 500


@search_ui_bp.route('/api/media/add_direct', methods=['POST'])
@login_required
def add_media_direct():
    """Ajoute un média à Sonarr/Radarr sans déclencher de recherche de torrent."""
    data = request.get_json()
    media_type = data.get('media_type')
    external_id = data.get('external_id')
    root_folder_path = data.get('root_folder_path')
    quality_profile_id = data.get('quality_profile_id')
    language_profile_id = data.get('language_profile_id') # Spécifique à Sonarr

    if not all([media_type, external_id, root_folder_path, quality_profile_id]):
        return jsonify({'success': False, 'message': 'Données manquantes.'}), 400

    try:
        item_title = "N/A"
        if media_type == 'tv':
            if not language_profile_id:
                return jsonify({'success': False, 'message': 'Profil de langue manquant pour Sonarr.'}), 400

            # Récupérer le titre canonique depuis TVDB pour la cohérence
            client = CustomTVDBClient()
            series_details = client.get_series_details_by_id(external_id, lang='fra')
            item_title = series_details.get('name') if series_details else 'Titre inconnu'

            added_item = arr_client.add_new_series_to_sonarr(
                tvdb_id=int(external_id),
                title=item_title,
                quality_profile_id=int(quality_profile_id),
                language_profile_id=int(language_profile_id),
                root_folder_path=root_folder_path,
                search_for_missing_episodes=False # Exigence clé
            )

        elif media_type == 'movie':
            # Récupérer le titre canonique depuis TMDB
            client = TheMovieDBClient()
            movie_details = client.get_movie_details(external_id, lang='fr-FR')
            item_title = movie_details.get('title') if movie_details else 'Titre inconnu'

            added_item = arr_client.add_new_movie_to_radarr(
                tmdb_id=int(external_id),
                title=item_title,
                quality_profile_id=int(quality_profile_id),
                root_folder_path=root_folder_path,
                search_for_movie=False # Exigence clé
            )

        else:
            return jsonify({'success': False, 'message': 'Type de média non supporté.'}), 400

        if added_item and added_item.get('id'):
            return jsonify({
                'success': True,
                'message': f"'{item_title}' a été ajouté avec succès à {media_type.capitalize()}."
            })
        else:
            return jsonify({
                'success': False,
                'message': f"Échec de l'ajout de '{item_title}' à {media_type.capitalize()}. Vérifiez les logs."
            }), 500

    except Exception as e:
        current_app.logger.error(f"Erreur dans /api/media/add_direct: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f"Erreur serveur: {str(e)}"}), 500
