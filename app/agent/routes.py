from flask import Blueprint, request, jsonify, current_app
from app.agent.services import generate_youtube_queries
from app.utils.trailer_finder import find_youtube_trailer

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json
    title, year, media_type = data.get('title'), data.get('year'), data.get('media_type')

    # Étape 1: L'IA génère les requêtes
    search_queries = generate_youtube_queries(title, year, media_type)

    # Étape 2: On cherche sur YouTube avec ces requêtes
    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')

    # On utilise la première requête suggérée par l'IA, comme demandé.
    # La fonction attend une liste, donc on l'encapsule.
    if search_queries:
        results = find_youtube_trailer([search_queries[0]], youtube_api_key)
    else:
        results = None

    return jsonify({'success': True, 'results': results})
