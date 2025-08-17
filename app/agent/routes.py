from flask import request, jsonify, current_app
from . import agent_bp
from app.agent.services import generate_youtube_queries
from app.utils.trailer_finder import find_youtube_trailer
from app.agent.cache_manager import get_from_cache, set_in_cache # <-- NOUVEL IMPORT

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json
    title, year, media_type = data.get('title'), data.get('year'), data.get('media_type')

    # **NOUVELLE LOGIQUE DE CACHE**
    cache_key = f"{title}_{year}_{media_type}"
    cached_results = get_from_cache(cache_key)
    if cached_results is not None:
        return jsonify({'success': True, 'results': cached_results})

    # Si pas dans le cache, on exécute la logique coûteuse
    api_key = current_app.config.get('YOUTUBE_API_KEY')
    final_results = []

    # On ne fait qu'UN SEUL appel à Gemini (le plus coûteux)
    search_queries = generate_youtube_queries(title, year, media_type)

    # On ne fait qu'UN SEUL appel à YouTube avec la meilleure requête
    if search_queries:
        best_query = search_queries[0]
        final_results = find_youtube_trailer(best_query, api_key)

    # Mettre le résultat (même s'il est vide) en cache
    set_in_cache(cache_key, final_results)

    return jsonify({'success': bool(final_results), 'results': final_results})
