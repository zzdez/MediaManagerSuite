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
        if self._sonarr_series is None:
            self._sonarr_series = get_all_sonarr_series() or []
        if self._radarr_movies is None:
            self._radarr_movies = get_all_radarr_movies() or []

    def get_media_details(self, media_type, tmdb_id):
        self._init_clients_if_needed()
        self._load_libraries()

        tmdb_details = self._get_tmdb_details(media_type, tmdb_id)
        tvdb_id = tmdb_details.get('tvdb_id') if media_type == 'tv' else None

        details = {
            'sonarr_status': self._get_sonarr_status(tmdb_id),
            'radarr_status': self._get_radarr_status(tmdb_id),
            'plex_status': self._get_plex_status(media_type, tmdb_id, tvdb_id),
            'production_status': {"status": tmdb_details.get('status', 'Inconnu')},
        }
        return details

    def _get_tmdb_details(self, media_type, tmdb_id):
        if not self.tmdb_client:
            return {}
        try:
            if media_type == 'tv':
                return self.tmdb_client.get_series_details(tmdb_id) or {}
            else:
                return self.tmdb_client.get_movie_details(tmdb_id) or {}
        except Exception as e:
            logger.error(f"Erreur TMDB pour {media_type}_{tmdb_id}: {e}")
            return {}

    def _get_sonarr_status(self, tmdb_id):
        if self._sonarr_series is None: return {"present": False, "message": "Bibliothèque Sonarr non chargée."}
        for series in self._sonarr_series:
            if series.get('tmdbId') == tmdb_id:
                return {"present": True, "monitored": series.get('monitored', False), "has_file": series.get('statistics', {}).get('episodeFileCount', 0) > 0}
        return {"present": False}

    def _get_radarr_status(self, tmdb_id):
        if self._radarr_movies is None: return {"present": False, "message": "Bibliothèque Radarr non chargée."}
        for movie in self._radarr_movies:
            if movie.get('tmdbId') == tmdb_id:
                return {"present": True, "monitored": movie.get('monitored', False), "has_file": movie.get('hasFile', False)}
        return {"present": False}

    def _get_plex_status(self, media_type, tmdb_id, tvdb_id):
        if not self.plex_server:
            return {"present": False, "message": "Serveur Plex non disponible."}

        if media_type == 'tv':
            if not tvdb_id:
                return {"present": False, "message": "ID TVDB manquant pour la recherche Plex."}
            guid = f"tvdb://{tvdb_id}"
            libtype = 'show'
        else:
            guid = f"tmdb://{tmdb_id}"
            libtype = 'movie'

        plex_media = find_plex_media_by_external_id(self.plex_server, guid, libtype)

        if not plex_media:
            return {"present": False}

        is_watched = plex_media.isWatched
        physical_presence = any(part.file for media in plex_media.media for part in media.parts if hasattr(part, 'file'))
        seen_via_tag = any(tag.tag.lower() == 'vu' for tag in getattr(plex_media, 'tags', []))

        watched_episodes_str = None
        if media_type == 'tv':
            watched_episodes_str = f"{plex_media.viewedLeafCount}/{plex_media.leafCount}"

        return {
            "present": True,
            "physical_presence": physical_presence,
            "is_watched": is_watched,
            "seen_via_tag": seen_via_tag,
            "watched_episodes": watched_episodes_str
        }

media_info_manager = MediaInfoManager()
