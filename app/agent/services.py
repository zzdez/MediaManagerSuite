import google.generativeai as genai
import json
from flask import current_app

def generate_youtube_queries(title, year, media_type):
    api_key = current_app.config.get('GEMINI_API_KEY')
    if not api_key:
        print("AVERTISSEMENT: Clé GEMINI_API_KEY non configurée.")
        return [f'"{title}" {year} bande annonce officielle vf'] # Fallback

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-pro')

    prompt = f"Génère une liste de 3 requêtes de recherche YouTube optimisées pour trouver la bande-annonce officielle du {media_type} '{title}' ({year}). Priorise la langue française (VF puis VOSTFR). Le format de sortie doit être une liste JSON de chaînes de caractères. Ne retourne que le JSON brut."

    try:
        response = model.generate_content(prompt)
        json_response = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(json_response)
    except Exception as e:
        print(f"ERREUR lors de la génération des requêtes Gemini : {e}")
        return [f'"{title}" {year} bande annonce officielle vf']
