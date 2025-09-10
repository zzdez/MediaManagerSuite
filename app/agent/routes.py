from flask import request, jsonify, current_app, session
from . import agent_bp
from app.agent.services import generate_youtube_queries, score_and_sort_results
from app.utils.trailer_finder import find_youtube_trailer, get_videos_details
from app.agent.cache_manager import get_from_cache, set_in_cache
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

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json
    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')

    page_token = data.get('page_token')
    if page_token:
        # La logique de pagination existante est conservée pour l'instant
        query = data.get('query')
        search_result = find_youtube_trailer(query, youtube_api_key, page_token=page_token)
        return jsonify({'success': True, 'results': search_result.get('results', []), 'nextPageToken': search_result.get('nextPageToken'), 'query': query})

    ratingKey = data.get('ratingKey')
    original_title = data.get('title')
    year = data.get('year')
    media_type = data.get('media_type')
    user_id = data.get('userId') # <-- NOUVELLE LIGNE

    if not all([ratingKey, original_title, year, media_type, user_id]):
        return jsonify({'success': False, 'error': 'Données manquantes (ratingKey, title, year, media_type, userId)'}), 400

    # La clé de cache utilise le titre original et le ratingKey pour être unique
    cache_key = f"trailer_search_{original_title}_{year}_{ratingKey}"
    cached_result = get_from_cache(cache_key)
    if cached_result:
        current_app.logger.info(f"Cache HIT for trailer search: '{original_title}'")
        return jsonify({'success': True, **cached_result})

    current_app.logger.debug(f"Suggest Trailer: Received ratingKey={ratingKey}, title='{original_title}', year={year}, userId={user_id}")

    try:
        plex_server = get_user_specific_plex_server_from_id(user_id)
        if not plex_server:
            return jsonify({'success': False, 'error': "Impossible d'établir la connexion au serveur Plex."}), 500

        plex_item = plex_server.fetchItem(int(ratingKey))
        actual_title = get_actual_title(plex_item)
        current_app.logger.debug(f"Suggest Trailer: Original title='{original_title}', Found actual title='{actual_title}'")

    except Exception as e:
        current_app.logger.error(f"Erreur lors de la récupération du titre réel pour ratingKey {ratingKey}: {e}", exc_info=True)
        actual_title = original_title # Fallback en cas d'erreur

    search_queries = generate_youtube_queries(actual_title, year, media_type)
    current_app.logger.debug(f"Suggest Trailer: Generated search queries: {search_queries}")

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
        return jsonify({'success': False, 'error': 'Aucun résultat trouvé pour les requêtes générées.'})

    sorted_by_title = score_and_sort_results(all_results, actual_title, year, media_type)

    top_ids = [res['videoId'] for res in sorted_by_title[:15]]
    if top_ids:
        video_details = get_videos_details(top_ids, youtube_api_key)
        final_sorted_list = score_and_sort_results(sorted_by_title, actual_title, year, media_type, video_details=video_details)
    else:
        final_sorted_list = sorted_by_title

    top_results = final_sorted_list[:10]

    # La pagination est maintenant basée sur la première requête qui a retourné des résultats
    response_data = {
        'results': top_results,
        'nextPageToken': first_next_page_token,
        'query': first_successful_query
    }

    # Log des résultats finaux pour le débogage
    log_results = [{'title': r['title'], 'channel': r['channel'], 'score': r['score']} for r in top_results]
    current_app.logger.debug(f"Suggest Trailer: Top 10 final results: {log_results}")

    # Mettre le résultat final en cache
    set_in_cache(cache_key, response_data)

    return jsonify({'success': True, **response_data})
