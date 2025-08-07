# L'import de urlencode n'est plus nécessaire car la méthode .url() s'en charge
# si on ne construit pas nous-mêmes la query string.

def find_plex_trailer(plex_item, plex_server):
    """
    Recherche une bande-annonce pour un item Plex et retourne une URL de streaming universel.
    """
    if not plex_item or not hasattr(plex_item, 'extras'):
        return None

    for extra in plex_item.extras():
        if extra.subtype == 'trailer':
            try:
                # ÉTAPE CRUCIALE : Accéder à la première "partie" du média
                # C'est cette clé que le transcodeur attend.
                media_part = extra.media[0].parts[0]
                part_key = media_part.key

                # On construit le chemin du transcodeur en utilisant la clé de la partie
                transcode_path = f'/video/:/transcode/universal/start.m3u8?path={part_key}'

                # La méthode .url() du serveur ajoute l'adresse, le port et le token.
                # Elle gère aussi l'encodage nécessaire.
                trailer_url = plex_server.url(transcode_path, includeToken=True)
                return trailer_url

            except (IndexError, AttributeError) as e:
                # Cette exception se produit si la bande-annonce n'a pas de média ou de partie,
                # ce qui peut arriver. On l'ignore et on continue.
                print(f"DEBUG: Impossible de trouver une partie média pour la bande-annonce '{extra.title}': {e}")
                continue

    return None
