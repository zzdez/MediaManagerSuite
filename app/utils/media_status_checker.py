# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit
from .arr_client import search_radarr_by_title
from app.plex_editor.routes import get_user_specific_plex_server

def check_media_status(release_title):
    status_info = {'status': 'Indéterminé', 'details': release_title, 'badge_color': 'secondary'}
    try:
        parsed_info = guessit(release_title)
        if not parsed_info: return status_info

        title = parsed_info.get('title')
        year = parsed_info.get('year')
        media_type = parsed_info.get('type')

        if media_type == 'episode':
            # La logique pour les séries viendra plus tard
            status_info.update({'status': 'Série', 'details': f"{title}", 'badge_color': 'info'})
            return status_info

        elif media_type == 'movie':
            status_info['details'] = f"{title} ({year})" if year else title
            
            radarr_results = search_radarr_by_title(title)
            found_in_radarr = next((m for m in radarr_results if m.get('year') == year), None) if radarr_results else None
            
            if not found_in_radarr:
                status_info.update({'status': 'Non Trouvé (Radarr)', 'badge_color': 'dark'})
                return status_info
            
            user_plex_server = get_user_specific_plex_server()
            if user_plex_server:
                movie_libraries = [lib for lib in user_plex_server.library.sections() if lib.type == 'movie']
                found_in_plex = False
                
                # ### LOGIQUE DE RECHERCHE AMÉLIORÉE ###
                for library in movie_libraries:
                    # MÉTHODE 1 : Recherche par GUID (la plus fiable)
                    tmdb_id_str = str(found_in_radarr.get('tmdbId'))
                    if tmdb_id_str and library.search(guid=f"tmdb://{tmdb_id_str}"):
                        found_in_plex = True
                        break # Sort de la boucle dès qu'on a trouvé

                    # MÉTHODE 2 (Plan B) : Recherche par titre et année
                    if library.search(title=title, year=year):
                        found_in_plex = True
                        break # Sort de la boucle dès qu'on a trouvé

                if found_in_plex:
                    status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                    return status_info
            
            # Non trouvé dans Plex, on se base sur le statut Radarr
            if found_in_radarr.get('hasFile', False):
                status_info.update({'status': 'Statut Inconnu (Radarr/Plex)', 'badge_color': 'danger'})
            elif found_in_radarr.get('monitored', False):
                status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
            else:
                status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})
            
            return status_info

        return status_info
    except Exception as e:
        current_app.logger.error(f"Erreur dans check_media_status pour '{release_title}': {e}", exc_info=True)
        status_info.update({'status': 'Erreur Analyse', 'badge_color': 'danger'})
        return status_info