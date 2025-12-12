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
    Gère automatiquement le fallback sur d'autres modèles en cas d'erreur.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("Clé API Gemini manquante (GEMINI_API_KEY).")
        return {"error": "Clé API manquante"}

    # Configuration des outils (Google Search Grounding)
    tools = ['google_search_retrieval']

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

    # Paramètres de sécurité pour éviter les blocages inutiles
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    try:
        genai.configure(api_key=api_key)

        # Liste des modèles à essayer, en commençant par celui configuré
        env_model_name = os.environ.get("GEMINI_MODEL_NAME")
        models_to_try = []
        if env_model_name:
            models_to_try.append(env_model_name)

        # Ajout des modèles par défaut pour le fallback
        defaults = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp", "gemini-pro"]
        for m in defaults:
            if m not in models_to_try:
                models_to_try.append(m)

        last_exception = None

        for model_name in models_to_try:
            try:
                logger.info(f"Tentative d'interrogation IA avec le modèle : {model_name}")
                model = genai.GenerativeModel(model_name)

                # C'est ici que l'erreur se produit généralement si le modèle n'existe pas ou n'est pas supporté
                response = model.generate_content(
                    prompt,
                    tools=tools,
                    safety_settings=safety_settings
                )

                # Si on arrive ici, l'appel a réussi, on traite la réponse
                if response.text:
                    raw_text = response.text.strip()
                    # Nettoyage des balises markdown
                    if raw_text.startswith("```json"): raw_text = raw_text[7:]
                    if raw_text.startswith("```"): raw_text = raw_text[3:]
                    if raw_text.endswith("```"): raw_text = raw_text[:-3]
                    raw_text = raw_text.strip()

                    try:
                        data = json.loads(raw_text)
                        return data
                    except json.JSONDecodeError:
                        logger.error(f"Erreur de décodage JSON de l'IA ({model_name}): {raw_text}")
                        return {"error": "L'IA n'a pas renvoyé un format valide."}
                else:
                    return {"error": "Aucune réponse de l'IA."}

            except Exception as e:
                logger.warning(f"Échec avec le modèle {model_name}: {str(e)}")
                last_exception = e
                # On continue la boucle pour essayer le modèle suivant
                continue

        # Si on sort de la boucle sans succès
        error_msg = f"Tous les modèles ont échoué. Dernier erreur: {str(last_exception)}"
        logger.error(error_msg)
        return {"error": error_msg}

    except Exception as e:
        logger.error(f"Erreur critique lors de l'appel à Gemini: {e}", exc_info=True)
        return {"error": f"Erreur Gemini: {str(e)}"}

def list_available_models():
    """
    Liste les modèles Gemini disponibles pour la clé API configurée.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"error": "Clé API manquante"}

    try:
        genai.configure(api_key=api_key)
        models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                models.append({
                    "name": m.name,
                    "display_name": m.display_name,
                    "version": m.version
                })
        return {"models": models}
    except Exception as e:
        logger.error(f"Erreur lors du listage des modèles: {e}")
        return {"error": str(e)}
