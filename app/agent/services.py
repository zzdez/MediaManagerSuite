import google.generativeai as genai
import json
from flask import current_app

def generate_youtube_queries(title, year, media_type):
    """
    Génère une liste de requêtes de recherche YouTube, soit via Gemini,
    soit avec une logique de secours robuste.
    """
    def _get_fallback_queries(title, year, media_type):
        """Génère une liste de requêtes de secours variées."""
        queries = [
            f'"{title} {year}" bande annonce officielle vf',
            f'{title} {year} trailer fr',
            f'{title} {year} bande annonce',
            f'"{title}" trailer' # Requête plus simple sans l'année
        ]
        if media_type == 'show':
            queries.extend([
                f'"{title}" saison 1 bande annonce vf',
                f'{title} season 1 trailer',
                f'"{title}" series trailer' # Requête générique pour les séries
            ])
        return queries

    api_key = current_app.config.get('GEMINI_API_KEY')
    model_name = current_app.config.get('GEMINI_MODEL_NAME')

    if not api_key:
        print("AVERTISSEMENT: Clé GEMINI_API_KEY non configurée. Utilisation des requêtes de secours.")
        return _get_fallback_queries(title, year, media_type)

    try:
        model = genai.GenerativeModel(model_name)
        prompt = f"Génère une liste de 3 requêtes de recherche YouTube optimisées pour trouver la bande-annonce officielle du {media_type} '{title}' ({year}). Priorise la langue française (VF puis VOSTFR). Le format de sortie doit être une liste JSON de chaînes de caractères. Ne retourne que le JSON brut."
        response = model.generate_content(prompt)
        json_response = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(json_response)
    except Exception as e:
        print(f"ERREUR lors de la génération des requêtes Gemini avec le modèle '{model_name}': {e}. Utilisation des requêtes de secours.")
        return _get_fallback_queries(title, year, media_type)

def score_and_sort_results(results, title, media_type, video_details=None):
    """
    Attribue un score à chaque résultat et les trie par pertinence.
    Le score est affiné si les détails de la vidéo (langue, sous-titres) sont fournis.
    """
    if video_details is None:
        video_details = {}

    weights = {
        "bande annonce": 5, "trailer": 5, "officielle": 3, "official": 3,
        "vf": 15, "vostfr": 12, # Poids augmentés pour la langue
        "saison 1": 5 if media_type == 'show' else 0,
        "season 1": 5 if media_type == 'show' else 0,
        "série": 3 if media_type == 'show' else 0,
        "series": 3 if media_type == 'show' else 0,
        "film": 3 if media_type == 'movie' else 0,
        "movie": 3 if media_type == 'movie' else 0,
        "reaction": -20, "review": -20, "analyse": -15,
        "ending": -15, "interview": -10, "promo": -5
    }

    scored_results = []
    for result in results:
        score = result.get('score', 0) # On peut re-scorer
        video_title_lower = result['title'].lower()

        # Phase 1: Scoring basé sur le titre (si pas déjà fait)
        if 'score' not in result:
            if title.lower() in video_title_lower:
                score += 10
            for keyword, weight in weights.items():
                if keyword in video_title_lower:
                    score += weight

        # Phase 2: Affinage du score avec les détails de la vidéo
        details = video_details.get(result['videoId'])
        if details:
            # Bonus pour la langue audio française
            if details['snippet'].get('defaultAudioLanguage', '').lower().startswith('fr'):
                score += 20
            # Bonus pour les sous-titres disponibles (proxy pour VOSTFR)
            if details['contentDetails'].get('caption') == 'true':
                score += 10

        result['score'] = score
        scored_results.append(result)

    sorted_results = sorted(scored_results, key=lambda x: x['score'], reverse=True)
    return sorted_results
