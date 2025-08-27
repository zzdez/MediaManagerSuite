# Fichier : app/utils/prowlarr_client.py
import requests
from flask import current_app
import logging

def _make_prowlarr_request(endpoint, params=None):
    """Makes a request to Prowlarr's internal JSON API."""
    config = current_app.config
    api_key = config.get('PROWLARR_API_KEY')
    base_url = config.get('PROWLARR_URL', '').rstrip('/')
    if not api_key or not base_url:
        current_app.logger.error("Prowlarr URL or API Key not configured for JSON API.")
        return None

    url = f"{base_url}/api/v1/{endpoint.lstrip('/')}"
    request_params = {'apikey': api_key}
    if params:
        request_params.update(params)

    try:
        # Prowlarr gère les listes dans les params (pour les catégories)
        response = requests.get(url, params=request_params, timeout=45)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Prowlarr JSON API request for endpoint '{endpoint}' failed: {e}")
        return None

def search_prowlarr(query, categories=None, lang=None, quality=None, codec=None, source=None, group=None):
    """
    Performs an intelligent search on Prowlarr, delegating filtering to the Prowlarr API.
    """
    # 1. Construire la chaîne de recherche textuelle intelligente
    query_parts = [query]

    # ### DÉBUT DE LA CORRECTION ###
    # On ajoute les filtres SEULEMENT s'ils ont une valeur non-vide.
    if lang:
        lang_map = {'fr': 'FRENCH', 'en': 'ENGLISH'}
        lang_term = lang_map.get(lang)
        if lang_term: query_parts.append(lang_term)

    if quality: query_parts.append(quality)
    if codec: query_parts.append(codec)
    if source: query_parts.append(source)
    if group: query_parts.append(group)
    # ### FIN DE LA CORRECTION ###

    effective_query = " ".join(query_parts)

    # 2. Préparer les paramètres pour l'API Prowlarr
    params = {
        'query': effective_query,
        'type': 'search'
    }

    # 3. Ajouter le filtrage par catégories, qui est le plus efficace
    if categories:
        params['categories'] = categories

    current_app.logger.info(f"Executing Prowlarr search with effective query: '{effective_query}' and params: {params}")

    return _make_prowlarr_request('search', params)

def get_prowlarr_categories():
    """
    Fetches and parses all categories from enabled Prowlarr indexers.
    (Cette fonction reste inchangée)
    """
    try:
        indexers = _make_prowlarr_request('indexer')
        if not indexers: raise ValueError("Indexer list from Prowlarr is empty or unreachable.")

        all_categories_map = {}
        def parse_categories_recursive(categories, indexer_name, parent_name=""):
            for cat in categories:
                cat_id_str = str(cat.get('id'))
                cat_name = cat.get('name', '').strip()
                if not cat_id_str or not cat_name: continue
                full_name = f"{parent_name}/{cat_name}" if parent_name and not cat_name.startswith(parent_name) else cat_name
                if cat_id_str not in all_categories_map:
                    all_categories_map[cat_id_str] = {'id': cat_id_str, 'name': full_name, 'indexers': []}
                if indexer_name not in all_categories_map[cat_id_str]['indexers']:
                    all_categories_map[cat_id_str]['indexers'].append(indexer_name)
                if 'subCategories' in cat and cat['subCategories']:
                    parse_categories_recursive(cat['subCategories'], indexer_name, parent_name=cat_name)

        for indexer in indexers:
            indexer_name = indexer.get('name')
            if not indexer.get('enable', False) or not indexer_name: continue
            if 'capabilities' in indexer and 'categories' in indexer['capabilities']:
                parse_categories_recursive(indexer['capabilities']['categories'], indexer_name)

        if not all_categories_map: raise ValueError("No valid categories parsed.")

        return sorted(list(all_categories_map.values()), key=lambda x: int(x['id']))
    except Exception as e:
        current_app.logger.error(f"Prowlarr category processing failed: {e}", exc_info=True)
        return []