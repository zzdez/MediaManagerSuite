from urllib.parse import urlencode

def find_plex_trailer(plex_item, plex_server):
    """
    Recherche une bande-annonce pour un item Plex et retourne une URL de streaming universel.
    """
    if not plex_item or not hasattr(plex_item, 'extras'):
        return None

    for extra in plex_item.extras():
        if extra.subtype == 'trailer':
            # **NOUVELLE LOGIQUE DE CONSTRUCTION SÉCURISÉE**

            # 1. Définir les paramètres du transcodeur dans un dictionnaire
            params = {
                'path': extra.key, # La clé originale, ex: /library/metadata/43579
                'mediaIndex': 0,
                'partIndex': 0,
                'protocol': 'hls',
                'fastSeek': 1,
                'directPlay': 0,
                'directStream': 1,
                'videoQuality': 100,
                'maxVideoBitrate': 20000,
                'videoResolution': '1920x1080'
            }

            # 2. Utiliser urlencode pour formater correctement la chaîne de requête
            query_string = urlencode(params)

            # 3. Construire le chemin final
            transcode_path = f'/video/:/transcode/universal/start.m3u8?{query_string}'

            # 4. Utiliser la méthode .url() du serveur qui gère le reste
            trailer_url = plex_server.url(transcode_path, includeToken=True)
            return trailer_url

    return None
