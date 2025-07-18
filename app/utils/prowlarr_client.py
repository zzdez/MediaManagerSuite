# app/utils/prowlarr_client.py
import requests
from flask import current_app

def _prowlarr_api_request(params):
    """Helper function to make requests to the Prowlarr API."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    # On récupère l'URL et on la traite de manière sûre
    base_url_from_config = config.get('PROWLARR_URL')

    # On vérifie AVANT d'essayer de manipuler la chaîne
    if not api_key or not base_url_from_config:
        current_app.logger.error("Prowlarr URL or API Key is not configured.")
        return None

    # On enlève le / final seulement si la chaîne existe
    base_url = base_url_from_config.rstrip('/')
    
    # L'endpoint de recherche est /api/v1/search pour Prowlarr
    url = f"{base_url}/api/v1/search"
    
    # Le reste de la fonction est inchangé...
    request_params = {'apikey': api_key}
    request_params.update(params)

    try:
        response = requests.get(url, params=request_params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr API request failed: {e}")
        return None


def get_prowlarr_categories():
    """Fetches all available categories from the Prowlarr API."""
    # On utilise le helper existant qui connaît la bonne URL (/api/v1/search)
    # et on lui passe le paramètre 't=caps' pour demander les capacités.
    params = {'t': 'caps', 'o': 'json'} # 'o=json' pour être sûr de la réponse
    
    response_json = _prowlarr_api_request(params)
    
    if not response_json:
        current_app.logger.error("N'a reçu aucune réponse de Prowlarr pour la demande de catégories.")
        return []

    # La structure de la réponse de /api/v1/search?t=caps est response['categories']['category']
    try:
        if 'categories' in response_json and 'category' in response_json['categories']:
            all_categories = response_json['categories']['category']
            # On trie par ID pour un affichage cohérent
            return sorted(all_categories, key=lambda x: int(x['@attributes']['id']))
        else:
            current_app.logger.error("Format de réponse inattendu pour les catégories Prowlarr. Réponse reçue : %s", response_json)
            return []
    except (KeyError, TypeError) as e:
        current_app.logger.error(f"Erreur en parsant la réponse des catégories Prowlarr : {e}")
        return []

def search_prowlarr(query, categories=None, lang=None):
    """
    Searches Prowlarr for a given query and optional filters.
    Prowlarr's direct filtering capabilities are limited via API,
    so complex filtering (like year, quality) will be done post-retrieval.
    """
    params = {
        'query': query,
        'type': 'search'
    }
    if categories:
        params['category'] = categories

    # Le filtrage par langue peut parfois être ajouté à la query
    # Prowlarr ne gère pas un paramètre 'lang' directement dans la recherche.
    # On l'ajoute au terme de recherche, ce qui est une heuristique courante.
    effective_query = query
    if lang:
        lang_map = {'fr': 'FRENCH', 'en': 'ENGLISH'} # Peut être étendu
        lang_term = lang_map.get(lang)
        if lang_term:
            effective_query = f"{query} {lang_term}"

    params['query'] = effective_query

    return _prowlarr_api_request(params)
