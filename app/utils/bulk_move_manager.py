# app/utils/bulk_move_manager.py
# -*- coding: utf-8 -*-

import uuid
import threading
import time
from flask import current_app

from .plex_client import get_plex_admin_server
from .arr_client import (
    get_sonarr_series_by_guid,
    get_radarr_movie_by_guid,
    move_sonarr_series,
    move_radarr_movie
)

class BulkMoveManager:
    def __init__(self):
        self.tasks = {}
        self.lock = threading.RLock()

    def _move_item(self, plex_rating_key, media_type, new_path):
        """
        Logique de déplacement pour un seul item.
        Retourne (True, "Message de succès") ou (False, "Message d'erreur").
        """
        try:
            plex_server = get_plex_admin_server()
            if not plex_server:
                return False, "Connexion au serveur Plex admin échouée."

            plex_item = plex_server.fetchItem(int(plex_rating_key))
            item_title = plex_item.title

            arr_item = None
            if media_type == 'sonarr':
                guid = next((g.id for g in plex_item.guids if 'tvdb' in g.id), None)
                if guid: arr_item = get_sonarr_series_by_guid(guid)
            elif media_type == 'radarr':
                guid = next((g.id for g in plex_item.guids if 'tmdb' in g.id), None)
                if guid: arr_item = get_radarr_movie_by_guid(guid)

            if not arr_item or not arr_item.get('id'):
                return False, f"Média non trouvé dans {media_type.capitalize()}."

            arr_item_id = arr_item.get('id')

            if media_type == 'sonarr':
                success, error = move_sonarr_series(arr_item_id, new_path)
            elif media_type == 'radarr':
                success, error = move_radarr_movie(arr_item_id, new_path)
            else:
                return False, "Type de média non supporté."

            if success:
                return True, f"'{item_title}' déplacé avec succès."
            else:
                return False, error or f"Échec du déplacement de '{item_title}' dans {media_type.capitalize()}."

        except Exception as e:
            current_app.logger.error(f"Erreur lors du déplacement de l'item {plex_rating_key}: {e}", exc_info=True)
            return False, f"Erreur inattendue : {str(e)}"

    def _run_bulk_move(self, task_id):
        with self.lock:
            task = self.tasks[task_id]
            app = task['app']
            items_to_move = task['items']
            task['status'] = 'in_progress'

        with app.app_context():
            total_items = len(items_to_move)

            for i, item in enumerate(items_to_move):
                with self.lock:
                    task['progress'] = {
                        'current': i + 1,
                        'total': total_items,
                        'item_title': item.get('title', 'N/A')
                    }

                success, message = self._move_item(item['rating_key'], item['media_type'], item['destination_path'])

                with self.lock:
                    if success:
                        task['results']['success'].append({'title': item.get('title'), 'message': message})
                    else:
                        task['results']['errors'].append({'title': item.get('title'), 'message': message})

                # Petite pause pour ne pas surcharger les API
                time.sleep(2)

            with self.lock:
                task['status'] = 'completed'
                task['progress'] = {
                    'current': total_items,
                    'total': total_items,
                    'item_title': 'Terminé'
                }

    def start_bulk_move(self, app, items, sonarr_path, radarr_path):
        task_id = str(uuid.uuid4())

        items_with_dest = []
        for item in items:
            dest_path = None
            if item['media_type'] == 'sonarr' and sonarr_path:
                dest_path = sonarr_path
            elif item['media_type'] == 'radarr' and radarr_path:
                dest_path = radarr_path

            if dest_path:
                items_with_dest.append({
                    'rating_key': item['rating_key'],
                    'media_type': item['media_type'],
                    'title': item['title'],
                    'destination_path': dest_path
                })

        if not items_with_dest:
            return None # Aucun item à déplacer

        with self.lock:
            self.tasks[task_id] = {
                'id': task_id,
                'app': app,
                'status': 'pending',
                'items': items_with_dest,
                'progress': {
                    'current': 0,
                    'total': len(items_with_dest),
                    'item_title': 'Initialisation...'
                },
                'results': {
                    'success': [],
                    'errors': []
                }
            }

        # Démarrer le thread
        thread = threading.Thread(target=self._run_bulk_move, args=(task_id,))
        thread.daemon = True
        thread.start()

        return task_id

    def get_task_status(self, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None

            # Créer une copie du dictionnaire de la tâche sans l'objet 'app'
            # pour éviter les erreurs de sérialisation JSON.
            task_for_json = {key: value for key, value in task.items() if key != 'app'}
            return task_for_json

# Instance globale
bulk_move_manager = BulkMoveManager()
