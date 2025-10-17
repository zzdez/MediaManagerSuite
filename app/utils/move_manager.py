# app/utils/move_manager.py

import threading
import uuid
from flask import current_app

class MoveManager:
    """
    Manages the state of media file moves to ensure only one move operation
    is active at a time across the application. This is a simple in-memory
    manager suitable for a single-worker server setup.
    """
    _instance = None
    _lock = threading.Lock()
    _current_move = {}  # { 'task_id': str, 'media_id': int, 'media_type': str, 'status': str }

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(MoveManager, cls).__new__(cls)
        return cls._instance

    def start_move(self, media_id, media_type):
        """
        Starts a new move task if no other move is in progress.

        Returns:
            str: The task_id if the move can be started.
            None: If a move is already in progress.
        """
        with self._lock:
            if self.is_move_in_progress():
                current_app.logger.warning(f"Cannot start move for {media_type} ID {media_id}. "
                                           f"A move is already in progress: {self._current_move}")
                return None

            task_id = str(uuid.uuid4())
            self._current_move = {
                'task_id': task_id,
                'media_id': media_id,
                'media_type': media_type,
                'status': 'starting'
            }
            current_app.logger.info(f"Started move task {task_id} for {media_type} ID {media_id}.")
            return task_id

    def end_move(self, task_id):
        """Ends a move task, allowing a new one to start."""
        with self._lock:
            if self._current_move.get('task_id') == task_id:
                current_app.logger.info(f"Ending move task {task_id}.")
                self._current_move = {}
            else:
                current_app.logger.warning(f"Attempted to end a move task ({task_id}) that is not the current one "
                                           f"({self._current_move.get('task_id')}). Ignoring.")

    def is_move_in_progress(self):
        """Checks if a move task is currently active."""
        with self._lock:
            return bool(self._current_move)

    def get_current_move_status(self):
        """Gets the details of the currently active move task."""
        with self._lock:
            return self._current_move.copy() if self._current_move else None

# Singleton instance
move_manager = MoveManager()