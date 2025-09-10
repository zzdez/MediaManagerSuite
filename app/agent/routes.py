from flask import request, jsonify, current_app
from . import agent_bp
from app.agent.services import generate_youtube_queries, score_and_sort_results
from app.utils.trailer_finder import find_youtube_trailer, get_videos_details
from app.agent.cache_manager import get_from_cache, set_in_cache

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json
    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')

    # NOTE: La pagination est temporairement désactivée pour permettre l'agrégation.
    # On pourrait la réintroduire plus tard en paginant sur la meilleure requête.
    page_token = data.get('page_token')
    query = data.get('query')
    if page_token or query:
        # Pour l'instant, on ne gère pas la pagination sur une recherche agrégée.
        # On retourne simplement une réponse vide pour éviter des erreurs.
        return jsonify({'success': True, 'results': [], 'nextPageToken': None})

    title, year, media_type = data.get('title'), data.get('year'), data.get('media_type')
    if not all([title, year, media_type]):
        return jsonify({'success': False, 'error': 'Données manquantes (title, year, media_type)'}), 400

    # NOTE: La mise en cache est désactivée pendant le développement de la nouvelle logique.
    # cache_key = f"trailer_search_{title}_{year}_{media_type}"
    # cached_result = get_from_cache(cache_key)
    # if cached_result:
    #     return jsonify({'success': True, **cached_result})

    # Étape 1: Générer toutes les requêtes de recherche
    search_queries = generate_youtube_queries(title, year, media_type)

    # Étape 2: Agréger les résultats de toutes les requêtes
    all_results = []
    seen_video_ids = set()

    for current_query in search_queries:
        search_result = find_youtube_trailer(current_query, youtube_api_key)
        if search_result and search_result['results']:
            for result in search_result['results']:
                if result['videoId'] not in seen_video_ids:
                    all_results.append(result)
                    seen_video_ids.add(result['videoId'])

    if not all_results:
        return jsonify({'success': False, 'error': 'Aucun résultat trouvé pour les requêtes générées.'})

    # Étape 3: Premier tri basé sur les titres
    sorted_by_title = score_and_sort_results(all_results, title, year, media_type)

    # Étape 4: Enrichissement avec les détails pour le top 15
    top_15_ids = [res['videoId'] for res in sorted_by_title[:15]]
    if top_15_ids:
        video_details = get_videos_details(top_15_ids, youtube_api_key)
        # Re-trier la liste complète avec les nouvelles informations
        final_sorted_list = score_and_sort_results(sorted_by_title, title, year, media_type, video_details=video_details)
    else:
        final_sorted_list = sorted_by_title

    # On ne retourne que le top 10 final pour garder la liste gérable
    top_results = final_sorted_list[:10]

    # NOTE: Pas de mise en cache ni de nextPageToken pour l'instant.
    response_data = {
        'results': top_results,
        'nextPageToken': None, # Pagination désactivée
        'query': ", ".join(search_queries) # Pour le debug
    }

    return jsonify({'success': True, **response_data})
