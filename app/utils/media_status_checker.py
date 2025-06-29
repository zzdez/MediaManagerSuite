# app/utils/media_status_checker.py
from flask import current_app
from parseit import parse
from .arr_client import get_radarr_movie_by_guid, get_sonarr_series_by_guid

def check_media_status(release_title):
    """
    Parses a release title, checks its status, and returns a status dict.
    """
    status_info = {'status': 'Indéterminé', 'details': release_title, 'badge_color': 'secondary'}

    try:
        parsed_info = parse(release_title)
        if not parsed_info:
            return status_info

        title = parsed_info.get('title')
        year = parsed_info.get('year')

        # --- Logique pour les SÉRIES ---
        if parsed_info.get('type') == 'episode':
            # Pour l'instant, on se contente d'une vérification basique.
            # La logique de recherche par TVDB ID sera ajoutée plus tard.
            status_info['status'] = 'Série'
            status_info['details'] = f"{title}"
            status_info['badge_color'] = 'info'
            return status_info

        # --- Logique pour les FILMS ---
        elif parsed_info.get('type') == 'movie':
            # TODO: Implémenter la recherche dans Radarr et Plex ici.
            # Pour cette étape, on se contente d'identifier le film.
            status_info['status'] = 'Film'
            status_info['details'] = f"{title} ({year})" if year else title
            status_info['badge_color'] = 'primary'
            return status_info

        return status_info

    except Exception as e:
        current_app.logger.error(f"Erreur dans check_media_status pour '{release_title}': {e}")
        status_info['status'] = 'Erreur Analyse'
        status_info['badge_color'] = 'danger'
        return status_info
