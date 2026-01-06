import json
import os
from datetime import datetime, timezone, timedelta
from flask import current_app

SEEN_HISTORY_FILE = os.path.join('instance', 'seen_history.json')
DEFAULT_RETENTION_DAYS = 60

def get_seen_history():
    """Loads the seen history from disk. Returns a dict {guid: timestamp}."""
    if not os.path.exists(SEEN_HISTORY_FILE):
        return {}
    try:
        with open(SEEN_HISTORY_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        current_app.logger.error(f"Error loading seen history: {e}")
        return {}

def add_to_seen_history(guids):
    """
    Adds a list of GUIDs to the seen history.
    Also performs a cleanup of entries older than retention period.
    """
    if not guids:
        return

    history = get_seen_history()
    now_iso = datetime.now(timezone.utc).isoformat()

    updated = False
    for guid in guids:
        # Always update the timestamp to extend retention if the user interacts with it
        if guid:
            history[guid] = now_iso
            updated = True

    if updated:
        # Auto-purge old entries only when we write
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=DEFAULT_RETENTION_DAYS)
        keys_to_remove = [k for k, v in history.items() if _is_older_than(v, cutoff_date)]

        for k in keys_to_remove:
            del history[k]

        try:
            os.makedirs(os.path.dirname(SEEN_HISTORY_FILE), exist_ok=True)
            with open(SEEN_HISTORY_FILE, 'w') as f:
                json.dump(history, f, indent=2)
            current_app.logger.info(f"Updated seen history. Added/Updated: {len(guids)}. Removed: {len(keys_to_remove)}. Total: {len(history)}.")
        except IOError as e:
            current_app.logger.error(f"Error saving seen history: {e}")

def is_seen(guid):
    """Checks if a GUID exists in the seen history."""
    if not guid:
        return False
    history = get_seen_history()
    return guid in history

def _is_older_than(timestamp_str, cutoff_dt):
    try:
        # Handle simple ISO format
        ts = datetime.fromisoformat(timestamp_str)
        return ts < cutoff_dt
    except (ValueError, TypeError):
        return True # Treat invalid dates as old
