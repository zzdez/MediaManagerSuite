# app/utils/bulk_move_manager.py

import threading
import uuid
import time
import os
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
        Traite les items séquentiellement et s'arrête au premier échec.
        """
        with app.app_context():
            total_items = len(media_items)

            for i, item in enumerate(media_items):
                processed_count = i + 1
                media_id = item.get('media_id')
                media_title = item.get('title', f"Item ID: {media_id}") # Fallback au cas où
                media_type = item.get('media_type')
                destination_folder = item.get('destination')

                # Mettre à jour le statut pour indiquer ce qu'on fait
                with self._lock:
                    task = self._tasks[task_id]
                    task['status'] = 'running'
                    task['message'] = f"Déplacement de '{media_title}' ({processed_count}/{total_items})..."
                    task['progress'] = ((processed_count -1) / total_items) * 100
                    task['processed'] = processed_count - 1

                success = False
                error_message = "Type de média non supporté"

                try:
                    if media_type == 'sonarr':
                        success, error_message = move_sonarr_series(media_id, destination_folder)
                        if success:
                            error_message = self._poll_sonarr_path(task_id, media_id, destination_folder)
                            if error_message:
                                success = False

                    elif media_type == 'radarr':
                        success, error_message = move_radarr_movie(media_id, destination_folder)
                        if success:
                            # Succès de l'initiation, on commence le polling du chemin
                            error_message = self._poll_radarr_path(task_id, media_id, destination_folder)
                            if error_message:
                                success = False

                    if not success:
                        # ÉCHEC: On arrête tout
                        with self._lock:
                            task = self._tasks[task_id]
                            task['status'] = 'failed'
                            task['message'] = f"Échec du déplacement de '{media_title}'. Erreur: {error_message}"
                            task['failures'].append({"media_id": media_id, "error": error_message})
                        current_app.logger.error(f"[BulkMoveTask:{task_id}] Task failed on item {media_id} ('{media_title}'). Reason: {error_message}")
                        return # Arrête le thread

                    # SUCCÈS pour cet item
                    with self._lock:
                        task = self._tasks[task_id]
                        task['successes'].append(media_id)
                        task['processed'] = processed_count
                        task['progress'] = (processed_count / total_items) * 100

                except Exception as e:
                    # ÉCHEC CRITIQUE: On arrête tout
                    error_str = str(e)
                    current_app.logger.error(f"[BulkMoveTask:{task_id}] Task failed critically on item {media_id} ('{media_title}'): {error_str}", exc_info=True)
                    with self._lock:
                        task = self._tasks[task_id]
                        task['status'] = 'failed'
                        task['message'] = f"Erreur critique sur '{media_title}': {error_str}"
                        task['failures'].append({"media_id": media_id, "error": error_str})
                    return # Arrête le thread

                time.sleep(1) # Petite pause pour ne pas surcharger les APIs

            # Si on arrive ici, tout a réussi
            with self._lock:
                task = self._tasks[task_id]
                task['status'] = 'completed'
                task['message'] = f"Déplacement terminé avec succès pour {total_items} élément(s)."
                task['progress'] = 100
                current_app.logger.info(f"[BulkMoveTask:{task_id}] Completed successfully for all {total_items} items.")

    def _poll_radarr_path(self, task_id, movie_id, expected_path):
        """Vérifie que le chemin d'un film Radarr a bien été mis à jour."""
        from app.utils.arr_client import get_radarr_movie_by_id

        POLL_INTERVAL = 5
        MAX_WAIT_TIME = 300
        start_time = time.time()

        while time.time() - start_time < MAX_WAIT_TIME:
            movie_data = get_radarr_movie_by_id(movie_id)
            if not movie_data:
                return "Impossible de récupérer les informations du film depuis Radarr pendant la vérification."

            current_path_full = os.path.normpath(movie_data.get('path', '')).lower()
            target_root_path = os.path.normpath(expected_path).lower()

            if current_path_full.startswith(target_root_path):
                return None # Succès

            time.sleep(POLL_INTERVAL)

        return f"La vérification du changement de chemin pour Radarr a dépassé le temps maximum d'attente ({MAX_WAIT_TIME}s)."

    def _poll_sonarr_path(self, task_id, series_id, expected_path):
        """Vérifie que le chemin d'une série Sonarr a bien été mis à jour."""
        from app.utils.arr_client import get_sonarr_series_by_id

        POLL_INTERVAL = 5
        MAX_WAIT_TIME = 300
        start_time = time.time()

        while time.time() - start_time < MAX_WAIT_TIME:
            series_data = get_sonarr_series_by_id(series_id)
            if not series_data:
                return "Impossible de récupérer les informations de la série depuis Sonarr pendant la vérification."

            # Comparaison insensible à la casse et normalisée
            current_path = os.path.normpath(series_data.get('rootFolderPath', '')).lower()
            target_path = os.path.normpath(expected_path).lower()

            if current_path == target_path:
                return None # Succès, le chemin a été mis à jour

            time.sleep(POLL_INTERVAL)

        return f"La vérification du changement de chemin a dépassé le temps maximum d'attente ({MAX_WAIT_TIME}s)."

    def start_bulk_move(self, media_items, app):
        """
        Démarre une nouvelle tâche de déplacement en masse.

        Args:
            media_items (list): Liste de dicts, ex: [{'media_id': 123, 'title': 'Titre', 'destination': '/path'}]
            app: L'objet application Flask.

        Returns:
            str: L'ID de la tâche.
        """
        task_id = str(uuid.uuid4())
        with self._lock:
            self._tasks[task_id] = {
                'status': 'starting',
                'message': 'Initialisation de la tâche de déplacement en masse...',
                'total': len(media_items),
                'processed': 0,
                'progress': 0,
                'successes': [],
                'failures': [],
                'start_time': time.time(),
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
