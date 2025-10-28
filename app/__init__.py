# MediaManagerSuite/app/__init__.py

import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
import secrets
from app.auth import login_required

from flask import Flask, render_template, session, flash, request, redirect, url_for, current_app
from config import Config
import google.generativeai as genai

# APScheduler imports
from apscheduler.schedulers.background import BackgroundScheduler
from app.utils.sftp_scanner import scan_and_map_torrents
from app.utils.staging_processor import process_pending_staging_items
from app.utils.trailer_manager import clean_stale_entries
import datetime
import atexit
import threading

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None
# Global lock for SFTP scan is now obsolete as the new scanner is simpler
# sftp_scan_lock = threading.Lock()

def create_app(config_class=Config):
    app = Flask(__name__)
    # app.sftp_scan_lock = sftp_scan_lock # Obsolete
    app.config.from_object(config_class)

    # Configuration du logging de l'application
    if not app.debug and not app.testing:
        if app.config.get('LOG_TO_STDOUT'):
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.INFO)
            app.logger.addHandler(stream_handler)
        else:
            if not os.path.exists('logs'):
                os.mkdir('logs')
            file_handler = RotatingFileHandler('logs/mediamanager.log',
                                               maxBytes=10240, backupCount=10,
                                               encoding='utf-8')
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s: %(message)s '
                '[in %(pathname)s:%(lineno)d]'))
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.info('MediaManagerSuite startup in production mode')
    else:
        logging.basicConfig(level=logging.INFO,
                            format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
        logger.info('MediaManagerSuite startup in debug/development mode')

    # Initialisation de Google Gemini (une seule fois au démarrage)
    gemini_api_key = app.config.get('GEMINI_API_KEY')
    if gemini_api_key:
        try:
            genai.configure(api_key=gemini_api_key)
            app.logger.info("Google Gemini a été configuré avec succès.")
        except Exception as e:
            app.logger.error(f"Erreur lors de la configuration de Google Gemini: {e}")
    else:
        app.logger.warning("Clé API Gemini non trouvée. Le service de suggestion de requêtes sera limité aux requêtes de secours.")


    # Enregistrement des Blueprints
    from app.plex_editor import plex_editor_bp
    app.register_blueprint(plex_editor_bp, url_prefix='/plex')
    logger.info("Blueprint 'plex_editor' enregistré avec succès.")

    from app.seedbox_ui import seedbox_ui_bp
    app.register_blueprint(seedbox_ui_bp, url_prefix='/seedbox')
    logger.info("Blueprint 'seedbox_ui' enregistré avec succès.")

    from app.config_ui import config_ui_bp
    app.register_blueprint(config_ui_bp, url_prefix='/configuration')
    logger.info("Blueprint 'config_ui' enregistré avec succès.")

    from app.ygg_cookie_ui import ygg_cookie_ui_bp
    app.register_blueprint(ygg_cookie_ui_bp, url_prefix='/ygg-cookie')
    logger.info("Blueprint 'ygg_cookie_ui' enregistré avec succès.")

    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    logger.info("Blueprint 'api' enregistré avec succès.")

    from app.search_ui import search_ui_bp
    app.register_blueprint(search_ui_bp, url_prefix='/search')
    logger.info("Blueprint 'search_ui' enregistré avec succès.")

    from app.agent import agent_bp
    app.register_blueprint(agent_bp)
    logger.info("Blueprint 'agent' enregistré avec succès.")

    # Dans app/__init__.py
    from app.debug_tools.routes import debug_tools_bp
    app.register_blueprint(debug_tools_bp, url_prefix='/debug')
    logger.info("Blueprint 'debug_tools' enregistré avec succès.")

    # Route pour la page d'accueil/portail
    @app.route('/')
    @login_required
    def home():
        current_year = datetime.datetime.now(datetime.timezone.utc).year
        return render_template('home_portal.html',
                               title="Portail Media Manager Suite",
                               current_year=current_year)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            password = request.form.get('password')
            app_password = current_app.config.get('APP_PASSWORD')
            if app_password and password and secrets.compare_digest(password, app_password):
                session['logged_in'] = True
                session.permanent = True
                flash('Connexion réussie !', 'success')
                next_url = session.pop('next_url', None)
                return redirect(next_url or url_for('home'))
            else:
                flash('Mot de passe incorrect.', 'danger')
        return render_template('login.html', title="Connexion")

    @app.route('/logout')
    def logout():
        session.pop('logged_in', None)
        flash('Vous avez été déconnecté.', 'info')
        return redirect(url_for('login'))

    # Obsolete manual scan trigger route has been removed.

    # Gestionnaires d'erreurs HTTP globaux
    @app.errorhandler(404)
    def not_found_error(error):
        logger.warning(f"Erreur 404 - Page non trouvée: {request.url} (Référent: {request.referrer})")
        return render_template('404.html', title="Page non trouvée"), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Erreur interne du serveur (500): {error}", exc_info=True)
        return render_template('500.html', title="Erreur Interne du Serveur"), 500

    logger.info("Application MediaManagerSuite créée et configurée.")

    # Initialize and start the scheduler
    global scheduler
    if scheduler is None or not scheduler.running:
        scheduler = BackgroundScheduler(daemon=True)

        # Get interval from config for the rTorrent scanner
        rtorrent_scan_interval = app.config.get('SCHEDULER_SFTP_SCAN_INTERVAL_MINUTES', 15)

        # Define the function for the rTorrent scanner job
        def scheduled_rtorrent_scan_job():
            with app.app_context():
                current_app.logger.info(f"Scheduler: Triggering rTorrent scan job. Interval: {rtorrent_scan_interval} mins.")
                scan_and_map_torrents()

        # Define the function for the staging processor job
        def scheduled_staging_processor_job():
            with app.app_context():
                current_app.logger.info("Scheduler: Triggering staging processor job. Interval: 1 min.")
                process_pending_staging_items()

        # Define the function for the trailer database cleanup job
        def scheduled_trailer_cleanup_job():
            with app.app_context():
                current_app.logger.info("Scheduler: Triggering trailer database cleanup job. Interval: 24 hours.")
                cleaned_count = clean_stale_entries()
                current_app.logger.info(f"Scheduler: Trailer cleanup job finished. Cleaned {cleaned_count} entries.")

        # Add the rTorrent scanner job
        scheduler.add_job(
            func=scheduled_rtorrent_scan_job,
            trigger='interval',
            minutes=rtorrent_scan_interval,
            id='rtorrent_scan_job',
            next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=20),
            replace_existing=True
        )

        # Add the staging processor job
        scheduler.add_job(
            func=scheduled_staging_processor_job,
            trigger='interval',
            minutes=1,
            id='staging_processor_job',
            next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=10),
            replace_existing=True
        )

        # Add the trailer cleanup job
        scheduler.add_job(
            func=scheduled_trailer_cleanup_job,
            trigger='interval',
            hours=24,
            id='trailer_cleanup_job',
            next_run_time=datetime.datetime.now() + datetime.timedelta(minutes=5), # Run 5 mins after startup
            replace_existing=True
        )

        scheduler.start()
        app.logger.info(f"APScheduler started. rTorrent scan job scheduled every {rtorrent_scan_interval} minutes. Staging processor job scheduled every 1 minute. Trailer cleanup job scheduled every 24 hours.")

        # Ensure scheduler shuts down cleanly when the app exits
        atexit.register(lambda: scheduler.shutdown() if scheduler and scheduler.running else None)

    return app