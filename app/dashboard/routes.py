from flask import render_template, jsonify, current_app, request
from app.dashboard import dashboard_bp
import json
import os
from datetime import datetime, timezone, timedelta
import uuid
import threading

# Import the centralized refresh logic and lock file constant
from .helpers import perform_dashboard_refresh, DASHBOARD_LOCK_FILE

# Import other necessary utilities
from app.utils.release_parser import parse_release_data
from app.utils.tmdb_client import TheMovieDBClient
from app.utils.status_manager import get_media_statuses

# Define paths for our state files
DASHBOARD_TORRENTS_FILE = os.path.join('instance', 'dashboard_torrents.json')
DASHBOARD_IGNORED_FILE = os.path.join('instance', 'dashboard_ignored.json')

# --- In-memory store for background task status ---
tasks = {}
tasks_lock = threading.Lock()

# --- Routes ---

@dashboard_bp.route('/dashboard')
def dashboard():
    """
    Dashboard page - loads torrents from our persistent store.
    """
    torrents = []
    if os.path.exists(DASHBOARD_TORRENTS_FILE):
        try:
            with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
                torrents = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            current_app.logger.error(f"Could not read or parse dashboard_torrents.json: {e}")

    # Ensure all torrents have parsed_data for backward compatibility
    for torrent in torrents:
        if 'parsed_data' not in torrent or not torrent['parsed_data']:
            torrent['parsed_data'] = parse_release_data(torrent['title'])

    return render_template('dashboard/index.html', torrents=torrents)

def run_refresh_in_background(task_id, app_context):
    """
    Wrapper function to run the refresh task in a background thread
    and update the task status. It now handles its own locking.
    """
    with app_context:
        if os.path.exists(DASHBOARD_LOCK_FILE):
            current_app.logger.warning(f"Task {task_id}: Could not acquire lock, another refresh is running.")
            with tasks_lock:
                tasks[task_id] = {'status': 'error', 'message': 'Un rafraîchissement est déjà en cours.'}
            return

        try:
            with open(DASHBOARD_LOCK_FILE, 'w') as f:
                f.write(str(datetime.now(timezone.utc)))

            with tasks_lock:
                tasks[task_id] = {'status': 'running'}

            final_torrents = perform_dashboard_refresh()

            with tasks_lock:
                tasks[task_id] = {'status': 'complete', 'result': final_torrents}

        except Exception as e:
            current_app.logger.error(f"Background refresh task {task_id} failed: {e}", exc_info=True)
            with tasks_lock:
                tasks[task_id] = {'status': 'error', 'message': str(e)}
        finally:
            if os.path.exists(DASHBOARD_LOCK_FILE):
                os.remove(DASHBOARD_LOCK_FILE)

@dashboard_bp.route('/dashboard/api/task_status/<task_id>')
def task_status(task_id):
    """
    API endpoint for the client to poll the status of a background task.
    """
    with tasks_lock:
        task = tasks.get(task_id)
        if task is None:
            return jsonify({'status': 'not_found'}), 404
        return jsonify(task)

@dashboard_bp.route('/dashboard/api/refresh')
def refresh_torrents():
    """
    API endpoint to start a background refresh task.
    Returns a task ID for the client to poll.
    """
    task_id = str(uuid.uuid4())

    # We need to pass the app context to the new thread
    app_context = current_app.app_context()

    thread = threading.Thread(target=run_refresh_in_background, args=(task_id, app_context))
    thread.start()

    return jsonify({"status": "pending", "task_id": task_id})

# --- Other Helper Functions for Routes ---

def get_ignored_hashes():
    """Reads the set of ignored torrent hashes."""
    if not os.path.exists(DASHBOARD_IGNORED_FILE):
        return set()
    try:
        with open(DASHBOARD_IGNORED_FILE, 'r') as f:
            return set(json.load(f))
    except (json.JSONDecodeError, IOError):
        return set()

def add_ignored_hash(torrent_hash):
    """Adds a torrent hash to the ignored file."""
    ignored_hashes = get_ignored_hashes()
    ignored_hashes.add(torrent_hash)
    os.makedirs(os.path.dirname(DASHBOARD_IGNORED_FILE), exist_ok=True)
    with open(DASHBOARD_IGNORED_FILE, 'w') as f:
        json.dump(list(ignored_hashes), f)
    current_app.logger.info(f"Added hash {torrent_hash} to ignored list.")

# --- Other API Routes ---

@dashboard_bp.route('/dashboard/api/ignore', methods=['POST'])
def ignore_torrent():
    data = request.get_json()
    torrent_id = data.get('id')
    if not torrent_id:
        return jsonify({"status": "error", "message": "No identifier provided"}), 400
    add_ignored_hash(torrent_id)
    return jsonify({"status": "success", "message": f"Identifier {torrent_id} ignored."})

@dashboard_bp.route('/dashboard/api/refresh-statuses')
def refresh_statuses():
    try:
        if not os.path.exists(DASHBOARD_TORRENTS_FILE):
            return jsonify({"status": "success", "torrents": []})

        with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
            existing_torrents = json.load(f)

        tmdb_api_key = current_app.config.get('TMDB_API_KEY')
        if not tmdb_api_key:
            current_app.logger.warning("TMDB_API_KEY not set. Skipping status refresh.")
            return jsonify({"status": "success", "torrents": existing_torrents})

        is_new_status_map = {t['hash']: t.get('is_new', False) for t in existing_torrents}

        for torrent in existing_torrents:
            if 'parsed_data' not in torrent or not torrent['parsed_data']:
                torrent['parsed_data'] = parse_release_data(torrent['title'])

            torrent['statuses'] = get_media_statuses(
                title=torrent.get('title'),
                tmdb_id=torrent.get('tmdbId'),
                tvdb_id=torrent.get('tvdbId'),
                media_type=torrent.get('type'),
                parsed_data=torrent['parsed_data']
            )
            torrent['is_new'] = is_new_status_map.get(torrent['hash'], False)

        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(existing_torrents, f, indent=2)

        return jsonify({"status": "success", "torrents": existing_torrents})
    except Exception as e:
        current_app.logger.error(f"Error in refresh_statuses: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An unexpected error occurred."}), 500

@dashboard_bp.route('/dashboard/api/cleanup', methods=['POST'])
def cleanup_torrents():
    data = request.get_json()
    days_to_keep = data.get('days')
    try:
        days_to_keep = int(days_to_keep)
        if not (0 <= days_to_keep <= 30):
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid number of days."}), 400

    if not os.path.exists(DASHBOARD_TORRENTS_FILE):
        return jsonify({"status": "success", "cleaned_count": 0})

    try:
        with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
            all_torrents = json.load(f)

        original_count = len(all_torrents)
        if days_to_keep == 0:
            cleaned_torrents = []
        else:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            cleaned_torrents = [
                t for t in all_torrents
                if datetime.fromisoformat(t['publishDate'].replace('Z', '+00:00')) >= cutoff_date
            ]

        cleaned_count = original_count - len(cleaned_torrents)
        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(cleaned_torrents, f, indent=2)

        return jsonify({"status": "success", "cleaned_count": cleaned_count})
    except Exception as e:
        current_app.logger.error(f"Error during cleanup: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to process torrent file."}), 500

@dashboard_bp.route('/dashboard/api/mark-all-as-seen', methods=['POST'])
def mark_all_as_seen():
    if not os.path.exists(DASHBOARD_TORRENTS_FILE):
        return jsonify({"status": "success", "message": "No torrents to update."})
    try:
        with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
            torrents = json.load(f)
        updated_count = 0
        for torrent in torrents:
            if torrent.get('is_new'):
                torrent['is_new'] = False
                updated_count += 1
        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(torrents, f, indent=2)
        return jsonify({"status": "success", "updated_count": updated_count})
    except Exception as e:
        current_app.logger.error(f"Error marking all as seen: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to process torrent file."}), 500

@dashboard_bp.route('/dashboard/api/mark-as-seen', methods=['POST'])
def mark_as_seen():
    data = request.get_json()
    torrent_hash = data.get('hash')
    if not torrent_hash:
        return jsonify({"status": "error", "message": "No hash provided."}), 400
    if not os.path.exists(DASHBOARD_TORRENTS_FILE):
        return jsonify({"status": "error", "message": "Torrent file not found."}), 404
    try:
        with open(DASHBOARD_TORRENTS_FILE, 'r') as f:
            torrents = json.load(f)

        found = False
        for torrent in torrents:
            if torrent.get('hash') == torrent_hash:
                torrent['is_new'] = False
                found = True
                break

        if not found:
            return jsonify({"status": "error", "message": "Torrent not found."}), 404

        with open(DASHBOARD_TORRENTS_FILE, 'w') as f:
            json.dump(torrents, f, indent=2)
        return jsonify({"status": "success"})
    except Exception as e:
        current_app.logger.error(f"Error in mark_as_seen: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to process torrent file."}), 500
