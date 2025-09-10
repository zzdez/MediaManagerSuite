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

def score_and_sort_results(results, title, year, media_type, video_details=None):
    """
    Attribue un score à chaque résultat et les trie par pertinence en suivant une hiérarchie stricte.
    """
    if video_details is None:
        video_details = {}

    tie_breaker_weights = {
        "bande annonce": 5, "trailer": 5, "officielle": 3, "official": 3,
        "vf": 15, "vostfr": 12,
        "saison 1": 5 if media_type == 'show' else 0,
        "season 1": 5 if media_type == 'show' else 0,
        "série": 3 if media_type == 'show' else 0,
        "series": 3 if media_type == 'show' else 0,
        "film": 3 if media_type == 'movie' else 0,
        "movie": 3 if media_type == 'movie' else 0,
        "reaction": -50, "review": -50, "analyse": -50,
        "ending": -50, "interview": -50, "promo": -20, "episode": -50
    }

    official_channels = ["hbo", "netflix", "disney", "official", "warner bros", "bandes annonces"]
    distrusted_channels = ["filmsactu"] # Chaînes connues pour des titres trompeurs

    scored_results = []
    # Simplification du titre pour la recherche (ex: "Task (2025)" -> "task")
    simple_title = title.split('(')[0].strip().lower()

    for result in results:
        score = 0
        video_title_lower = result['title'].lower()
        channel_title_lower = result['channel'].lower()

        # Étape 1: Le titre du média DOIT être dans le titre de la vidéo. C'est la condition la plus importante.
        if simple_title not in video_title_lower:
            score -= 1000  # Pénalité massive pour disqualifier
        else:
            score += 100  # Bonus massif si le titre correspond

        # Étape 2: Bonus si l'année correspond
        if str(year) in video_title_lower:
            score += 20

        # Étape 3: Bonus pour les chaînes officielles
        for channel in official_channels:
            if channel in channel_title_lower:
                score += 30
                break # Appliquer le bonus une seule fois

        for channel in distrusted_channels:
            if channel in channel_title_lower:
                score -= 50 # Pénalité pour les chaînes non fiables
                break

        # Étape 4: Mots-clés comme départage (tie-breaker)
        for keyword, weight in tie_breaker_weights.items():
            if keyword in video_title_lower:
                score += weight

        # Étape 5: Affinage avec les détails de la vidéo (si disponibles)
        details = video_details.get(result['videoId'])
        if details:
            if details['snippet'].get('defaultAudioLanguage', '').lower().startswith('fr'):
                score += 40 # Bonus VF
            if details['contentDetails'].get('caption') == 'true':
                score += 20 # Bonus sous-titres

        result['score'] = score
        scored_results.append(result)

    sorted_results = sorted(scored_results, key=lambda x: x['score'], reverse=True)
    return sorted_results
