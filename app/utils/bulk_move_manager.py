
# app/utils/bulk_move_manager.py

import threading
import uuid
from flask import current_app
from .move_manager import MoveManager

class BulkMoveManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(BulkMoveManager, cls).__new__(cls)
                cls._instance.tasks = {}
        return cls._instance

    def start_bulk_move(self, movie_ids, radarr_path, series_ids, sonarr_path, app):
        task_id = str(uuid.uuid4())
        task_info = {
            'status': 'starting',
            'progress': 0,
            'report': 'Initialisation...',
            'total_items': len(movie_ids) + len(series_ids),
            'processed_items': 0,
            'success_count': 0,
            'failure_count': 0,
            'app': app # Store app context for the thread
        }
        self.tasks[task_id] = task_info

        thread = threading.Thread(target=self._run_bulk_move, args=(task_id, movie_ids, radarr_path, series_ids, sonarr_path))
        thread.daemon = True
        thread.start()
        return task_id

    def get_task_status(self, task_id):
        task = self.tasks.get(task_id)
        if not task:
            return {'status': 'not_found', 'message': 'Tâche non trouvée.'}

        # Renvoyer une copie sans l'objet 'app' pour éviter les erreurs de sérialisation JSON
        status_copy = task.copy()
        status_copy.pop('app', None)
        return status_copy

    def _run_bulk_move(self, task_id, movie_ids, radarr_path, series_ids, sonarr_path):
        task = self.tasks[task_id]
        app = task['app']
        move_manager = MoveManager()
        report_lines = []

        with app.app_context():
            try:
                task['status'] = 'running'

                # --- Traitement des films (Radarr) ---
                if movie_ids and radarr_path:
                    for media_id in movie_ids:
                        task['processed_items'] += 1
                        task['progress'] = (task['processed_items'] / task['total_items']) * 100

                        item_name = f"Film ID {media_id}" # Placeholder, on pourrait récupérer le vrai titre
                        try:
                            # Utilise la logique existante du MoveManager
                            move_manager.start_move(media_id, 'radarr', radarr_path)
                            # On attend la fin de cette tâche spécifique
                            while move_manager.get_status()['status'] not in ['completed', 'failed', 'idle']:
                                threading.sleep(2)

                            final_status = move_manager.get_status()
                            if final_status['status'] == 'completed':
                                task['success_count'] += 1
                                report_lines.append(f"SUCCÈS: {item_name} déplacé vers {radarr_path}.")
                            else:
                                task['failure_count'] += 1
                                error_msg = final_status.get('message', 'Erreur inconnue')
                                report_lines.append(f"ÉCHEC: {item_name} - {error_msg}")

                        except Exception as e:
                            task['failure_count'] += 1
                            report_lines.append(f"ÉCHEC: {item_name} - Erreur critique: {e}")

                # --- Traitement des séries (Sonarr) ---
                if series_ids and sonarr_path:
                    for media_id in series_ids:
                        task['processed_items'] += 1
                        task['progress'] = (task['processed_items'] / task['total_items']) * 100

                        item_name = f"Série ID {media_id}"
                        try:
                            move_manager.start_move(media_id, 'sonarr', sonarr_path)
                            while move_manager.get_status()['status'] not in ['completed', 'failed', 'idle']:
                                threading.sleep(2)

                            final_status = move_manager.get_status()
                            if final_status['status'] == 'completed':
                                task['success_count'] += 1
                                report_lines.append(f"SUCCÈS: {item_name} déplacé vers {sonarr_path}.")
                            else:
                                task['failure_count'] += 1
                                error_msg = final_status.get('message', 'Erreur inconnue')
                                report_lines.append(f"ÉCHEC: {item_name} - {error_msg}")

                        except Exception as e:
                             task['failure_count'] += 1
                             report_lines.append(f"ÉCHEC: {item_name} - Erreur critique: {e}")

                task['status'] = 'completed'
                task['progress'] = 100

            except Exception as e:
                task['status'] = 'failed'
                report_lines.append(f"ERREUR FATALE: Le processus a été interrompu. {e}")

            finally:
                summary = f"Opération terminée. Succès: {task['success_count']}, Échecs: {task['failure_count']}."
                report_lines.insert(0, summary)
                task['report'] = "\n".join(report_lines)
