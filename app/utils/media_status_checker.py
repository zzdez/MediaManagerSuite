# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit
# On a de nouveau besoin de nos clients !
from .arr_client import search_radarr_by_title
# Importer aussi le client Plex sera nécessaire
from app.plex_editor.routes import get_user_specific_plex_server

def check_media_status(release_title):
    """
    Parses a release title using guessit and returns a status dict.
    """
    status_info = {'status': 'Indéterminé', 'details': release_title, 'badge_color': 'secondary'}
    
    try:
        # On utilise guessit() pour analyser le nom du fichier
        parsed_info = guessit(release_title)
        if not parsed_info:
            return status_info

        title = parsed_info.get('title')
        year = parsed_info.get('year')
        
        media_type = parsed_info.get('type')

        # --- Logique pour les SÉRIES ---
        if media_type == 'episode':
            status_info['status'] = 'Série'
            status_info['details'] = f"{title}"
            status_info['badge_color'] = 'info'
            return status_info

        # --- Logique pour les FILMS (VERSION FINALE AVEC PLEX) ---
        elif parsed_info.get('type') == 'movie':
            title = parsed_info.get('title')
            year = parsed_info.get('year')
            status_info['details'] = f"{title} ({year})" if year else title

            # 1. On cherche d'abord dans Radarr pour obtenir le TMDB ID
            radarr_results = search_radarr_by_title(title)
            found_in_radarr = None
            if radarr_results:
                for movie in radarr_results:
                    if movie.get('year') == year:
                        found_in_radarr = movie
                        break

            if not found_in_radarr or not found_in_radarr.get('tmdbId'):
                status_info.update({'status': 'Non Trouvé', 'badge_color': 'dark'})
                return status_info

            # 2. On a le TMDB ID. On cherche maintenant dans PLEX avec ce GUID.
            tmdb_id_str = str(found_in_radarr.get('tmdbId'))
            plex_guid = f"tmdb://{tmdb_id_str}"

            user_plex_server = get_user_specific_plex_server()
            if user_plex_server:
                # La fonction search() est efficace pour chercher par guid
                plex_results = user_plex_server.search(guid=plex_guid, libtype='movie')
                if plex_results:
                    # Le film existe dans Plex ! C'est le statut final.
                    status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                    return status_info

            # 3. Si on arrive ici, le film n'est pas dans Plex. On utilise le statut Radarr.
            if found_in_radarr.get('monitored', False):
                status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
            else:
                status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})

            return status_info

        return status_info

    except Exception as e:
        current_app.logger.error(f"Erreur dans check_media_status pour '{release_title}': {e}")
        status_info['status'] = 'Erreur Analyse'
        status_info['badge_color'] = 'danger'
        return status_info