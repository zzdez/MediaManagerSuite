import os
import json
import logging
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)

def extract_opengraph_image(url):
    """
    Tente d'extraire l'image OpenGraph (og:image) d'une page Web.
    Utilisé pour récupérer un poster de haute qualité depuis une source officielle.
    """
    if not url or not url.startswith('http'):
        return None

    try:
        # User-Agent standard pour ne pas être bloqué
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                return og_image["content"]
    except Exception as e:
        logger.warning(f"Échec extraction OpenGraph pour {url}: {e}")

    return None

def _get_configured_models(api_key):
    """
    Découvre et trie les modèles Gemini disponibles.
    Retourne une liste de noms de modèles à essayer.
    """
    try:
        genai.configure(api_key=api_key)
        available_model_names = []
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_model_names.append(m.name)
        except Exception as e_list:
            logger.warning(f"Impossible de lister les modèles, utilisation des valeurs par défaut: {e_list}")

        models_to_try = []

        # Priorité A: Variable d'env
        env_model = os.environ.get("GEMINI_MODEL_NAME")
        if env_model: models_to_try.append(env_model)

        # Priorité B: Modèles découverts dynamiquement (Flash puis Pro)
        flash_models = [m for m in available_model_names if 'flash' in m]
        pro_models = [m for m in available_model_names if 'pro' in m and 'vision' not in m]

        flash_models.sort(reverse=True)
        pro_models.sort(reverse=True)

        models_to_try.extend(flash_models)
        models_to_try.extend(pro_models)

        # Priorité C: Fallbacks
        defaults = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "gemini-pro"]
        for d in defaults:
            if d not in models_to_try:
                models_to_try.append(d)

        return models_to_try
    except Exception as e:
        logger.error(f"Erreur config modèles: {e}")
        return ["models/gemini-1.5-flash"]

def _call_gemini(prompt, tools=None):
    """
    Fonction générique pour appeler Gemini avec gestion des modèles et erreurs.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"error": "Clé API manquante"}

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    models_to_try = _get_configured_models(api_key)
    last_exception = None

    for model_name in models_to_try:
        try:
            logger.info(f"Appel IA ({model_name})")
            model = genai.GenerativeModel(model_name)

            # Essai avec outils si fournis
            if tools:
                try:
                    response = model.generate_content(prompt, tools=tools, safety_settings=safety_settings)
                except Exception as e_tool:
                    logger.warning(f"Échec outils {model_name}: {e_tool}, retry sans outils.")
                    response = model.generate_content(prompt, safety_settings=safety_settings)
            else:
                response = model.generate_content(prompt, safety_settings=safety_settings)

            if response.text:
                raw_text = response.text.strip()
                # Clean markdown
                if raw_text.startswith("```json"): raw_text = raw_text[7:]
                if raw_text.startswith("```"): raw_text = raw_text[3:]
                if raw_text.endswith("```"): raw_text = raw_text[:-3]
                raw_text = raw_text.strip()

                try:
                    return json.loads(raw_text)
                except json.JSONDecodeError:
                    return {"error": "Format JSON invalide", "raw": raw_text}
            else:
                return {"error": "Réponse vide"}

        except Exception as e:
            logger.warning(f"Modèle {model_name} échoué: {e}")
            last_exception = e
            continue

    return {"error": f"Tous les modèles ont échoué: {last_exception}"}

def get_metadata_from_ai(query):
    """
    Recherche complète de métadonnées avec Google Search.
    """
    prompt = f"""
    Tu es un expert en métadonnées de cinéma et de télévision.
    Ta mission est de trouver les informations textuelles détaillées pour le média suivant : "{query}".

    Instructions :
    1. Utilise tes outils de recherche (Google Search) pour trouver les informations exactes.
    2. Concentre-toi sur le texte : Titre exact, année, résumé, studio.
    3. Réponds UNIQUEMENT avec un objet JSON valide.

    Structure du JSON attendu :
    {{
        "title": "Titre français officiel",
        "original_title": "Titre original",
        "year": 2024,
        "summary": "Résumé complet en français.",
        "studio": "Studio de production",
        "source_url": "URL pertinente"
    }}

    Si rien n'est trouvé, renvoie {{}}.
    """

    data = _call_gemini(prompt, tools=['google_search_retrieval'])

    if "error" not in data and data.get("source_url"):
        og_img = extract_opengraph_image(data['source_url'])
        if og_img:
            data['poster_candidates'] = [og_img]

    return data

def guess_media_type_and_title(filename_or_title):
    """
    Analyse un nom de fichier/titre de torrent pour deviner le titre propre et le type.
    N'utilise PAS de recherche web, juste de l'analyse linguistique.
    """
    prompt = f"""
    Analyse la chaîne suivante qui est un nom de fichier ou un titre de release torrent :
    "{filename_or_title}"

    Ta mission :
    1. Nettoyer le titre pour avoir un nom de dossier propre (ex: "Le Bureau des Légendes S01" -> "Le Bureau des Légendes").
    2. Déterminer si c'est un FILM ('movie') ou une SÉRIE ('tv') en te basant sur des indices comme SxxExx, Saison, Integrale, ou le titre lui-même.

    Réponds UNIQUEMENT avec ce JSON :
    {{
        "title": "Titre Nettoyé",
        "type": "movie" ou "tv"
    }}
    """

    # Pas d'outils de recherche nécessaire ici, c'est de l'analyse de texte pur
    return _call_gemini(prompt, tools=None)

def list_available_models():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return {"error": "Clé API manquante"}
    try:
        genai.configure(api_key=api_key)
        models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                models.append({"name": m.name, "display_name": m.display_name})
        return {"models": models}
    except Exception as e:
        return {"error": str(e)}
