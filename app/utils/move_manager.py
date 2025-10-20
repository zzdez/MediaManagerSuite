# app/utils/move_manager.py

import threading
import uuid
from flask import current_app
from datetime import datetime, timedelta

class MoveManager:
    """
    Manages the state of media file moves, tracking active and recently completed tasks.
    Ensures only one move operation is active at a time.
    This is a simple in-memory manager suitable for a single-worker server setup.
    """
    _instance = None
    _lock = threading.RLock()
    _tasks = {}  # { task_id: { 'media_id': ..., 'status': 'in_progress'/'success'/'failure', ... } }
    COMPLETED_TASK_RETENTION = timedelta(minutes=5)

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(MoveManager, cls).__new__(cls)
        return cls._instance

    def _cleanup_old_tasks(self):
        """Removes completed tasks that are older than the retention time."""
        now = datetime.now()
        tasks_to_delete = [
            task_id for task_id, task in self._tasks.items()
            if task.get('status') in ['success', 'failure'] and (now - task.get('end_time', now) > self.COMPLETED_TASK_RETENTION)
        ]
        for task_id in tasks_to_delete:
            del self._tasks[task_id]
            current_app.logger.info(f"Cleaned up completed move task {task_id}.")

    def start_move(self, media_id, media_type):
        """
        Starts a new move task if no other move is in progress.
        Also cleans up old completed tasks.

        Returns:
            str: The task_id if the move can be started.
            None: If a move is already in progress.
        """
        with self._lock:
            self._cleanup_old_tasks()

            if self.is_move_in_progress():
                current_app.logger.warning(f"Cannot start move for {media_type} ID {media_id}. A move is already in progress.")
                return None

            task_id = str(uuid.uuid4())
            self._tasks[task_id] = {
                'task_id': task_id,
                'media_id': media_id,
                'media_type': media_type,
                'status': 'in_progress',
                'start_time': datetime.now()
            }
            current_app.logger.info(f"Started move task {task_id} for {media_type} ID {media_id}.")
            return task_id

    def update_task_status(self, task_id, success, error_message=None):
        """Updates the status of a task to 'success' or 'failure'."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task['status'] = 'success' if success else 'failure'
                task['end_time'] = datetime.now()
                if error_message:
                    task['error_message'] = error_message
                current_app.logger.info(f"Updated move task {task_id} status to {task['status']}.")
            else:
                current_app.logger.warning(f"Attempted to update a non-existent move task ({task_id}).")

    def get_task_status(self, task_id):
        """Gets the status details of a specific move task."""
        with self._lock:
            return self._tasks.get(task_id)

    def is_move_in_progress(self):
        """Checks if any move task is currently in progress."""
        with self._lock:
            return any(task.get('status') == 'in_progress' for task in self._tasks.values())

    def get_current_move_status(self):
        """
        Gets the details of the currently active move task.
        Maintained for compatibility, but might be deprecated.
        """
        with self._lock:
            for task in self._tasks.values():
                if task.get('status') == 'in_progress':
                    return task.copy()
            return None

# Singleton instance
move_manager = MoveManager()