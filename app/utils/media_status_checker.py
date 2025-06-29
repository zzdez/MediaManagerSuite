# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit
from .arr_client import search_radarr_by_title, search_sonarr_by_title, get_sonarr_episode_files
from app.plex_editor.routes import get_user_specific_plex_server
from plexapi.exceptions import NotFound

def check_media_status(release_title):
    status_info = {'status': 'Indéterminé', 'details': release_title, 'badge_color': 'secondary'}
    try:
        parsed_info = guessit(release_title)
        if not parsed_info: return status_info

        title = parsed_info.get('title')
        year = parsed_info.get('year')
        media_type = parsed_info.get('type')

        # --- Logique pour les SÉRIES (AMÉLIORÉE) ---
        if media_type == 'episode':
            title = parsed_info.get('title')
            season_num = parsed_info.get('season')
            episode_num = parsed_info.get('episode')
            status_info['details'] = f"{title} - S{season_num:02d}E{episode_num:02d}"

            # 1. On cherche la série dans Sonarr par son titre
            sonarr_results = search_sonarr_by_title(title)
            if not sonarr_results:
                status_info.update({'status': 'Série non trouvée', 'badge_color': 'dark'})
                return status_info

            sonarr_series = sonarr_results[0] # On prend le premier résultat
            # series_id_sonarr = sonarr_series['id'] # Non utilisé directement dans la suite du code fourni

            # 2. On vérifie si l'épisode est dans PLEX
            user_plex_server = get_user_specific_plex_server()
            if user_plex_server:
                # On cherche la série dans Plex par son TVDB ID
                tvdb_id = sonarr_series.get('tvdbId')
                if tvdb_id: # S'assurer qu'on a un TVDB ID
                    plex_series = next((s for lib in user_plex_server.library.sections() if lib.type == 'show' for s in lib.search(guid=f"tvdb://{tvdb_id}")), None)

                    if plex_series:
                        # On a trouvé la série, on cherche l'épisode spécifique
                        try:
                            # Vérifier que season_num et episode_num ne sont pas None
                            if season_num is not None and episode_num is not None:
                                episode = plex_series.episode(season=season_num, episode=episode_num)
                                if episode: # L'épisode existe dans la base de données Plex
                                    status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                                    return status_info
                            else:
                                current_app.logger.warning(f"Numéro de saison ou d'épisode manquant pour {title} lors de la recherche Plex.")
                        except NotFound:
                            # L'épisode n'est pas dans Plex
                            pass
                else:
                    current_app.logger.warning(f"TVDB ID manquant pour la série Sonarr : {title}")


            # 3. Non trouvé dans Plex, on se base sur le statut Sonarr
            # (Il serait bon de vérifier ici si l'épisode spécifique a un fichier dans Sonarr)
            # Pour l'instant, on se base sur le statut "monitored" de la série.
            # Une amélioration future pourrait utiliser get_sonarr_episode_files pour plus de précision.
            if sonarr_series.get('monitored', False):
                status_info.update({'status': 'Manquant (Surveillé)', 'badge_color': 'warning'})
            else:
                status_info.update({'status': 'Non Surveillé', 'badge_color': 'secondary'})

            return status_info

        elif media_type == 'movie':
            status_info['details'] = f"{title} ({year})" if year else title

            # 1. On cherche dans Radarr
            radarr_results = search_radarr_by_title(title)
            found_in_radarr = next((m for m in radarr_results if m.get('year') == year), None) if radarr_results else None

            if not found_in_radarr or not found_in_radarr.get('tmdbId'):
                status_info.update({'status': 'Non Trouvé (Radarr)', 'badge_color': 'dark'})
                return status_info

            # 2. On a le TMDB ID, on cherche dans PLEX
            tmdb_id_str = str(found_in_radarr.get('tmdbId'))
            user_plex_server = get_user_specific_plex_server()
            if user_plex_server:
                # ### CORRECTION DE LA LOGIQUE DE RECHERCHE ###
                # On ne peut pas chercher par GUID sur tout le serveur.
                # On doit itérer sur les bibliothèques de films.
                movie_libraries = [lib for lib in user_plex_server.library.sections() if lib.type == 'movie']
                for library in movie_libraries:
                    # On utilise library.search() qui, elle, accepte le filtre par guid
                    plex_results = library.search(guid=f"tmdb://{tmdb_id_str}")
                    if plex_results:
                        status_info.update({'status': 'Déjà Présent', 'badge_color': 'success'})
                        return status_info # Trouvé ! On arrête tout.

            # 3. Non trouvé dans Plex, on se base sur le statut Radarr
            if found_in_radarr.get('hasFile', False):
                # Radarr pense avoir le fichier, mais il n'est pas dans Plex. Problème de matching ?
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