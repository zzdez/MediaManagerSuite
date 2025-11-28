# app/utils/dashboard_scheduler.py

import os
from datetime import datetime, timezone
from flask import current_app

# Import the centralized refresh logic and lock file constant
from app.dashboard.helpers import perform_dashboard_refresh, DASHBOARD_LOCK_FILE

def scheduled_dashboard_refresh():
    """
    This function is designed to be called by the APScheduler.
    It uses a lock to prevent multiple instances from running simultaneously.
    """
    if os.path.exists(DASHBOARD_LOCK_FILE):
        current_app.logger.warning("Scheduler: Refresh job already running. Skipping this run.")
        return

    try:
        # Create lock file
        with open(DASHBOARD_LOCK_FILE, 'w') as f:
            f.write(str(datetime.now(timezone.utc)))

        current_app.logger.info("Scheduler: Starting scheduled dashboard refresh job.")

        # Call the centralized refresh logic
        perform_dashboard_refresh()

        current_app.logger.info("Scheduler: Dashboard refresh job finished successfully.")

    except Exception as e:
        current_app.logger.error(f"Scheduler: Error in scheduled_dashboard_refresh: {e}", exc_info=True)
    finally:
        # Ensure the lock is always removed
        if os.path.exists(DASHBOARD_LOCK_FILE):
            os.remove(DASHBOARD_LOCK_FILE)
            current_app.logger.info("Scheduler: Lock file removed.")
