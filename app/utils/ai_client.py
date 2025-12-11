import os
import json
import logging
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)

def get_metadata_from_ai(query):
    """
    Interroge l'API Gemini pour trouver des métadonnées sur un média.
    Utilise le 'grounding' (recherche Google) pour les infos récentes/spécifiques.
    Retourne un dictionnaire JSON structuré.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("Clé API Gemini manquante (GEMINI_API_KEY).")
        return {"error": "Clé API manquante"}

    try:
        genai.configure(api_key=api_key)

        # Configuration du modèle
        # On utilise gemini-1.5-flash pour la rapidité et le coût, ou pro si dispo
        model_name = "gemini-1.5-flash"

        # Configuration des outils (Google Search Grounding)
        # Note: La syntaxe peut varier selon la version de la lib.
        # Pour google-generativeai v0.8.x, 'google_search_retrieval' est souvent le mot clé pour le grounding
        tools = ['google_search_retrieval']

        model = genai.GenerativeModel(model_name)

        # Prompt system/user combiné
        prompt = f"""
        Tu es un expert en métadonnées de cinéma et de télévision.
        Ta mission est de trouver les informations détaillées pour le média suivant : "{query}".

        Instructions :
        1. Cherche sur le web (Google) pour trouver les informations exactes, surtout si c'est un programme TV (Arte, France 5, etc.) ou un film récent.
        2. Si tu trouves plusieurs correspondances, choisis la plus pertinente (correspondance titre/année).
        3. Réponds UNIQUEMENT avec un objet JSON valide (pas de markdown ```json ... ```, juste le JSON).

        Structure du JSON attendu :
        {{
            "title": "Titre français officiel",
            "original_title": "Titre original (si différent)",
            "year": 2024,
            "summary": "Résumé complet en français (2-3 phrases).",
            "studio": "Studio de production ou Chaîne de diffusion principale",
            "poster_url": "URL valide d'une image d'affiche (si trouvée, sinon null)"
        }}

        Si tu ne trouves rien de pertinent, renvoie un objet JSON vide {{}}.
        """

        # Paramètres de sécurité pour éviter les blocages inutiles sur des synopsis
        safety_settings = {
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }

        # Appel à l'API
        response = model.generate_content(
            prompt,
            tools=tools,
            safety_settings=safety_settings
        )

        # Traitement de la réponse
        if response.text:
            raw_text = response.text.strip()
            # Nettoyage des balises markdown si présentes
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            raw_text = raw_text.strip()

            try:
                data = json.loads(raw_text)
                return data
            except json.JSONDecodeError:
                logger.error(f"Erreur de décodage JSON de l'IA: {raw_text}")
                return {"error": "L'IA n'a pas renvoyé un format valide."}
        else:
             return {"error": "Aucune réponse de l'IA."}

    except Exception as e:
        logger.error(f"Erreur lors de l'appel à Gemini: {e}", exc_info=True)
        return {"error": f"Erreur Gemini: {str(e)}"}
