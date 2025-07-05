# app/search_ui/utils.py

import requests
import json
from flask import current_app

def get_content_with_flaresolverr(target_url):
    """
    Envoie une requête à FlareSolverr pour récupérer le contenu d'une URL protégée.
    Ceci utilise la méthode en deux temps :
    1. Obtenir les cookies/headers de FlareSolverr.
    2. Faire la requête finale avec ces informations.

    Args:
        target_url (str): L'URL du fichier .torrent à télécharger.

    Returns:
        bytes: Le contenu binaire de la réponse si la requête réussit.
        None: Si la requête échoue ou si FlareSolverr n'est pas configuré.
    """
    flaresolverr_url = current_app.config.get('FLARESOLVERR_URL')
    if not flaresolverr_url:
        # Ce n'est pas une erreur, juste que la fonction n'est pas activée.
        current_app.logger.info("FlareSolverr n'est pas configuré. Annulation de la tentative.")
        return None

    # S'assurer que l'URL de l'API est bien formée
    api_url = f"{flaresolverr_url.rstrip('/')}/v1"

    payload = {
        'cmd': 'request.get',
        'url': target_url,
        'maxTimeout': 60000  # Timeout de 60 secondes pour la résolution du challenge
    }
    headers = {'Content-Type': 'application/json'}

    try:
        current_app.logger.info(f"Envoi de la requête à FlareSolverr ({api_url}) pour l'URL : {target_url}")
        # Timeout pour la requête à FlareSolverr lui-même, légèrement supérieur à son propre timeout
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=70)
        response.raise_for_status()

        flaresolverr_data = response.json()

        if flaresolverr_data.get('status') == 'ok' and 'solution' in flaresolverr_data:
            solution = flaresolverr_data['solution']
            cookies = {cookie['name']: cookie['value'] for cookie in solution.get('cookies', [])}
            user_agent = solution.get('userAgent')

            current_app.logger.info("Solution FlareSolverr reçue. Utilisation des cookies et de l'User-Agent pour le téléchargement final.")

            final_headers = {'User-Agent': user_agent}
            final_response = requests.get(target_url, cookies=cookies, headers=final_headers, timeout=30)
            final_response.raise_for_status()

            # Vérifier que le contenu semble être un fichier torrent (commence par 'd' et contient 'info')
            if final_response.content and final_response.content.startswith(b'd') and b'info' in final_response.content:
                 current_app.logger.info("Contenu du torrent téléchargé avec succès via la solution FlareSolverr.")
                 return final_response.content
            else:
                 current_app.logger.warning("Le contenu téléchargé via FlareSolverr ne semble pas être un fichier .torrent valide.")
                 return None

        else:
            current_app.logger.error(f"Erreur retournée par FlareSolverr : {flaresolverr_data.get('message')}")
            return None

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Erreur de communication avec FlareSolverr ou l'URL finale : {e}")
        return None
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue dans la fonction get_content_with_flaresolverr : {e}")
        return None
