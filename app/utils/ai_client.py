import os
import json
import logging
import requests
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

logger = logging.getLogger(__name__)

def validate_image_candidate(url, target_ratio_type="poster"):
    """
    Vérifie si une image candidate est valide (téléchargeable, taille, ratio).
    target_ratio_type: 'poster' (approx 0.66) ou 'background' (approx 1.77)
    """
    if not url or not url.startswith('http'):
        return False

    try:
        # HEAD ou GET partiel pour éviter de tout télécharger si possible,
        # mais PIL a besoin de quelques octets. On télécharge tout pour simplifier (images web < 5MB).
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=5, stream=True)

        if response.status_code != 200:
            return False

        # Limite de taille simple
        if len(response.content) < 1000: # Trop petit pour une image
            return False

        img = Image.open(BytesIO(response.content))
        width, height = img.size

        if width < 300 or height < 300: # Trop petite résolution
            return False

        ratio = width / height

        if target_ratio_type == "poster":
            # Poster vertical : width < height. Ratio idéal ~0.66 (2/3). Acceptons 0.5 à 0.8
            if 0.5 <= ratio <= 0.85:
                return True
        elif target_ratio_type == "background":
            # Fond horizontal : width > height. Ratio idéal ~1.77 (16/9). Acceptons 1.3 à 2.0
            if 1.3 <= ratio <= 2.2:
                return True

        return False # Ratio incorrect

    except Exception as e:
        logger.warning(f"Validation image échouée pour {url}: {e}")
        return False

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
    1. Utilise tes outils de recherche (Google Images, Web) pour trouver non seulement les infos, mais aussi plusieurs images candidates pertinentes.
    2. Pour les images (posters et backgrounds), cherche des liens directs (jpg/png/webp) sur des sites fiables (TheMovieDB, Fanart.tv, Amazon, sites de chaînes TV...).
    3. Ne te limite pas à une seule image, fournis une liste de candidats.
    4. Réponds UNIQUEMENT avec un objet JSON valide.

    Structure du JSON attendu :
    {{
        "title": "Titre français officiel",
        "original_title": "Titre original (si différent)",
        "year": 2024,
        "summary": "Résumé complet en français (2-3 phrases).",
        "studio": "Studio de production ou Chaîne de diffusion principale",
        "source_url": "L'URL de la page web officielle ou la plus pertinente (ex: arte.tv, allocine...)",
        "poster_candidates": [
            "https://url_image_1.jpg",
            "https://url_image_2.jpg",
            "..."
        ],
        "background_candidates": [
            "https://url_fond_1.jpg",
            "https://url_fond_2.jpg"
        ]
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

                        # --- TRAITEMENT DES CANDIDATS IMAGES ---
                        # On valide et filtre les listes fournies par l'IA

                        valid_posters = []
                        raw_posters = data.get('poster_candidates', [])
                        if isinstance(raw_posters, list):
                            for url in raw_posters[:5]: # Limiter aux 5 premiers pour la perf
                                if validate_image_candidate(url, "poster"):
                                    valid_posters.append(url)

                        valid_backgrounds = []
                        raw_backgrounds = data.get('background_candidates', [])
                        if isinstance(raw_backgrounds, list):
                            for url in raw_backgrounds[:5]:
                                if validate_image_candidate(url, "background"):
                                    valid_backgrounds.append(url)

                        # --- FALLBACK OPENGRAPH ---
                        # Si aucun poster valide trouvé, on essaie l'OpenGraph de la source
                        if not valid_posters and data.get('source_url'):
                            logger.info(f"Aucun poster IA valide. Tentative extraction OpenGraph depuis {data['source_url']}")
                            og_img = extract_opengraph_image(data['source_url'])
                            if og_img:
                                # On ne sait pas si c'est vertical ou horizontal, mais on l'ajoute
                                # Souvent OpenGraph est horizontal (1200x630), donc on peut le mettre dans backgrounds aussi
                                # ou le tenter en poster. Mettons-le dans les deux pour laisser le choix.
                                if validate_image_candidate(og_img, "poster"):
                                    valid_posters.append(og_img)
                                else:
                                    # Si pas ratio poster, c'est probablement un background
                                    valid_backgrounds.append(og_img)

                        # Mise à jour du JSON final
                        data['poster_candidates'] = valid_posters
                        data['background_candidates'] = valid_backgrounds

                        # On retire les anciens champs simples pour éviter la confusion
                        if 'poster_url' in data: del data['poster_url']

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
