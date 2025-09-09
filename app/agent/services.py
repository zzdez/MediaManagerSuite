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
