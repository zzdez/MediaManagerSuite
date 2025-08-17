from flask import request, jsonify, current_app
from . import agent_bp
from app.agent.services import generate_youtube_queries
from app.utils.trailer_finder import find_youtube_trailer

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json
    title, year, media_type = data.get('title'), data.get('year'), data.get('media_type')

    # Étape 1: L'IA génère les requêtes (inchangé)
    search_queries = generate_youtube_queries(title, year, media_type)

    # Étape 2: NOUVELLE LOGIQUE - Boucle sur les requêtes
    final_results = []
    api_key = current_app.config.get('YOUTUBE_API_KEY')

    for query in search_queries:
        results_for_query = find_youtube_trailer(query, api_key)
        if results_for_query:
            final_results = results_for_query
            print(f"DEBUG: Résultats trouvés avec la requête '{query}'. Arrêt de la recherche.")
            break # On a trouvé des résultats, on arrête la boucle

    return jsonify({'success': bool(final_results), 'results': final_results})
