from urllib.parse import quote

def find_plex_trailer(plex_item, plex_server):
    """
    Recherche une bande-annonce pour un item Plex et retourne une URL de streaming universel.
    """
    if not plex_item or not hasattr(plex_item, 'extras'):
        return None

    for extra in plex_item.extras():
        if extra.subtype == 'trailer':
            try:
                media_part = extra.media[0].parts[0]
                part_key = media_part.key

                # ÉTAPE CRUCIALE : Encoder le part_key pour qu'il soit sûr dans une URL
                encoded_part_key = quote(part_key)

                # Construire le chemin du transcodeur avec la clé ENCODÉE
                transcode_path = f'/video/:/transcode/universal/start.m3u8?path={encoded_part_key}'

                trailer_url = plex_server.url(transcode_path, includeToken=True)
                return trailer_url

            except (IndexError, AttributeError) as e:
                print(f"DEBUG: Impossible de trouver une partie média pour la bande-annonce '{extra.title}': {e}")
                continue

    return None
