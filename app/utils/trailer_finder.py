def find_plex_trailer(plex_item, plex_server):
    """
    Recherche une bande-annonce pour un item Plex et retourne une URL de streaming universel.
    """
    if not plex_item or not hasattr(plex_item, 'extras'):
        return None

    for extra in plex_item.extras():
        if extra.subtype == 'trailer':
            # Construire le path pour le transcodeur universel
            transcode_path = (f'/video/:/transcode/universal/start.m3u8'
                              f'?path={extra.key}&mediaIndex=0&partIndex=0'
                              f'&protocol=hls&fastSeek=1&directPlay=0&directStream=1'
                              f'&videoQuality=100&maxVideoBitrate=20000&videoResolution=1920x1080')

            # Utiliser la méthode .url() du serveur pour ajouter l'adresse et le token
            trailer_url = plex_server.url(transcode_path, includeToken=True)
            return trailer_url

    return None
