# -*- coding: utf-8 -*-
from plexapi.server import PlexServer

def run_plex_test(plex_url, plex_token, series_title):
    """
    Se connecte au serveur Plex, recherche une série et retourne les résultats sous forme de chaîne de caractères.
    """
    output_lines = []

    if not plex_token or plex_token == 'VOTRE_TOKEN_PLEX_ICI':
        output_lines.append("ERREUR : Le token Plex n'a pas été configuré dans le fichier 'plex_api_test.py'.")
        return "\n".join(output_lines)

    try:
        output_lines.append(f"Tentative de connexion au serveur Plex à l'adresse : {plex_url}...")
        plex = PlexServer(plex_url, plex_token)
        output_lines.append("Connexion réussie !")

        output_lines.append(f"\nRecherche de la série : '{series_title}'...")
        results = plex.search(series_title, libtype='show')

        show = None
        if results:
            for s in results:
                if s.title.lower() == series_title.lower():
                    show = s
                    break

        if show:
            output_lines.append(f"\n--- SÉRIE TROUVÉE : {show.title} (Année : {show.year}) ---")
            show.reload() # Recharger pour avoir les infos les plus récentes

            output_lines.append(f"Statut de visionnage global : {'Vue' if show.isWatched else 'Partiellement vue ou non vue'}")
            output_lines.append(f"Nombre d'épisodes vus : {show.viewedLeafCount}")
            output_lines.append(f"Nombre total d'épisodes : {show.leafCount}")
            output_lines.append("-" * 50)

            output_lines.append("\nDétail du statut de visionnage par épisode :")
            for season in show.seasons():
                output_lines.append(f"\n  > {season.title}")
                for episode in season.episodes():
                    status = "VU" if episode.isWatched else "NON VU"
                    output_lines.append(f"    - {episode.title} (S{str(episode.seasonNumber).zfill(2)}E{str(episode.index).zfill(2)}) : {status}")

            output_lines.append("\n" + "="*50)
            output_lines.append("CONCLUSION : SUCCÈS ! Les informations de visionnage sont accessibles.")
            output_lines.append("La Piste 2 est confirmée comme étant faisable.")
            output_lines.append("="*50)
        else:
            output_lines.append(f"\n--- AUCUNE SÉRIE TROUVÉE ---")
            output_lines.append(f"La série '{series_title}' n'a pas été trouvée.")
            output_lines.append("Ceci implique que Plex a nettoyé l'entrée de sa base de données.")
            output_lines.append("\n" + "="*50)
            output_lines.append("CONCLUSION : ÉCHEC. La Piste 2 n'est pas réalisable dans ces conditions.")
            output_lines.append("="*50)

    except Exception as e:
        output_lines.append(f"\n--- UNE ERREUR EST SURVENUE ---")
        output_lines.append(f"Détails de l'erreur : {e}")
        output_lines.append("\nVérifiez que le token et l'URL du serveur Plex sont corrects.")

    return "\n".join(output_lines)
