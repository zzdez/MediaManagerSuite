# app/utils/bulk_move_manager.py

import threading
import uuid
from flask import current_app
from .move_manager import MoveManager
from .arr_client import get_sonarr_root_folders, get_radarr_root_folders

class BulkMoveManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(BulkMoveManager, cls).__new__(cls)
                cls._instance.tasks = {}
        return cls._instance

    def start_bulk_move(self, move_groups, app):
        task_id = str(uuid.uuid4())
        total_items = sum(len(group.get('item_ids', [])) for group in move_groups)

        task_info = {
            'status': 'starting',
            'progress': 0,
            'report': 'Initialisation...',
            'total_items': total_items,
            'processed_items': 0,
            'success_count': 0,
            'failure_count': 0,
            'app': app # Store app context for the thread
        }
        self.tasks[task_id] = task_info

        thread = threading.Thread(target=self._run_bulk_move, args=(task_id, move_groups))
        thread.daemon = True
        thread.start()
        return task_id

    def get_task_status(self, task_id):
        task = self.tasks.get(task_id)
        if not task:
            return {'status': 'not_found', 'message': 'Tâche non trouvée.'}

        status_copy = task.copy()
        status_copy.pop('app', None)
        return status_copy

    def _run_bulk_move(self, task_id, move_groups):
        task = self.tasks[task_id]
        app = task['app']
        move_manager = MoveManager()
        report_lines = []

        with app.app_context():
            try:
                task['status'] = 'running'

                # Déterminer à quel *Arr appartient chaque dossier de destination
                sonarr_paths = {f['path'] for f in get_sonarr_root_folders() or []}
                radarr_paths = {f['path'] for f in get_radarr_root_folders() or []}

                for group in move_groups:
                    destination_path = group['destination_path']
                    item_ids = group['item_ids']
                    media_type_str = group['media_type']

                    arr_type = None
                    if destination_path in sonarr_paths:
                        arr_type = 'sonarr'
                    elif destination_path in radarr_paths:
                        arr_type = 'radarr'

                    if not arr_type:
                        task['failure_count'] += len(item_ids)
                        task['processed_items'] += len(item_ids)
                        report_lines.append(f"ÉCHEC CRITIQUE: Le dossier de destination '{destination_path}' pour le groupe '{media_type_str}' n'a été trouvé ni dans Sonarr ni dans Radarr. {len(item_ids)} média(s) ignoré(s).")
                        continue

                    for media_id in item_ids:
                        task['processed_items'] += 1
                        task['progress'] = (task['processed_items'] / task['total_items']) * 100
                        item_name = f"Média ID {media_id}" # Placeholder

                        try:
                            # Utilise la logique existante du MoveManager pour un seul item
                            move_manager.start_move(media_id, arr_type, destination_path)

                            # Boucle de polling pour ce déplacement spécifique
                            while move_manager.get_status()['status'] not in ['completed', 'failed', 'idle']:
                                threading.sleep(2) # Attente courte entre les vérifications

                            final_status = move_manager.get_status()
                            if final_status['status'] == 'completed':
                                task['success_count'] += 1
                                report_lines.append(f"SUCCÈS: {item_name} (Type: {media_type_str}) déplacé vers {destination_path}.")
                            else:
                                task['failure_count'] += 1
                                error_msg = final_status.get('message', 'Erreur inconnue lors du déplacement.')
                                report_lines.append(f"ÉCHEC: {item_name} (Type: {media_type_str}) - {error_msg}")

                        except Exception as e:
                            task['failure_count'] += 1
                            report_lines.append(f"ÉCHEC: {item_name} (Type: {media_type_str}) - Erreur critique: {e}")

                task['status'] = 'completed'
                task['progress'] = 100

            except Exception as e:
                task['status'] = 'failed'
                report_lines.append(f"ERREUR FATALE: Le processus a été interrompu. {e}")

            finally:
                summary = f"Opération terminée. Succès: {task['success_count']}, Échecs: {task['failure_count']}."
                report_lines.insert(0, summary)
                task['report'] = "\n".join(report_lines)
