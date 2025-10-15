# app/utils/media_info_manager.py
import logging
from flask import current_app

from app.utils.arr_client import get_all_sonarr_series, get_all_radarr_movies
from app.utils.plex_client import get_plex_admin_server, find_plex_media_by_external_id
from app.utils.tmdb_client import TheMovieDBClient

logger = logging.getLogger(__name__)

class MediaInfoManager:
    def __init__(self):
        self._sonarr_series = None
        self._radarr_movies = None
        self.tmdb_client = None
        self.plex_server = None

    def _init_clients_if_needed(self):
        if self.tmdb_client is None:
            try:
                self.tmdb_client = TheMovieDBClient()
            except ValueError:
                logger.warning("Client TMDB non initialisé (clé API manquante).")
        if self.plex_server is None:
            self.plex_server = get_plex_admin_server()

    def _load_libraries(self):
        if self._sonarr_series is None: self._sonarr_series = get_all_sonarr_series() or []
        if self._radarr_movies is None: self._radarr_movies = get_all_radarr_movies() or []

    def get_media_details(self, media_type, external_id):
        logger.info(f"Début du traitement pour {media_type}_{external_id}")
        self._init_clients_if_needed()
        self._load_libraries()

        tmdb_id = None
        tvdb_id = None
        tmdb_details = {}

        if media_type == 'tv':
            tvdb_id = external_id
            tmdb_details = self._get_tmdb_details_from_tvdb(tvdb_id)
            if tmdb_details:
                tmdb_id = tmdb_details.get('id')
        else: # movie
            tmdb_id = external_id
            tmdb_details = self._get_tmdb_details_from_tmdb(media_type, tmdb_id)

        details = {
            'plex_status': self._get_plex_status(media_type, tmdb_id, tvdb_id),
            'production_status': {"status": tmdb_details.get('status', 'Inconnu'), "total_seasons": tmdb_details.get('number_of_seasons'), "total_episodes": tmdb_details.get('number_of_episodes')},
        }

        if media_type == 'tv':
            details['sonarr_status'] = self._get_sonarr_status(tmdb_id)
            details['radarr_status'] = {"present": False}
        else: # movie
            details['radarr_status'] = self._get_radarr_status(tmdb_id)
            details['sonarr_status'] = {"present": False}

        logger.info(f"Détails finaux pour {media_type}_{external_id}: {details}")
        return details

    def _get_tmdb_details_from_tvdb(self, tvdb_id):
        if not self.tmdb_client: return {}
        try:
            return self.tmdb_client.find_series_by_tvdb_id(tvdb_id) or {}
        except Exception as e:
            logger.error(f"Erreur de traduction TVDB->TMDB pour {tvdb_id}: {e}")
            return {}

    def _get_tmdb_details_from_tmdb(self, media_type, tmdb_id):
        if not self.tmdb_client: return {}
        try:
            return (self.tmdb_client.get_series_details(tmdb_id) if media_type == 'tv' else self.tmdb_client.get_movie_details(tmdb_id)) or {}
        except Exception as e:
            logger.error(f"Erreur TMDB pour {media_type}_{tmdb_id}: {e}")
            return {}

    def _get_sonarr_status(self, tmdb_id):
        if self._sonarr_series is None: return {"present": False}
        if not tmdb_id: return {"present": False}
        for series in self._sonarr_series:
            if series.get('tmdbId') == tmdb_id:
                stats = series.get('statistics', {})
                return {"present": True, "monitored": series.get('monitored', False), "episodes_file_count": stats.get('episodeFileCount', 0), "episodes_count": stats.get('episodeCount', 0)}
        return {"present": False}

    def _get_radarr_status(self, tmdb_id):
        if self._radarr_movies is None: return {"present": False}
        if not tmdb_id: return {"present": False}
        for movie in self._radarr_movies:
            if movie.get('tmdbId') == tmdb_id:
                return {"present": True, "monitored": movie.get('monitored', False), "has_file": movie.get('hasFile', False)}
        return {"present": False}

    def _get_plex_status(self, media_type, tmdb_id, tvdb_id):
        if not self.plex_server: return {"present": False}

        guid = f"tvdb://{tvdb_id}" if media_type == 'tv' and tvdb_id else f"tmdb://{tmdb_id}"
        libtype = 'show' if media_type == 'tv' else 'movie'

        plex_media = find_plex_media_by_external_id(self.plex_server, guid, libtype)
        if not plex_media: return {"present": False}

        physical_presence = any(hasattr(part, 'file') and part.file for media in plex_media.media for part in media.parts)

        watched_episodes_str = f"{plex_media.viewedLeafCount}/{plex_media.leafCount}" if media_type == 'tv' else None

        return {
            "present": True,
            "physical_presence": physical_presence,
            "is_watched": plex_media.isWatched,
            "seen_via_tag": any(tag.tag.lower() == 'vu' for tag in getattr(plex_media, 'tags', [])),
            "watched_episodes": watched_episodes_str
        }

media_info_manager = MediaInfoManager()
