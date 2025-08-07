def find_plex_trailer(plex_item, plex_server):
    """
    Recherche une bande-annonce et retourne une URL de streaming directe.
    """
    if not plex_item or not hasattr(plex_item, 'extras'):
        return None

    for extra in plex_item.extras():
        if extra.subtype == 'trailer':
            try:
                # Pour les bandes-annonces de services (IVA), le part.key est le chemin direct.
                media_part = extra.media[0].parts[0]
                part_key = media_part.key  # ex: /services/iva/assets/597084/video.mp4?fmt=4...

                # On utilise directement cette clé. Le serveur Plex agit comme un proxy.
                # La méthode .url() ajoutera l'adresse du serveur et le token.
                trailer_url = plex_server.url(part_key, includeToken=True)
                return trailer_url

            except (IndexError, AttributeError) as e:
                # Cette exception se produit si la bande-annonce est mal formée.
                print(f"DEBUG: Impossible de trouver une partie média pour la bande-annonce '{extra.title}': {e}")
                continue

    return None
