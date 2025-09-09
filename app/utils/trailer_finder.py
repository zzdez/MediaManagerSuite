from googleapiclient.discovery import build

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

def find_youtube_trailer(search_queries, api_key):
    """
    Effectue des recherches sur YouTube avec une liste de requêtes
    et retourne la première liste de résultats non vide.
    """
    if not api_key:
        print("AVERTISSEMENT: Aucune clé API YouTube n'a été fournie.")
        return []

    try:
        youtube = build('youtube', 'v3', developerKey=api_key, cache_discovery=False)

        for query in search_queries:
            print(f"DEBUG: Recherche YouTube avec la requête : '{query}'")
            request = youtube.search().list(
                q=query,
                part='snippet',
                type='video',
                maxResults=5,
                relevanceLanguage='fr' # On spécifie la langue
            )
            response = request.execute()

            if response.get('items'):
                print(f"INFO: Trouvé {len(response['items'])} résultats pour la requête '{query}'.")
                results = []
                for item in response['items']:
                    results.append({
                        'videoId': item['id']['videoId'],
                        'title': item['snippet']['title'],
                        'thumbnail': item['snippet']['thumbnails']['high']['url'],
                        'channel': item['snippet']['channelTitle']
                    })
                return results # On retourne dès qu'on a des résultats

        print("INFO: Aucun résultat trouvé pour toutes les requêtes de recherche.")
        return []

    except Exception as e:
        print(f"ERREUR lors de la recherche sur YouTube : {e}")
        return [] # Toujours retourner une liste vide en cas d'erreur
