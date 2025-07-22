import logging
import requests
from config import Config

def _make_prowlarr_request(endpoint, params=None):
    """
    Helper function to make requests to the Prowlarr API.
    """
    base_url = Config.PROWLARR_URL
    api_key = Config.PROWLARR_API_KEY

    if not base_url or not api_key:
        logging.error("Prowlarr URL or API Key is not configured.")
        return None

    headers = {'X-Api-Key': api_key}
    url = f"{base_url.rstrip('/')}/api/v1/{endpoint}"

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error connecting to Prowlarr at {url}: {e}")
        return None
    except ValueError:
        logging.error(f"Error decoding Prowlarr's JSON response from {url}.")
        return None

def search_prowlarr(query, categories=None, lang=None):
    """
    [VERSION FILTRAGE CLIENT] Recherche des releases sur Prowlarr.
    Le filtrage par catégorie sera géré côté MMS pour plus de fiabilité.
    """
    effective_query = query
    if lang:
        lang_map = {'fr': 'FRENCH', 'en': 'ENGLISH'}
        lang_term = lang_map.get(lang)
        if lang_term:
            effective_query = f"{query} {lang_term}"

    params = {
        'query': effective_query,
        'type': 'search'
    }

    # On n'envoie PAS le paramètre 'category' à Prowlarr.

    # Note : Assurez-vous que la fonction _make_prowlarr_request appelle bien l'endpoint /api/v1/search
    return _make_prowlarr_request('search', params)
