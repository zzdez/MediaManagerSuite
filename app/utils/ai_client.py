import os
import json
import logging
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)

def get_metadata_from_ai(query):
    """
    Interroge l'API Gemini pour trouver des métadonnées sur un média.
    Tente d'abord une recherche avec 'grounding' (Google Search).
    En cas d'échec (modèle incompatible), retente SANS les outils.
    Retourne un dictionnaire JSON structuré.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("Clé API Gemini manquante (GEMINI_API_KEY).")
        return {"error": "Clé API manquante"}

    # Configuration des outils (Google Search Grounding)
    tools_with_search = ['google_search_retrieval']

    # Prompt system/user combiné
    prompt = f"""
    Tu es un expert en métadonnées de cinéma et de télévision.
    Ta mission est de trouver les informations détaillées pour le média suivant : "{query}".

    Instructions :
    1. Si possible, utilise tes outils de recherche pour trouver les informations exactes (surtout pour les programmes TV récents).
    2. Sinon, utilise tes connaissances internes.
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

    # Paramètres de sécurité
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    try:
        genai.configure(api_key=api_key)

        # 1. Découverte dynamique des modèles
        # On ne se fie plus aux noms codés en dur, on demande à l'API ce qui est dispo
        available_model_names = []
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_model_names.append(m.name)
        except Exception as e_list:
            logger.warning(f"Impossible de lister les modèles, utilisation des valeurs par défaut: {e_list}")

        # 2. Construction de la liste de priorité
        models_to_try = []

        # Priorité A: Variable d'env
        env_model = os.environ.get("GEMINI_MODEL_NAME")
        if env_model: models_to_try.append(env_model)

        # Priorité B: Modèles découverts dynamiquement (Flash puis Pro)
        # On cherche ceux qui contiennent 'flash' puis ceux qui contiennent 'pro'
        flash_models = [m for m in available_model_names if 'flash' in m]
        pro_models = [m for m in available_model_names if 'pro' in m and 'vision' not in m] # Eviter les modèles vision-only si possible

        # On trie pour avoir les plus récents (souvent numéro de version plus élevé ou 'latest')
        flash_models.sort(reverse=True)
        pro_models.sort(reverse=True)

        models_to_try.extend(flash_models)
        models_to_try.extend(pro_models)

        # Priorité C: Fallbacks codés en dur (au cas où list_models échoue)
        defaults = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "gemini-pro"]
        for d in defaults:
            if d not in models_to_try:
                models_to_try.append(d)

        # 3. Boucle d'essai
        last_exception = None

        for model_name in models_to_try:
            try:
                logger.info(f"Tentative IA avec le modèle : {model_name}")
                model = genai.GenerativeModel(model_name)

                # --- Essai 1 : AVEC OUTILS (Recherche Web) ---
                try:
                    response = model.generate_content(
                        prompt,
                        tools=tools_with_search,
                        safety_settings=safety_settings
                    )
                except Exception as e_tool:
                    # Si l'erreur est liée aux outils (ex: modèle ne supporte pas search), on réessaie SANS
                    logger.warning(f"Échec avec outils pour {model_name} ({e_tool}), nouvelle tentative SANS outils.")
                    response = model.generate_content(
                        prompt,
                        # Pas de tools
                        safety_settings=safety_settings
                    )

                # Si on arrive ici, l'appel a réussi, on traite la réponse
                if response.text:
                    raw_text = response.text.strip()
                    if raw_text.startswith("```json"): raw_text = raw_text[7:]
                    if raw_text.startswith("```"): raw_text = raw_text[3:]
                    if raw_text.endswith("```"): raw_text = raw_text[:-3]
                    raw_text = raw_text.strip()

                    try:
                        data = json.loads(raw_text)
                        return data
                    except json.JSONDecodeError:
                        logger.error(f"Erreur de décodage JSON IA ({model_name}): {raw_text}")
                        return {"error": "L'IA n'a pas renvoyé un format valide."}
                else:
                    return {"error": "Aucune réponse de l'IA."}

            except Exception as e:
                logger.warning(f"Échec complet avec le modèle {model_name}: {str(e)}")
                last_exception = e
                continue # Essayer le prochain modèle

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
