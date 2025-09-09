from flask import request, jsonify, current_app
from . import agent_bp
from app.agent.services import generate_youtube_queries
from app.utils.trailer_finder import find_youtube_trailer
from app.agent.cache_manager import get_from_cache, set_in_cache

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json
    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')

    page_token = data.get('page_token')
    query = data.get('query')

    # Cas 2: Requête de pagination
    if page_token and query:
        print(f"INFO: Requête de pagination pour la requête '{query}'")
        search_result = find_youtube_trailer(query, youtube_api_key, page_token=page_token)
        return jsonify({
            'success': True,
            'results': search_result['results'],
            'nextPageToken': search_result['nextPageToken'],
            'query': query
        })

    # Cas 1: Nouvelle recherche
    title, year, media_type = data.get('title'), data.get('year'), data.get('media_type')
    if not all([title, year, media_type]):
        return jsonify({'success': False, 'error': 'Données manquantes (title, year, media_type)'}), 400

    cache_key = f"trailer_search_{title}_{year}_{media_type}"
    cached_result = get_from_cache(cache_key)
    if cached_result:
        print(f"INFO: Recherche de trailer trouvée dans le cache pour '{title}'.")
        return jsonify({'success': True, **cached_result})

    # Générer les requêtes et essayer chacune d'elles
    search_queries = generate_youtube_queries(title, year, media_type)
    for current_query in search_queries:
        search_result = find_youtube_trailer(current_query, youtube_api_key)
        if search_result and search_result['results']:
            # On a trouvé des résultats, on met en cache et on retourne
            response_data = {
                'results': search_result['results'],
                'nextPageToken': search_result['nextPageToken'],
                'query': current_query # On retourne la requête qui a fonctionné
            }
            set_in_cache(cache_key, response_data)
            return jsonify({'success': True, **response_data})

    # Si aucune requête n'a donné de résultat
    return jsonify({'success': False, 'error': 'Aucun résultat trouvé pour les requêtes générées.'})
