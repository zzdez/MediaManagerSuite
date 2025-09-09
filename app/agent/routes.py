from flask import request, jsonify, current_app
from . import agent_bp
from app.agent.services import generate_youtube_queries, select_best_trailer_with_gemini
from app.utils.trailer_finder import find_youtube_trailer
from app.agent.cache_manager import get_from_cache, set_in_cache

@agent_bp.route('/suggest_trailers', methods=['POST'])
def suggest_trailers():
    data = request.json
    title, year, media_type = data.get('title'), data.get('year'), data.get('media_type')

    if not all([title, year, media_type]):
        return jsonify({'success': False, 'error': 'Données manquantes (title, year, media_type)'}), 400

    cache_key = f"trailer_{title}_{year}_{media_type}"
    cached_result = get_from_cache(cache_key)
    if cached_result is not None:
        print(f"INFO: Trailer trouvé dans le cache pour '{title}'.")
        return jsonify({'success': True, 'result': cached_result})

    youtube_api_key = current_app.config.get('YOUTUBE_API_KEY')
    gemini_api_key = current_app.config.get('GEMINI_API_KEY')

    # Étape 1: Générer des requêtes de recherche intelligentes
    search_queries = generate_youtube_queries(title, year, media_type)

    # Étape 2: Chercher sur YouTube avec toutes les requêtes jusqu'à trouver des résultats
    youtube_results = find_youtube_trailer(search_queries, youtube_api_key)

    if not youtube_results:
        return jsonify({'success': False, 'error': 'Aucun résultat trouvé sur YouTube.'})

    # Étape 3: Sélectionner le meilleur trailer avec Gemini (ou fallback)
    # Si Gemini n'est pas configuré, on utilise un fallback simple : le premier résultat.
    if gemini_api_key:
        best_trailer = select_best_trailer_with_gemini(youtube_results, title, year, media_type)
    else:
        print("AVERTISSEMENT: GEMINI_API_KEY non trouvé. Sélection du premier trailer par défaut.")
        best_trailer = youtube_results[0]

    if best_trailer:
        # Mettre en cache le résultat final pour 24h (86400s)
        set_in_cache(cache_key, best_trailer, expiration=86400)
        return jsonify({'success': True, 'result': best_trailer})
    else:
        # Ce cas est peu probable si youtube_results n'est pas vide, mais par sécurité
        return jsonify({'success': False, 'error': 'Impossible de sélectionner un trailer pertinent.'})
