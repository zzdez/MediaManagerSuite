from flask import Blueprint, request, jsonify, current_app
from app.utils.trailer_finder import find_youtube_trailer
from app.agent.services import generate_youtube_queries, score_and_sort_results

trailer_bp = Blueprint('trailer', __name__, url_prefix='/api/trailer')

@trailer_bp.route('/find', methods=['POST'])
def find_trailer_endpoint():
    data = request.json
    title = data.get('title')
    year = data.get('year')
    media_type = data.get('media_type')
    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')

    if not all([title, media_type]):
        return jsonify({'success': False, 'message': 'Le titre et le type de média sont requis.'}), 400

    if not youtube_api_key:
        return jsonify({'success': False, 'message': 'La clé API YouTube n\'est pas configurée.'}), 500

    # 1. Générer les requêtes de recherche
    search_queries = generate_youtube_queries(title, year, media_type)

    # 2. Exécuter les recherches
    all_results = []
    seen_video_ids = set()
    for query in search_queries:
        search_result = find_youtube_trailer(query, youtube_api_key)
        if search_result and search_result['results']:
            for result in search_result['results']:
                if result['videoId'] not in seen_video_ids:
                    all_results.append(result)
                    seen_video_ids.add(result['videoId'])

    if not all_results:
        return jsonify({'success': False, 'message': 'Aucune bande-annonce trouvée sur YouTube.'})

    # 3. Scorer et trier les résultats
    sorted_results = score_and_sort_results(all_results, title, year, media_type)

    # 4. Retourner l'URL du meilleur résultat
    if sorted_results and sorted_results[0]['score'] > 0:
        best_trailer = sorted_results[0]
        trailer_url = f"https://www.youtube.com/embed/{best_trailer['videoId']}?autoplay=1"
        return jsonify({'success': True, 'url': trailer_url})
    else:
        return jsonify({'success': False, 'message': 'Aucune bande-annonce pertinente trouvée après filtrage.'})
