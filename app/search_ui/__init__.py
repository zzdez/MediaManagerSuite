# app/search_ui/__init__.py

import logging
from flask import Blueprint, render_template, request, flash, jsonify, Response, stream_with_context, current_app, url_for
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
import time
import urllib.parse

# 1. Définition du Blueprint
search_ui_bp = Blueprint('search_ui', __name__, template_folder='templates', static_folder='static')

# 2. Routes
@search_ui_bp.route('/', methods=['GET'])
@login_required
def search_page():
    return render_template('search_ui/search.html')

# --- Fonctions Helper ---

def _determine_media_identity(media_id, instance_type):
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
    return final_app_type, final_target_id

def _process_single_release(release_details, final_app_type, final_target_id):
    import requests
    from app.utils.rtorrent_client import add_magnet_httprpc, add_torrent_file_httprpc, get_torrent_hash_by_name, _decode_bencode_name
    from app.utils.mapping_manager import add_or_update_torrent_in_map

    logger = current_app.logger
    release_name = release_details.get('releaseName')
    download_link = release_details.get('downloadLink')
    indexer_id = release_details.get('indexerId')
    guid = release_details.get('guid')

    try:
        if final_app_type == 'sonarr':
            rtorrent_label = current_app.config.get('RTORRENT_LABEL_SONARR')
            rtorrent_download_dir = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_SONARR_PATH')
        else:
            rtorrent_label = current_app.config.get('RTORRENT_LABEL_RADARR')
            rtorrent_download_dir = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_RADARR_PATH')

        release_name_for_map = release_name
        success_add, error_add = False, "Not initiated"

        if download_link.startswith('magnet:'):
            parsed_magnet = urllib.parse.parse_qs(urllib.parse.urlparse(download_link).query)
            if parsed_magnet.get('dn'): release_name_for_map = parsed_magnet.get('dn')[0]
            success_add, error_add = add_magnet_httprpc(download_link, rtorrent_label, rtorrent_download_dir)
        else:
            proxy_url = url_for('search_ui.download_torrent_proxy', _external=True)
            params = {'url': download_link, 'release_name': release_name, 'indexer_id': indexer_id, 'guid': guid}
            session_cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
            cookies = {session_cookie_name: request.cookies.get(session_cookie_name)}
            response = requests.get(proxy_url, params=params, cookies=cookies, timeout=60)
            response.raise_for_status()
            torrent_content = response.content
            decoded_name = _decode_bencode_name(torrent_content)
            if decoded_name: release_name_for_map = decoded_name
            success_add, error_add = add_torrent_file_httprpc(torrent_content, f"{release_name}.torrent", rtorrent_label, rtorrent_download_dir)

        if not success_add:
            return False, f"Échec de l'ajout à rTorrent: {error_add}"

        actual_hash = get_torrent_hash_by_name(release_name_for_map)
        if not actual_hash:
            return False, f"Torrent '{release_name_for_map}' ajouté, mais son hash n'a pas pu être récupéré."

        add_or_update_torrent_in_map(release_name=release_name_for_map, torrent_hash=actual_hash, status='pending_download', app_type=final_app_type, target_id=final_target_id, label=rtorrent_label, original_torrent_name=release_name)
        return True, f"Torrent '{release_name}' ajouté et mappé."

    except Exception as e:
        logger.error(f"Erreur dans _process_single_release pour '{release_name}': {e}", exc_info=True)
        return False, str(e)


# --- API Routes ---

@search_ui_bp.route('/api/media/search', methods=['POST'])
@login_required
def media_search():
    from app.utils import trailer_manager
    data = request.get_json()
    query, media_type_search = data.get('query'), data.get('media_type', 'movie')
    if not query: return jsonify({"error": "La requête est vide."}), 400
    try:
        results = []
        if media_type_search == 'movie':
            client = TheMovieDBClient()
            for item in client.search_movie(query, lang='fr-FR'):
                external_id = item.get('id')
                results.append({'id': external_id, 'title': item.get('title'), 'year': item.get('release_date', 'N/A')[:4], 'overview': item.get('overview'), 'poster': item.get('poster_path'), 'trailer_status': trailer_manager.get_trailer_status('movie', external_id) if external_id else 'NONE'})
        elif media_type_search == 'tv':
            client = CustomTVDBClient()
            for item in client.search_and_translate_series(query, lang='fra'):
                external_id = item.get('tvdb_id')
                results.append({'id': external_id, 'title': item.get('name'), 'year': item.get('year'), 'overview': item.get('overview'), 'poster': item.get('poster_url'), 'trailer_status': trailer_manager.get_trailer_status('tv', external_id) if external_id else 'NONE'})
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": f"Erreur serveur: {e}"}), 500

@search_ui_bp.route('/api/prowlarr/search', methods=['POST'])
@login_required
def prowlarr_search():
    data = request.get_json()
    query = data.get('query')
    if not query: return jsonify({"error": "La requête est vide."}), 400
    search_type = data.get('search_type', 'sonarr')
    filter_options, search_config = load_filter_options(), load_search_categories()
    category_ids = search_config.get(f"{search_type}_categories", [])
    raw_results = search_prowlarr(query=query, categories=category_ids)
    if raw_results is None: return jsonify({"error": "Erreur avec Prowlarr."}), 500
    enriched_results = []
    for result in raw_results:
        parsed_data = parse_release_data(result.get('title', ''))
        final_result = {**result, **parsed_data}
        if (search_type == 'sonarr' and (final_result['is_episode'] or final_result['is_season_pack'] or final_result['is_collection'])) or \
           (search_type == 'radarr' and (final_result['is_collection'] or final_result['year'] is not None)):
            enriched_results.append(final_result)
    return jsonify({'results': enriched_results, 'filter_options': filter_options})

@search_ui_bp.route('/api/search/lookup', methods=['POST'])
def api_search_lookup():
    data, media_type, final_results, clean_title = request.get_json(), data.get('media_type'), [], ""
    if not media_type or (not data.get('term') and not data.get('media_id')): return jsonify({'error': 'Titre ou ID requis.'}), 400
    if data.get('media_id'):
        api_response = arr_client.search_sonarr_by_title(f"tvdb:{data.get('media_id')}") if media_type == 'tv' else arr_client.search_radarr_by_title(f"tmdb:{data.get('media_id')}")
        if api_response: final_results, final_results[0]['is_best_match'], clean_title = api_response, True, api_response[0].get('title', '')
    elif data.get('term'):
        parsed_info = parse_media_name(data.get('term'))
        clean_title, year = parsed_info.get('title', data.get('term')).lower(), parsed_info.get('year')
        api_response = arr_client.search_sonarr_by_title(clean_title) if media_type == 'tv' else arr_client.search_radarr_by_title(clean_title)
        if api_response:
            scored_results = sorted([{'score': levenshtein_distance(clean_title, item.get('title', '').lower()) - (10 if clean_title == item.get('title', '').lower() else 0) + (20 if year and item.get('year') and year != item.get('year') else 0), 'data': item} for item in api_response], key=lambda x: x['score'])
            final_results = [result['data'] for result in scored_results]
            if final_results: final_results[0]['is_best_match'] = True
    from app.utils import trailer_manager
    for item in final_results:
        item_media_type = 'tv' if item.get('tvdbId') else 'movie'
        item['trailer_status'] = trailer_manager.get_trailer_status(item_media_type, item.get('tvdbId') or item.get('tmdbId'))
    return jsonify({'results': final_results, 'cleaned_query': clean_title or data.get('term')})

@search_ui_bp.route('/api/enrich/details', methods=['POST'])
def enrich_details():
    data = request.get_json()
    media_id, media_type = data.get('media_id'), data.get('media_type')
    if not media_id or not media_type: return jsonify({'error': 'ID ou type manquant'}), 400
    try:
        if media_type == 'tv':
            details = CustomTVDBClient().get_series_details_by_id(media_id, lang='fra')
            if not details: return jsonify({'error': 'Série non trouvée'}), 404
            return jsonify({'id': details.get('id'), 'title': details.get('name') or details.get('seriesName'), 'year': details.get('year'), 'overview': details.get('overview'), 'poster': details.get('image', ''), 'status': details.get('status', {}).get('name', 'Inconnu')})
        elif media_type == 'movie':
            details = TheMovieDBClient().get_movie_details(media_id, lang='fr-FR')
            if not details: return jsonify({'error': 'Film non trouvé'}), 404
            return jsonify({'id': details.get('id'), 'title': details.get('title'), 'year': details.get('year'), 'overview': details.get('overview'), 'poster': details.get('poster'), 'status': details.get('status', 'Inconnu')})
    except Exception as e:
        return jsonify({'error': f"Erreur serveur : {e}"}), 500

@search_ui_bp.route('/download-and-map', methods=['POST'])
@login_required
def download_and_map():
    data = request.get_json()
    if not all([data.get('releaseName'), data.get('downloadLink'), data.get('instanceType'), data.get('mediaId')]):
        return jsonify({'status': 'error', 'message': 'Données manquantes.'}), 400
    final_app_type, final_target_id = _determine_media_identity(data.get('mediaId'), data.get('instanceType'))
    success, message = _process_single_release(data, final_app_type, final_target_id)
    return jsonify({'status': 'success' if success else 'error', 'message': message})

@search_ui_bp.route('/batch-download-and-map', methods=['POST'])
@login_required
def batch_download_and_map():
    data = request.get_json()
    releases, instance_type, media_id = data.get('releases'), data.get('instanceType'), data.get('mediaId')
    if not all([releases, instance_type, media_id]):
        return jsonify({'status': 'error', 'message': 'Données manquantes.'}), 400
    final_app_type, final_target_id = _determine_media_identity(media_id, instance_type)
    processed_count = 0
    for release in releases:
        success, message = _process_single_release(release, final_app_type, final_target_id)
        if not success:
            return jsonify({'status': 'error', 'message': f"Échec du lot après {processed_count} succès. Erreur sur '{release.get('releaseName')}': {message}"}), 500
        processed_count += 1
        time.sleep(1)
    return jsonify({'status': 'success', 'message': f"{processed_count} releases ajoutées avec succès."})

@search_ui_bp.route('/download_torrent_proxy')
@login_required
def download_torrent_proxy():
    import requests
    from app.utils.cookie_manager import get_ygg_cookie_status
    url, release_name, indexer_id, guid = request.args.get('url'), request.args.get('release_name', 'download.torrent'), request.args.get('indexer_id'), request.args.get('guid')
    if not all([url, release_name, indexer_id, guid]):
        return jsonify({'status': 'error', 'message': 'Paramètres manquants.'}), 400
    try:
        if str(current_app.config.get('YGG_INDEXER_ID')) == str(indexer_id):
            cookie_status = get_ygg_cookie_status()
            if not cookie_status["is_valid"]:
                return jsonify({'status': 'error', 'message': f"Cookie YGG invalide : {cookie_status.get('status_message')}"}), 400
            ygg_user_agent, ygg_base_url = current_app.config.get('YGG_USER_AGENT'), current_app.config.get('YGG_BASE_URL')
            if not all([ygg_user_agent, ygg_base_url]): raise ValueError("Config YGG manquante.")
            final_ygg_download_url = f"{ygg_base_url.rstrip('/')}/engine/download_torrent?id={guid.split('?id=')[1].split('&')[0]}"
            headers = {'User-Agent': ygg_user_agent, 'Cookie': cookie_status["cookie_string"]}
            response = requests.get(final_ygg_download_url, headers=headers, timeout=45, allow_redirects=True)
        else:
            headers = {'User-Agent': current_app.config.get('YGG_USER_AGENT', 'Mozilla/5.0')}
            response = requests.get(url, headers=headers, timeout=45, allow_redirects=True)
        response.raise_for_status()
        if 'application/x-bittorrent' not in response.headers.get('Content-Type', '').lower():
            raise ValueError("La réponse n'est pas un fichier .torrent valide.")
        return Response(response.content, mimetype='application/x-bittorrent', headers={'Content-Disposition': f'attachment;filename="{release_name}.torrent"'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Erreur interne du proxy : {e}"}), 500
