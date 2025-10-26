# app/utils/bulk_move_manager.py

import threading
import uuid
import time
import os
from flask import current_app
from app.utils.arr_client import move_sonarr_series, move_radarr_movie, get_sonarr_series_by_id, get_radarr_movie_by_id
from app.utils.plex_client import get_plex_admin_server

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

    def _trigger_plex_scan(self, library_keys):
        """Déclenche un scan pour une liste de clés de bibliothèque Plex."""
        if not library_keys:
            current_app.logger.info("[BulkMoveTask] No library keys provided for scanning.")
            return

        try:
            plex_server = get_plex_admin_server()
            if not plex_server:
                current_app.logger.error("[BulkMoveTask] Could not get Plex admin server to trigger scan.")
                return

            scanned_libs = []
            for key in library_keys:
                if key:
                    try:
                        library = plex_server.library.sectionByID(int(key))
                        library.update()
                        scanned_libs.append(library.title)
                    except Exception as e_lib:
                        current_app.logger.error(f"[BulkMoveTask] Failed to scan library key {key}: {e_lib}")
            current_app.logger.info(f"[BulkMoveTask] Triggered Plex scan for libraries: {', '.join(scanned_libs)}")
        except Exception as e:
            current_app.logger.error(f"[BulkMoveTask] An error occurred during Plex scan initiation: {e}", exc_info=True)

    def _process_move_queue(self, task_id, media_items, app):
        """
        Méthode exécutée en arrière-plan pour traiter la file de déplacement.
        Traite les items séquentiellement et s'arrête au premier échec.
        """
        with app.app_context():
            total_items = len(media_items)
            library_keys_to_scan = {item.get('library_key') for item in media_items}

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
                    # --- Get source path BEFORE the move ---
                    source_path = None
                    if media_type == 'sonarr':
                        media_details = get_sonarr_series_by_id(media_id)
                        source_path = media_details.get('path') if media_details else None
                    elif media_type == 'radarr':
                        media_details = get_radarr_movie_by_id(media_id)
                        source_path = media_details.get('path') if media_details else None

                    if not source_path:
                        raise Exception(f"Impossible de récupérer le chemin source pour {media_type} ID {media_id}.")

                    # --- Initiate the move ---
                    if media_type == 'sonarr':
                        success, error_message = move_sonarr_series(media_id, destination_folder)
                        if success:
                            error_message = self._poll_for_source_path_disappearance(task_id, source_path)
                            if error_message:
                                success = False

                    elif media_type == 'radarr':
                        success, error_message = move_radarr_movie(media_id, destination_folder)
                        if success:
                            error_message = self._poll_for_source_path_disappearance(task_id, source_path)
                            if error_message:
                                success = False

                    if not success:
                        # FAILURE: Stop everything
                        with self._lock:
                            task = self._tasks[task_id]
                            task['status'] = 'failed'
                            task['message'] = f"Échec du déplacement de '{media_title}'. Erreur: {error_message}"
                            task['failures'].append({
                                "media_id": media_id,
                                "ratingKey": item.get('plex_rating_key'), # Utiliser la bonne clé
                                "error": error_message
                            })
                        current_app.logger.error(f"[BulkMoveTask:{task_id}] Task failed on item {media_id} ('{media_title}'). Reason: {error_message}")
                        return # Arrête le thread

                    # SUCCÈS pour cet item : récupérer le nouveau chemin
                    new_path = "Non trouvé"
                    try:
                        if media_type == 'sonarr':
                            media_details = get_sonarr_series_by_id(media_id)
                            new_path = media_details.get('path') if media_details else "N/A"
                        elif media_type == 'radarr':
                            media_details = get_radarr_movie_by_id(media_id)
                            new_path = media_details.get('path') if media_details else "N/A"
                    except Exception as e_path:
                        current_app.logger.warning(f"[BulkMoveTask:{task_id}] Could not fetch new path for {media_type} ID {media_id}: {e_path}")
                        new_path = "Erreur de récupération"

                    with self._lock:
                        task = self._tasks[task_id]
                        task['successes'].append(media_id)
                        task['completed_for_ui'].append({
                            'ratingKey': item.get('plex_rating_key'), # Utiliser la bonne clé
                            'newPath': new_path
                        })
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

            self._trigger_plex_scan(library_keys_to_scan)

    def _poll_for_source_path_disappearance(self, task_id, source_path):
        """
        Polls the filesystem to wait for the source path to be deleted.
        This is the definitive signal that a 'move' operation has completed.
        """
        POLL_INTERVAL = 5  # seconds
        # Set a very generous timeout, e.g., 2 hours, for massive files on slow disks.
        MAX_WAIT_TIME = 7200  # seconds
        start_time_poll = time.time()

        current_app.logger.info(f"[BulkMoveTask:{task_id}] Waiting for source path '{source_path}' to disappear...")

        while time.time() - start_time_poll < MAX_WAIT_TIME:
            if not os.path.exists(source_path):
                current_app.logger.info(f"[BulkMoveTask:{task_id}] Source path '{source_path}' has disappeared. Move confirmed.")
                return None  # SUCCESS

            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    base_message = task['message'].split(' - ')[0]
                    task['message'] = f"{base_message} - Transfert physique en cours..."
            time.sleep(POLL_INTERVAL)

        timeout_message = f"Le suivi du déplacement pour le chemin '{source_path}' a dépassé le temps maximum d'attente ({MAX_WAIT_TIME}s)."
        current_app.logger.error(f"[BulkMoveTask:{task_id}] {timeout_message}")
        return timeout_message


    def is_task_running(self):
        """Vérifie si une tâche est déjà en cours."""
        with self._lock:
            for task_id, task_details in self._tasks.items():
                if task_details.get('status') in ['starting', 'running']:
                    return True
        return False

    def start_bulk_move(self, media_items, app):
        """
        Démarre une nouvelle tâche de déplacement en masse.

        Args:
            media_items (list): Liste de dicts, ex: [{'media_id': 123, 'title': 'Titre', 'destination': '/path'}]
            app: L'objet application Flask.

        Returns:
            tuple: (task_id, error_message). L'un des deux sera None.
        """
        if self.is_task_running():
            current_app.logger.warning("Attempted to start a new bulk move while another is already running.")
            return None, "Une tâche de déplacement est déjà en cours. Veuillez attendre sa fin."

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
                'completed_for_ui': [],
                'start_time': time.time(),
                'app': app # Stocker l'app pour le thread
            }

        thread = threading.Thread(target=self._process_move_queue, args=(task_id, media_items, app))
        thread.daemon = True
        thread.start()

        current_app.logger.info(f"Started bulk move task {task_id} for {len(media_items)} items.")
        return task_id, None

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

    def get_task_status_with_updates(self, task_id):
        """
        Récupère l'état d'une tâche et la liste des items récemment complétés,
        puis vide la liste des complétés pour éviter les renvois multiples.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            # 1. Copier les mises à jour et les échecs
            updates_for_ui = list(task.get('completed_for_ui', []))
            failures_for_ui = list(task.get('failures', [])) # On renvoie toujours tous les échecs

            # 2. Vider la liste des mises à jour UI dans l'objet de tâche
            task['completed_for_ui'] = []

            # 3. Préparer une copie du statut à renvoyer
            status_to_return = task.copy()
            status_to_return.pop('app', None)

            # 4. Ajouter les listes copiées à la réponse
            status_to_return['updates_for_ui'] = updates_for_ui
            status_to_return['failures_for_ui'] = failures_for_ui

            return status_to_return

# Instance singleton
bulk_move_manager = BulkMoveManager()
