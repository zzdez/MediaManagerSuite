# MediaManagerSuite/app/__init__.py

import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
import secrets # Added import
from app.auth import login_required

from flask import Flask, render_template, session, flash, request, redirect, url_for, current_app # Added current_app
from config import Config # Correct car config.py est à la racine du projet

# APScheduler imports
from apscheduler.schedulers.background import BackgroundScheduler
from app.utils.sftp_scanner import scan_and_map_torrents
from app.utils.staging_processor import process_pending_staging_items
import datetime
import atexit
import threading

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None
# Global lock for SFTP scan
sftp_scan_lock = threading.Lock()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.sftp_scan_lock = sftp_scan_lock # Attach the global lock to the app instance
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
                                               encoding='utf-8') # <--- AJOUTER encoding='utf-8'
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


    # Enregistrement des Blueprints
    # try/except a été temporairement retiré pour voir l'erreur d'importation réelle
    from app.plex_editor import plex_editor_bp
    app.register_blueprint(plex_editor_bp, url_prefix='/plex')
    logger.info("Blueprint 'plex_editor' enregistré avec succès.")

    try:
        from app.seedbox_ui import seedbox_ui_bp # Correct car seedbox_ui est un sous-package de app
        app.register_blueprint(seedbox_ui_bp, url_prefix='/seedbox')
        logger.info("Blueprint 'seedbox_ui' enregistré avec succès.")
    except ImportError as e:
        logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint seedbox_ui: {e}")

    # AJOUT POUR LE NOUVEAU BLUEPRINT
    try:
        from app.config_ui import config_ui_bp
        app.register_blueprint(config_ui_bp, url_prefix='/configuration')
        logger.info("Blueprint 'config_ui' enregistré avec succès.")
    except ImportError as e:
        logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint config_ui: {e}")
    # FIN DE L'AJOUT

    # Register YGG Cookie UI blueprint
    try:
        from app.ygg_cookie_ui import ygg_cookie_ui_bp
        app.register_blueprint(ygg_cookie_ui_bp, url_prefix='/ygg-cookie')
        logger.info("Blueprint 'ygg_cookie_ui' enregistré avec succès.")
    except ImportError as e:
        logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint ygg_cookie_ui: {e}")

    try:
        from app.search_ui import search_ui_bp
        app.register_blueprint(search_ui_bp, url_prefix='/search')
        logger.info("Blueprint 'search_ui' enregistré avec succès.")
    except ImportError as e:
        logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint search_ui: {e}")

    try:
        from app.trailer_routes import trailer_bp
        app.register_blueprint(trailer_bp)
        logger.info("Blueprint 'trailer' enregistré avec succès.")
    except ImportError as e:
        logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint trailer: {e}")

    # Route pour la page d'accueil/portail
    @app.route('/')
    @login_required
    def home():
        current_year = datetime.datetime.now(datetime.timezone.utc).year
        return render_template('home_portal.html',
                               title="Portail Media Manager Suite",
                               current_year=current_year)

        # Option B: Rediriger vers un module par défaut
        # return redirect(url_for('seedbox_ui.index'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            password = request.form.get('password')
            app_password = current_app.config.get('APP_PASSWORD')
            if app_password and password and secrets.compare_digest(password, app_password):
                session['logged_in'] = True
                session.permanent = True  # Make session permanent
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

    # Gestionnaires d'erreurs HTTP globaux
    @app.errorhandler(404)
    def not_found_error(error):
        logger.warning(f"Erreur 404 - Page non trouvée: {request.url} (Référent: {request.referrer})")
        return render_template('404.html', title="Page non trouvée"), 404 # CHEMIN CORRIGÉ

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Erreur interne du serveur (500): {error}", exc_info=True)
        # db.session.rollback() # Si tu utilises une base de données
        return render_template('500.html', title="Erreur Interne du Serveur"), 500 # CHEMIN CORRIGÉ  
    logger.info("Application MediaManagerSuite créée et configurée.")

    # Initialize and start the scheduler only if it's not already running
    # This is particularly important with Flask's reloader
    global scheduler
    if scheduler is None or not scheduler.running:
        scheduler = BackgroundScheduler(daemon=True)

        # Get interval from config
        sftp_scan_interval = app.config.get('SCHEDULER_SFTP_SCAN_INTERVAL_MINUTES', 30)

        # Define the function for the rTorrent scanner job
        def scheduled_rtorrent_scan_job():
            with app.app_context():
                current_app.logger.info(f"Scheduler: Triggering rTorrent scan job. Interval: {app.config.get('SCHEDULER_SFTP_SCAN_INTERVAL_MINUTES', 15)} mins.")
                scan_and_map_torrents()

        # Define the function for the staging processor job
        def scheduled_staging_processor_job():
            with app.app_context():
                current_app.logger.info("Scheduler: Triggering staging processor job. Interval: 1 min.")
                process_pending_staging_items()

        # Add the rTorrent scanner job
        scheduler.add_job(
            func=scheduled_rtorrent_scan_job,
            trigger='interval',
            minutes=sftp_scan_interval,
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

        scheduler.start()
        app.logger.info(f"APScheduler started. rTorrent scan job scheduled every {sftp_scan_interval} minutes. Staging processor job scheduled every 1 minute.")

        # Ensure scheduler shuts down cleanly when the app exits
        atexit.register(lambda: scheduler.shutdown() if scheduler and scheduler.running else None)

    return app