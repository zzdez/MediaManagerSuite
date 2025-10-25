# app/utils/bulk_move_manager.py

import threading
import uuid
import time
import os
from datetime import datetime, timezone
from flask import current_app
from app.utils.arr_client import move_sonarr_series, move_radarr_movie, check_media_path_matches_root, check_import_event_in_history
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
                    start_time_utc = datetime.now(timezone.utc)
                    if media_type == 'sonarr':
                        success, error_message = move_sonarr_series(media_id, destination_folder)
                        if success:
                            error_message = self._poll_for_full_move_completion(task_id, 'sonarr', media_id, destination_folder, start_time_utc)
                            if error_message:
                                success = False

                    elif media_type == 'radarr':
                        success, error_message = move_radarr_movie(media_id, destination_folder)
                        if success:
                            error_message = self._poll_for_full_move_completion(task_id, 'radarr', media_id, destination_folder, start_time_utc)
                            if error_message:
                                success = False

                    if not success:
                        # FAILURE: Stop everything
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

            self._trigger_plex_scan(library_keys_to_scan)

    def _poll_for_full_move_completion(self, task_id, arr_type, media_id, destination_folder, start_time_utc):
        """
        Polls in a two-stage process to reliably confirm a move is complete.
        Stage 1: Waits for the path to be updated in the media object.
        Stage 2: Waits for a file import event in the history.
        """
        POLL_INTERVAL = 15  # seconds
        MAX_WAIT_TIME = 3600  # seconds (1 hour)
        start_time_poll = time.time()

        # --- Stage 1: Wait for path to update ---
        current_app.logger.info(f"[BulkMoveTask:{task_id}] Stage 1: Waiting for path update for {arr_type} ID {media_id}.")
        while time.time() - start_time_poll < MAX_WAIT_TIME:
            path_updated = False
            try:
                path_updated = check_media_path_matches_root(arr_type, media_id, destination_folder)
            except Exception as e:
                current_app.logger.error(f"[BulkMoveTask:{task_id}] Error in Stage 1 polling for {arr_type} ID {media_id}: {e}", exc_info=True)

            if path_updated:
                current_app.logger.info(f"[BulkMoveTask:{task_id}] Stage 1 PASSED: Path updated for {arr_type} ID {media_id}.")
                break  # Move to Stage 2

            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    base_message = task['message'].split(' - ')[0]
                    task['message'] = f"{base_message} - Initialisation du transfert..."
            time.sleep(POLL_INTERVAL)
        else: # Loop finished without break
            timeout_message = f"Stage 1 Timeout: La mise à jour du chemin pour {arr_type} ID {media_id} n'a pas été détectée."
            current_app.logger.error(f"[BulkMoveTask:{task_id}] {timeout_message}")
            return timeout_message

        # --- Stage 2: Wait for import event ---
        current_app.logger.info(f"[BulkMoveTask:{task_id}] Stage 2: Waiting for file import confirmation for {arr_type} ID {media_id}.")
        stage2_start_time = time.time()
        while time.time() - stage2_start_time < MAX_WAIT_TIME:
            import_confirmed = False
            try:
                import_confirmed = check_import_event_in_history(arr_type, media_id, start_time_utc)
            except Exception as e:
                current_app.logger.error(f"[BulkMoveTask:{task_id}] Error in Stage 2 polling for {arr_type} ID {media_id}: {e}", exc_info=True)

            if import_confirmed:
                current_app.logger.info(f"[BulkMoveTask:{task_id}] Stage 2 PASSED: Import event confirmed for {arr_type} ID {media_id}.")
                return None  # SUCCESS

            with self._lock:
                task = self._tasks.get(task_id)
                if task:
                    base_message = task['message'].split(' - ')[0]
                    task['message'] = f"{base_message} - Finalisation du transfert..."
            time.sleep(POLL_INTERVAL)
        else: # Loop finished without break
            timeout_message = f"Stage 2 Timeout: La confirmation de l'importation pour {arr_type} ID {media_id} n'a pas été détectée."
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

# Instance singleton
bulk_move_manager = BulkMoveManager()
