import os
import re
from flask import current_app, flash, redirect, url_for
from dotenv import set_key

from . import ygg_cookie_ui_bp
from app.auth import login_required

def process_and_update_mms():
    """
    This function processes the cookie file and updates the .env file.
    It's a direct adaptation of the script you provided.
    """
    try:
        # Get config from the Flask app
        mms_env_file_path = current_app.config.get("MMS_ENV_FILE_PATH")
        ygg_domain = current_app.config.get("YGG_DOMAIN")
        cookie_download_path = current_app.config.get("COOKIE_DOWNLOAD_PATH")
        mms_restart_command = current_app.config.get("MMS_RESTART_COMMAND")

        # --- Verifications ---
        # If the path from .env is empty, construct the default path
        if not mms_env_file_path:
            basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            mms_env_file_path = os.path.join(basedir, '.env')

        if not os.path.exists(mms_env_file_path):
            raise FileNotFoundError(f"Chemin invalide pour le .env de MMS : '{mms_env_file_path}'")
        if not ygg_domain:
            raise ValueError("Le domaine YGG_DOMAIN est manquant dans votre fichier .env")

        # --- Find cookie file ---
        cookie_filename = f"{ygg_domain}_cookies.txt"
        downloads_path = cookie_download_path or os.path.join(os.path.expanduser('~'), 'Downloads')
        cookie_file_path = os.path.join(downloads_path, cookie_filename)

        if not os.path.exists(cookie_file_path):
            raise FileNotFoundError(f"Fichier '{cookie_filename}' non trouvé dans '{downloads_path}'.")

        # --- Read and parse the file ---
        current_app.logger.info(f"1. Lecture du fichier '{cookie_file_path}'...")
        with open(cookie_file_path, 'r') as f:
            lines = f.readlines()

        cookies_dict = {parts[5]: parts[6] for line in lines if not line.startswith('#') and line.strip() and len(parts := line.strip().split('\t')) == 7}

        if 'ygg_' not in cookies_dict or 'cf_clearance' not in cookies_dict:
            raise ValueError("Le cookie 'ygg_' ou 'cf_clearance' est manquant.")

        # --- Build cookie string ---
        cookie_order = ['cf_clearance', 'ygg_'] + [k for k in cookies_dict if k not in ['cf_clearance', 'ygg_']]
        full_cookie_string = "; ".join([f"{name}={cookies_dict[name]}" for name in cookie_order if name in cookies_dict])

        # --- Update .env file ---
        current_app.logger.info(f"2. Mise à jour du fichier : {mms_env_file_path}")
        set_key(mms_env_file_path, "YGG_COOKIE", full_cookie_string) # Using YGG_COOKIE as per config.py

        # --- Restart MMS ---
        if mms_restart_command:
            current_app.logger.info(f"3. Lancement de la commande de redémarrage...")
            os.system(mms_restart_command)

        # --- Cleanup ---
        os.remove(cookie_file_path)
        current_app.logger.info("   - Fichier d'export temporaire supprimé.")
        return True, "Cookie YGGTorrent mis à jour avec succès !"
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la mise à jour du cookie YGG: {e}", exc_info=True)
        return False, f"UNE ERREUR EST SURVENUE : {e}"

@ygg_cookie_ui_bp.route('/refresh-ygg-cookie')
@login_required
def refresh_ygg_cookie():
    """
    The route that triggers the cookie refresh process.
    """
    success, message = process_and_update_mms()
    if success:
        flash(message, 'success')
        if current_app.config.get("MMS_RESTART_COMMAND"):
             flash("L'application va maintenant redémarrer.", 'info')
    else:
        flash(message, 'danger')

    # Redirect to the home page after the operation
    return redirect(url_for('home'))
