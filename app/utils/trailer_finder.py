def find_plex_trailer(plex_item, plex_server):
    """
    Recherche une bande-annonce pour un item Plex et retourne une URL de streaming authentifiée.
    """
    if not plex_item or not hasattr(plex_item, 'extras'):
        return None

    for extra in plex_item.extras:
        if extra.subtype == 'trailer':
            # Utilise la méthode .url() du serveur pour construire l'URL complète avec token
            trailer_url = plex_server.url(extra.key, includeToken=True)
            return trailer_url

    return None # Aucune bande-annonce trouvée dans les extras
