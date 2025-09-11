from flask import request, jsonify, current_app, session
from . import agent_bp
from app.agent.services import generate_youtube_queries, score_and_sort_results
from app.utils.trailer_finder import find_youtube_trailer, get_videos_details
from app.agent.cache_manager import get_from_cache, set_in_cache, lock_trailer_in_cache, unlock_trailer_in_cache
from app.utils.plex_client import get_user_specific_plex_server_from_id
from app.utils.tmdb_client import TheMovieDBClient
from app.utils.tvdb_client import CustomTVDBClient

def get_actual_title(plex_item):
    """Tente de trouver le titre réel via les GUIDs et les API externes."""
    if plex_item.type == 'movie':
        tmdb_id = next((g.id.replace('tmdb://', '') for g in plex_item.guids if g.id.startswith('tmdb://')), None)
        if tmdb_id:
            tmdb_client = TheMovieDBClient()
            movie_details = tmdb_client.get_movie_details(tmdb_id)
            if movie_details and movie_details.get('title'):
                return movie_details['title']
    elif plex_item.type == 'show':
        tvdb_id = next((g.id.replace('tvdb://', '') for g in plex_item.guids if g.id.startswith('tvdb://')), None)
        if tvdb_id:
            tvdb_client = CustomTVDBClient()
            series_details = tvdb_client.get_series_details_by_id(tvdb_id)
            if series_details and series_details.get('name'):
                return series_details['name']
    return plex_item.title # Fallback sur le titre de Plex

def _search_and_score_trailers(title, year, media_type):
    """Helper function to search and score trailers, used by multiple routes."""
    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')
    if not youtube_api_key:
        return {'success': False, 'error': "La clé API YouTube n'est pas configurée."}

    search_queries = generate_youtube_queries(title, year, media_type)
    current_app.logger.debug(f"Generated search queries: {search_queries}")

    all_results = []
    seen_video_ids = set()
    first_successful_query = None
    first_next_page_token = None

    for current_query in search_queries:
        search_result = find_youtube_trailer(current_query, youtube_api_key)
        if search_result and search_result['results']:
            if not first_successful_query:
                first_successful_query = current_query
                first_next_page_token = search_result.get('nextPageToken')
            for result in search_result['results']:
                if result['videoId'] not in seen_video_ids:
                    all_results.append(result)
                    seen_video_ids.add(result['videoId'])

    if not all_results:
        return {'success': False, 'error': 'Aucun résultat trouvé pour les requêtes générées.'}

    sorted_by_title = score_and_sort_results(all_results, title, year, media_type)

    top_ids = [res['videoId'] for res in sorted_by_title[:15]]
    if top_ids:
        video_details = get_videos_details(top_ids, youtube_api_key)
        final_sorted_list = score_and_sort_results(sorted_by_title, title, year, media_type, video_details=video_details)
    else:
        final_sorted_list = sorted_by_title

    top_results = final_sorted_list[:10]
    log_results = [{'title': r['title'], 'channel': r['channel'], 'score': r['score']} for r in top_results]
    current_app.logger.debug(f"Top 10 final results: {log_results}")

    response_data = {
        'results': top_results,
        'nextPageToken': first_next_page_token,
        'query': first_successful_query
    }
    return {'success': True, **response_data}

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json

    # Handle pagination separately as it's stateless
    page_token = data.get('page_token')
    if page_token:
        query = data.get('query')
        youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')
        search_result = find_youtube_trailer(query, youtube_api_key, page_token=page_token)
        return jsonify({'success': True, 'results': search_result.get('results', []), 'nextPageToken': search_result.get('nextPageToken'), 'query': query})

    # Main logic: either use Plex item context or just search terms
    ratingKey = data.get('ratingKey')
    original_title = data.get('title')
    year = data.get('year')
    media_type = data.get('media_type')
    user_id = data.get('userId')

    if not all([original_title, year, media_type]):
        return jsonify({'success': False, 'error': 'Données manquantes (title, year, media_type)'}), 400

    # If a ratingKey is provided, we can use Plex-specific features (caching, real title)
    if ratingKey and user_id:
        cache_key = f"trailer_search_{original_title}_{year}_{ratingKey}"
        cached_result = get_from_cache(cache_key)
        if cached_result:
            current_app.logger.info(f"Cache HIT for trailer search: '{original_title}'")
            return jsonify({'success': True, **cached_result})

        try:
            plex_server = get_user_specific_plex_server_from_id(user_id)
            if not plex_server:
                return jsonify({'success': False, 'error': "Impossible d'établir la connexion au serveur Plex."}), 500
            plex_item = plex_server.fetchItem(int(ratingKey))
            search_title = get_actual_title(plex_item)
            current_app.logger.debug(f"Suggest Trailer: Original title='{original_title}', Found actual title='{search_title}'")
        except Exception as e:
            current_app.logger.error(f"Erreur lors de la récupération du titre réel pour ratingKey {ratingKey}: {e}", exc_info=True)
            search_title = original_title
    else:
        # If no ratingKey, we're likely on the search page. No caching, use the title directly.
        search_title = original_title

    results = _search_and_score_trailers(search_title, year, media_type)

    if not results.get('success'):
        return jsonify(results), 500

    # Cache the results only if we have a ratingKey
    if ratingKey:
        set_in_cache(cache_key, results)

    return jsonify(results)

@agent_bp.route('/lock_trailer', methods=['POST'])
def lock_trailer_route():
    data = request.json
    ratingKey = data.get('ratingKey')
    title = data.get('title')
    year = data.get('year')
    video_id = data.get('videoId')

    if not all([ratingKey, title, year, video_id]):
        return jsonify({'success': False, 'error': 'Données manquantes (ratingKey, title, year, videoId)'}), 400

    cache_key = f"trailer_search_{title}_{year}_{ratingKey}"

    success = lock_trailer_in_cache(cache_key, video_id, title)

    if success:
        return jsonify({'success': True, 'message': f'Bande-annonce pour {title} verrouillée avec succès.'})
    else:
        return jsonify({'success': False, 'error': 'Impossible de trouver l\'entrée de cache à verrouiller.'}), 404

@agent_bp.route('/unlock_trailer', methods=['POST'])
def unlock_trailer_route():
    data = request.json
    ratingKey = data.get('ratingKey')
    title = data.get('title')
    year = data.get('year')

    if not all([ratingKey, title, year]):
        return jsonify({'success': False, 'error': 'Données manquantes (ratingKey, title, year)'}), 400

    cache_key = f"trailer_search_{title}_{year}_{ratingKey}"

    success = unlock_trailer_in_cache(cache_key)

    if success:
        return jsonify({'success': True, 'message': f'Verrouillage de la bande-annonce pour {title} retiré.'})
    else:
        return jsonify({'success': False, 'error': 'Impossible de trouver l\'entrée de cache à déverrouiller.'}), 404

@agent_bp.route('/custom_trailer_search', methods=['POST'])
def custom_trailer_search():
    data = request.json
    query = data.get('query')
    title = data.get('title') # Le titre original pour le scoring
    year = data.get('year')
    media_type = data.get('media_type')
    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')

    if not all([query, title, media_type]):
        return jsonify({'success': False, 'error': 'Données manquantes (query, title, media_type)'}), 400

    search_result = find_youtube_trailer(query, youtube_api_key)

    if not search_result or not search_result['results']:
        return jsonify({'success': True, 'results': []}) # Retourner succès avec une liste vide

    # On score les résultats par rapport au titre original, pas forcément par rapport à la query
    sorted_results = score_and_sort_results(search_result['results'], title, year, media_type)

    return jsonify({'success': True, 'results': sorted_results, 'nextPageToken': search_result.get('nextPageToken'), 'query': query})
