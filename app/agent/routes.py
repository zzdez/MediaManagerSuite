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

    # We now fetch more results to allow for better pagination.
    # Let's aim for ~20-25 results. find_youtube_trailer fetches max 10 per query.
    for current_query in search_queries[:3]: # Limit to 3 queries to avoid long waits
        search_result = find_youtube_trailer(current_query, youtube_api_key, max_results=10)
        if search_result and search_result['results']:
            for result in search_result['results']:
                if result['videoId'] not in seen_video_ids:
                    all_results.append(result)
                    seen_video_ids.add(result['videoId'])

    if not all_results:
        return {'success': False, 'error': 'Aucun résultat trouvé pour les requêtes générées.'}

    sorted_by_title = score_and_sort_results(all_results, title, year, media_type)

    # Fetch details for up to 25 top results to refine scoring
    top_ids = [res['videoId'] for res in sorted_by_title[:25]]
    if top_ids:
        video_details = get_videos_details(top_ids, youtube_api_key)
        final_sorted_list = score_and_sort_results(sorted_by_title, title, year, media_type, video_details=video_details)
    else:
        final_sorted_list = sorted_by_title

    log_results = [{'title': r['title'], 'channel': r['channel'], 'score': r['score']} for r in final_sorted_list[:10]]
    current_app.logger.debug(f"Top 10 final results: {log_results}")

    # Return the full sorted list. The calling function will handle pagination.
    return {'success': True, 'results': final_sorted_list}

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json

    ratingKey = data.get('ratingKey')
    title = data.get('title')
    year = data.get('year')
    media_type = data.get('media_type')
    user_id = data.get('userId')
    page = data.get('page', 1)
    page_size = 5 # Return 5 results per page

    if not ratingKey or not user_id:
        return jsonify({'success': False, 'error': 'Cette route nécessite un ratingKey et un userId pour la mise en cache.'}), 400

    cache_key = f"trailer_search_{title}_{year}_{ratingKey}"

    # On an initial search (page 1), we always perform a fresh search.
    # For subsequent pages, we rely on the cache.
    if page == 1:
        try:
            plex_server = get_user_specific_plex_server_from_id(user_id)
            item = plex_server.fetchItem(int(ratingKey))
            search_title = get_actual_title(item)
        except Exception as e:
            current_app.logger.warning(f"Could not fetch item from Plex for title search, falling back. Error: {e}")
            search_title = title

        search_response = _search_and_score_trailers(search_title, year, media_type)
        if not search_response.get('success'):
            return jsonify(search_response)

        full_results = search_response['results']

        # Preserve lock status from previous cache entry if it exists
        existing_cache = get_from_cache(cache_key)
        is_locked = existing_cache.get('is_locked', False) if existing_cache else False
        locked_video_id = existing_cache.get('locked_video_id', None) if existing_cache else None

        # If a video was locked, find it in the new results and move it to the top.
        if is_locked and locked_video_id:
            locked_item = next((item for item in full_results if item['videoId'] == locked_video_id), None)
            if locked_item:
                full_results.remove(locked_item)
                full_results.insert(0, locked_item)

        # Store the new full list in the cache, maintaining lock state
        set_in_cache(cache_key, {'results': full_results, 'is_locked': is_locked, 'locked_video_id': locked_video_id})

    else: # page > 1
        cached_data = get_from_cache(cache_key)
        if not cached_data:
            return jsonify({'success': False, 'error': 'Session de recherche expirée. Veuillez relancer la recherche.'}), 404
        full_results = cached_data.get('results', [])

    # Get the definitive current state from cache for pagination
    final_cached_data = get_from_cache(cache_key) or {}
    is_locked_final = final_cached_data.get('is_locked', False)
    locked_video_id_final = final_cached_data.get('locked_video_id', None) if is_locked_final else None

    # Paginate the full list
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    paginated_results = full_results[start_index:end_index]
    has_more = len(full_results) > end_index

    return jsonify({
        'success': True,
        'results': paginated_results,
        'has_more': has_more,
        'is_locked': is_locked_final,
        'locked_video_id': locked_video_id_final
    })

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
    page_token = data.get('page_token') # For pagination
    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')

    if not all([query, title, media_type]):
        return jsonify({'success': False, 'error': 'Données manquantes (query, title, media_type)'}), 400

    # For standalone search, we do a simpler search and pagination.
    # We don't do the multi-query and deep scoring like in suggest_trailers.
    search_result = find_youtube_trailer(query, youtube_api_key, page_token=page_token, max_results=5)

    if not search_result or not search_result['results']:
        return jsonify({'success': True, 'results': []})

    # We still score the results for relevance
    sorted_results = score_and_sort_results(search_result['results'], title, year, media_type)

    return jsonify({
        'success': True,
        'results': sorted_results,
        'nextPageToken': search_result.get('nextPageToken'),
        'query': query
    })
