# app/utils/bulk_move_manager.py

import threading
import uuid
import time
from flask import current_app
from app.utils.arr_client import move_sonarr_series, move_radarr_movie

class BulkMoveManager:
    _instance = None
    _lock = threading.RLock()
    _tasks = {} # Dictionnaire pour suivre l'état de chaque tâche de masse

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(BulkMoveManager, cls).__new__(cls)
        return cls._instance

    def _process_move_queue(self, task_id, media_items, app):
        """
        Méthode exécutée en arrière-plan pour traiter la file de déplacement.
        Nécessite l'objet 'app' pour le contexte d'application.
        """
        with app.app_context():
            total_items = len(media_items)
            processed_count = 0

            for item in media_items:
                media_id = item.get('media_id')
                media_type = item.get('media_type')
                destination_folder = item.get('destination')
                success = False
                error_message = "Type de média non supporté"

                try:
                    if media_type == 'sonarr':
                        success, error_message = move_sonarr_series(media_id, destination_folder)
                    elif media_type == 'radarr':
                        success, error_message = move_radarr_movie(media_id, destination_folder)

                    with self._lock:
                        task = self._tasks[task_id]
                        if success:
                            task['successes'].append(media_id)
                        else:
                            task['failures'].append({"media_id": media_id, "error": "Move command failed"})

                except Exception as e:
                    current_app.logger.error(f"[BulkMoveTask:{task_id}] Failed to move media ID {media_id}: {e}")
                    with self._lock:
                        task = self._tasks[task_id]
                        task['failures'].append({"media_id": media_id, "error": str(e)})

                finally:
                    processed_count += 1
                    with self._lock:
                        task = self._tasks[task_id]
                        task['progress'] = (processed_count / total_items) * 100
                        task['processed'] = processed_count

                    time.sleep(1) # Petite pause pour ne pas surcharger les APIs

            with self._lock:
                self._tasks[task_id]['status'] = 'completed'
                current_app.logger.info(f"[BulkMoveTask:{task_id}] Completed. Success: {len(self._tasks[task_id]['successes'])}, Failures: {len(self._tasks[task_id]['failures'])}.")

    def start_bulk_move(self, media_items, app):
        """
        Démarre une nouvelle tâche de déplacement en masse.

        Args:
            media_items (list): Une liste de dictionnaires, ex: [{'media_id': 123, 'destination': '/path/to/dest'}]
            app: L'objet application Flask (nécessaire pour le contexte).

        Returns:
            str: L'ID de la tâche.
        """
        task_id = str(uuid.uuid4())
        with self._lock:
            self._tasks[task_id] = {
                'status': 'running',
                'total': len(media_items),
                'processed': 0,
                'progress': 0,
                'successes': [],
                'failures': [],
                'app': app # Stocker l'app pour le thread
            }

        thread = threading.Thread(target=self._process_move_queue, args=(task_id, media_items, app))
        thread.daemon = True
        thread.start()

        current_app.logger.info(f"Started bulk move task {task_id} for {len(media_items)} items.")
        return task_id

    def get_task_status(self, task_id):
        """
        Récupère l'état d'une tâche de déplacement en masse.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            # On ne veut pas renvoyer l'objet 'app' dans le JSON
            status_copy = task.copy()
            status_copy.pop('app', None)
            return status_copy

# Instance singleton
bulk_move_manager = BulkMoveManager()
