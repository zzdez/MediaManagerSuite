# app/utils/media_status_checker.py
from flask import current_app
from guessit import guessit  # <<< On importe la bonne bibliothèque
# On retire les imports de arr_client pour l'instant, car on ne les utilise pas encore ici
# from .arr_client import get_radarr_movie_by_guid, get_sonarr_series_by_guid

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

        # --- Logique pour les FILMS ---
        elif media_type == 'movie':
            status_info['status'] = 'Film'
            status_info['details'] = f"{title} ({year})" if year else title
            status_info['badge_color'] = 'primary'
            return status_info

        # Si ce n'est ni un film ni une série, on retourne le statut par défaut
        return status_info

    except Exception as e:
        current_app.logger.error(f"Erreur dans check_media_status pour '{release_title}': {e}")
        status_info['status'] = 'Erreur Analyse'
        status_info['badge_color'] = 'danger'
        return status_info