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
            f'{title} {year} bande annonce'
        ]
        if media_type == 'show':
            queries.extend([
                f'"{title}" saison 1 bande annonce vf',
                f'{title} season 1 trailer'
            ])
        return queries

    api_key = current_app.config.get('GEMINI_API_KEY')
    model_name = current_app.config.get('GEMINI_MODEL_NAME')

    if not api_key:
        print("AVERTISSEMENT: Clé GEMINI_API_KEY non configurée. Utilisation des requêtes de secours.")
        return _get_fallback_queries(title, year, media_type)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        prompt = f"Génère une liste de 3 requêtes de recherche YouTube optimisées pour trouver la bande-annonce officielle du {media_type} '{title}' ({year}). Priorise la langue française (VF puis VOSTFR). Le format de sortie doit être une liste JSON de chaînes de caractères. Ne retourne que le JSON brut."
        response = model.generate_content(prompt)
        json_response = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(json_response)
    except Exception as e:
        print(f"ERREUR lors de la génération des requêtes Gemini avec le modèle '{model_name}': {e}. Utilisation des requêtes de secours.")
        return _get_fallback_queries(title, year, media_type)

def select_best_trailer_with_gemini(youtube_results, title, year, media_type):
    """
    Utilise Gemini pour sélectionner le meilleur trailer parmi une liste de résultats YouTube.
    """
    api_key = current_app.config.get('GEMINI_API_KEY')
    model_name = current_app.config.get('GEMINI_MODEL_NAME')

    if not api_key:
        print("AVERTISSEMENT: Clé GEMINI_API_KEY non configurée. Sélection du premier trailer par défaut.")
        return youtube_results[0] if youtube_results else None

    if not youtube_results:
        return None

    # Prépare une liste des titres de vidéos pour le prompt
    video_titles = [f"{i+1}. {result['title']}" for i, result in enumerate(youtube_results)]
    video_titles_str = "\n".join(video_titles)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)

        prompt = f"""
        Étant donné le titre du {media_type} '{title}' ({year}), choisis la vidéo qui est le plus probablement la bande-annonce officielle en français (VF) ou à défaut en version originale sous-titrée (VOSTFR) parmi la liste suivante.
        Ne réponds qu'avec le numéro de la vidéo choisie (par exemple: '3').

        Voici les titres des vidéos :
        {video_titles_str}
        """

        response = model.generate_content(prompt)
        # Nettoyage robuste de la réponse pour n'extraire que le premier chiffre trouvé
        choice_text = ''.join(filter(str.isdigit, response.text))

        if choice_text:
            choice_index = int(choice_text) - 1
            if 0 <= choice_index < len(youtube_results):
                print(f"INFO: Gemini a choisi le trailer n°{choice_index + 1}: '{youtube_results[choice_index]['title']}'")
                return youtube_results[choice_index]

        # Fallback si Gemini ne donne pas une réponse valide
        print("AVERTISSEMENT: Gemini n'a pas retourné un choix valide. Sélection du premier trailer.")
        return youtube_results[0]

    except Exception as e:
        print(f"ERREUR lors de la sélection du trailer par Gemini: {e}")
        # En cas d'erreur API, on retourne le premier résultat par sécurité
        return youtube_results[0]
