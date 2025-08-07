from googleapiclient.discovery import build
from app import config # Importe notre configuration

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

def find_youtube_trailer(title, year, media_type='movie'):
    """
    Recherche une bande-annonce sur YouTube en suivant une priorité de langues.
    """
    if not config.YOUTUBE_API_KEY:
        print("AVERTISSEMENT: La clé YOUTUBE_API_KEY n'est pas configurée.")
        return None

    try:
        youtube = build('youtube', 'v3', developerKey=config.YOUTUBE_API_KEY, cache_discovery=False)

        # Liste des requêtes par ordre de priorité
        search_queries = [
            f'"{title}" {year} bande annonce officielle vf',
            f'"{title}" {year} trailer officiel vostfr',
            f'"{title}" official trailer {year}'
        ]

        for query in search_queries:
            print(f"DEBUG: Recherche YouTube avec la requête : {query}")
            request = youtube.search().list(
                q=query,
                part='snippet',
                type='video',
                maxResults=3 # On prend 3 résultats pour trouver le plus pertinent
            )
            response = request.execute()

            if response.get('items'):
                # Idéalement, on ajouterait ici une logique pour choisir la meilleure vidéo
                # (chaîne officielle, plus de vues, etc.). Pour l'instant, on prend la première.
                video_id = response['items'][0]['id']['videoId']
                print(f"DEBUG: Vidéo trouvée : {video_id}")
                return f"https://www.youtube.com/watch?v={video_id}"

    except Exception as e:
        print(f"ERREUR lors de la recherche sur YouTube : {e}")
        return None

    print("DEBUG: Aucune vidéo trouvée sur YouTube.")
    return None

def get_trailer(title, year, media_type, plex_item=None, plex_server=None):
    """
    Fonction maîtresse pour trouver une bande-annonce en utilisant plusieurs sources.
    """
    # Étage 1 : Recherche dans Plex (si possible)
    if plex_item and plex_server:
        plex_trailer_url = find_plex_trailer(plex_item, plex_server)
        if plex_trailer_url:
            print(f"DEBUG: Bande-annonce trouvée via Plex pour '{title}'.")
            return plex_trailer_url

    # Étage 2 : Recherche sur YouTube
    youtube_trailer_url = find_youtube_trailer(title, year, media_type)
    if youtube_trailer_url:
        print(f"DEBUG: Bande-annonce trouvée via YouTube pour '{title}'.")
        return youtube_trailer_url

    # Aucun trailer trouvé
    return None
