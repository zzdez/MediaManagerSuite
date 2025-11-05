# -*- coding: utf-8 -*-
from plexapi.server import PlexServer

# --- Configuration ---
# Remplacez par l'URL de base de votre serveur Plex.
# Si Plex est sur la même machine, ceci est généralement correct.
PLEX_URL = 'http://localhost:32400'

# IMPORTANT : Remplacez par votre propre token d'authentification Plex.
# Voir : https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
PLEX_TOKEN = 'VOTRE_TOKEN_PLEX_ICI'

# Nom de la série à rechercher (dont les fichiers ont été supprimés)
SERIES_TITLE_TO_SEARCH = 'Acapulco'
# --- Fin de la configuration ---

def test_deleted_media_watch_status():
    """
    Se connecte au serveur Plex, recherche une série spécifique et affiche
    le statut de visionnage de ses épisodes.
    """
    if PLEX_TOKEN == 'VOTRE_TOKEN_PLEX_ICI':
        print("ERREUR : Veuillez remplacer 'VOTRE_TOKEN_PLEX_ICI' par votre token Plex dans le script.")
        return

    try:
        print(f"Connexion au serveur Plex à l'adresse : {PLEX_URL}...")
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        print("Connexion réussie !")

        print(f"\nRecherche de la série : '{SERIES_TITLE_TO_SEARCH}' dans toutes les bibliothèques...")

        # plex.search() recherche dans tout le serveur
        results = plex.search(SERIES_TITLE_TO_SEARCH, libtype='show')

        show = None
        if results:
            # On prend le premier résultat qui correspond exactement au titre
            for s in results:
                if s.title.lower() == SERIES_TITLE_TO_SEARCH.lower():
                    show = s
                    break

        if show:
            print(f"\n--- SÉRIE TROUVÉE : {show.title} (Année : {show.year}) ---")
            print(f"Statut de visionnage global de la série : {'Vue' if show.isWatched else 'Partiellement vue ou non vue'}")
            print(f"Nombre d'épisodes vus : {show.viewedLeafCount}")
            print(f"Nombre total d'épisodes : {show.leafCount}")
            print("-" * 50)

            print("\nDétail du statut de visionnage par épisode :")
            # On recharge la série pour être sûr d'avoir tous les détails des épisodes
            show.reload()
            for season in show.seasons():
                print(f"\n  > {season.title}")
                for episode in season.episodes():
                    status = "VU" if episode.isWatched else "NON VU"
                    print(f"    - {episode.title} (S{str(episode.seasonNumber).zfill(2)}E{str(episode.index).zfill(2)}) : {status}")

            print("\n" + "="*50)
            print("CONCLUSION : SUCCÈS ! Les informations de visionnage sont accessibles via l'API.")
            print("La Piste 2 est faisable.")
            print("="*50)

        else:
            print(f"\n--- AUCUNE SÉRIE TROUVÉE ---")
            print(f"La série '{SERIES_TITLE_TO_SEARCH}' n'a pas été trouvée sur le serveur Plex.")
            print("Cela peut signifier que Plex a supprimé l'entrée de sa base de données après la suppression des fichiers.")
            print("\n" + "="*50)
            print("CONCLUSION : ÉCHEC. Les informations ne semblent pas accessibles.")
            print("La Piste 2 n'est probablement pas faisable. Nous devrons envisager la Piste 1 ou 3.")
            print("="*50)

    except Exception as e:
        print(f"\n--- UNE ERREUR EST SURVENUE ---")
        print(f"Détails de l'erreur : {e}")
        print("\nVérifications possibles :")
        print("1. Le token Plex est-il correct ?")
        print("2. Le serveur Plex est-il bien en cours d'exécution à l'adresse indiquée ?")
        print("3. La machine a-t-elle accès au réseau local (si Plex n'est pas sur localhost) ?")

if __name__ == '__main__':
    test_deleted_media_watch_status()
