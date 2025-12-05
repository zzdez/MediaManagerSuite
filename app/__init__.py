# MediaManagerSuite/app/__init__.py

import logging
from logging.handlers import RotatingFileHandler
import os
import datetime
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
from app.utils.seedbox_cleaner import run_seedbox_cleaner_task
from app.utils.dashboard_scheduler import scheduled_dashboard_refresh
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

    # --- Run startup tasks within app context ---
    with app.app_context():
        from app.utils.archive_manager import migrate_database_keys
        migrate_database_keys()

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

    # --- Filtres Jinja2 personnalisés ---
    def format_iso_datetime(iso_string):
        """Filtre Jinja pour formater une date/heure ISO en format lisible (Europe/Paris)."""
        if not iso_string:
            return 'Date inconnue'
        try:
            import pytz
            # Parse ISO string
            # Handle possible 'Z' (UTC) or other formats
            core_string = iso_string
            if '.' in iso_string:
                core_string = iso_string.split('.')[0] # Remove microseconds

            if iso_string.endswith('Z'):
                core_string = core_string.rstrip('Z')
                dt = datetime.datetime.strptime(core_string, '%Y-%m-%dT%H:%M:%S')
                # Assume Z means UTC
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            else:
                # If no Z, try parsing. If naive, assume UTC or Server Time?
                # Prowlarr usually returns UTC.
                dt = datetime.datetime.strptime(core_string, '%Y-%m-%dT%H:%M:%S')
                # If naive, make it UTC aware
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)

            # Convert to Paris
            paris_tz = pytz.timezone('Europe/Paris')
            dt_paris = dt.astimezone(paris_tz)

            return dt_paris.strftime('%d/%m/%Y à %H:%M')
        except (ValueError, TypeError, ImportError) as e:
            # Fallback
            try:
                # Simple split date
                return iso_string.split('T')[0]
            except:
                return 'Date invalide'

    app.jinja_env.filters['date_format'] = format_iso_datetime
    # Ajout du filtre to_datetime manquant si la version de Jinja est ancienne
    if 'to_datetime' not in app.jinja_env.filters:
        from jinja2.filters import pass_environment
        @pass_environment
        def to_datetime_filter(environment, value):
            if value is None:
                return None
            try:
                # Remplacé par strptime pour la compatibilité
                return datetime.datetime.strptime(value.split('.')[0], '%Y-%m-%dT%H:%M:%S')
            except:
                return None
        app.jinja_env.filters['to_datetime'] = to_datetime_filter


    # Enregistrement des Blueprints
    from app.plex_editor import plex_editor_bp
    app.register_blueprint(plex_editor_bp)
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

    from app.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)
    logger.info("Blueprint 'dashboard' enregistré avec succès.")

    # Route pour la page d'accueil/portail
    @app.route('/')
    @login_required
    def home():
        # Redirige l'utilisateur vers le nouveau tableau de bord
        return redirect(url_for('dashboard_bp.dashboard'))

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

    # --- Context Processor for Disk Usage ---
    @app.context_processor
    def inject_disk_usage():
        try:
            from app.utils.disk_manager import DiskManager
            stats = DiskManager.get_disk_usage()
            return dict(disk_usage_stats=stats)
        except Exception as e:
            logger.error(f"Context Processor Error (DiskManager): {e}")
            return dict(disk_usage_stats=[])

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
            start_date=datetime.datetime.now() + datetime.timedelta(seconds=20),
            replace_existing=True
        )

        # Add the staging processor job
        scheduler.add_job(
            func=scheduled_staging_processor_job,
            trigger='interval',
            minutes=1,
            id='staging_processor_job',
            start_date=datetime.datetime.now() + datetime.timedelta(seconds=10),
            replace_existing=True
        )

        # Add the trailer cleanup job
        scheduler.add_job(
            func=scheduled_trailer_cleanup_job,
            trigger='interval',
            hours=24,
            id='trailer_cleanup_job',
            start_date=datetime.datetime.now() + datetime.timedelta(minutes=5), # Run 5 mins after startup
            replace_existing=True
        )

        scheduler.start()
        app.logger.info(f"APScheduler started. rTorrent scan job scheduled every {rtorrent_scan_interval} minutes. Staging processor job scheduled every 1 minute. Trailer cleanup job scheduled every 24 hours.")

        # Ensure scheduler shuts down cleanly when the app exits
        atexit.register(lambda: scheduler.shutdown() if scheduler and scheduler.running else None)

        # --- Seedbox Cleaner Job ---
        if app.config.get('SEEDBOX_CLEANER_ENABLED'):
            cleaner_interval_hours = app.config.get('SEEDBOX_CLEANER_SCHEDULE_HOURS', 24)
            def scheduled_seedbox_cleaner_job():
                with app.app_context():
                    current_app.logger.info(f"Scheduler: Triggering Seedbox Cleaner job. Interval: {cleaner_interval_hours} hours.")
                    run_seedbox_cleaner_task()

            scheduler.add_job(
                func=scheduled_seedbox_cleaner_job,
                trigger='interval',
                hours=cleaner_interval_hours,
                id='seedbox_cleaner_job',
                start_date=datetime.datetime.now() + datetime.timedelta(minutes=1), # Run 1 min after startup
                replace_existing=True
            )
            app.logger.info(f"Seedbox Cleaner job scheduled every {cleaner_interval_hours} hours.")
        else:
            app.logger.info("Seedbox Cleaner is disabled. Job not scheduled.")

        # --- Dashboard Refresh Job ---
        dashboard_refresh_interval_hours = app.config.get('DASHBOARD_REFRESH_INTERVAL_HOURS')
        if dashboard_refresh_interval_hours and dashboard_refresh_interval_hours > 0:
            def scheduled_dashboard_job():
                with app.app_context():
                    current_app.logger.info(f"Scheduler: Triggering Dashboard Refresh job. Interval: {dashboard_refresh_interval_hours} hours.")
                    scheduled_dashboard_refresh()

            scheduler.add_job(
                func=scheduled_dashboard_job,
                trigger='interval',
                hours=dashboard_refresh_interval_hours,
                id='dashboard_refresh_job',
                start_date=datetime.datetime.now() + datetime.timedelta(minutes=2), # Run 2 mins after startup
                replace_existing=True
            )
            app.logger.info(f"Dashboard Refresh job scheduled every {dashboard_refresh_interval_hours} hours.")
        else:
            app.logger.info("Dashboard Refresh scheduler is disabled (DASHBOARD_REFRESH_INTERVAL_HOURS not set or is 0). Job not scheduled.")

        # --- Backup Job ---
        try:
            from app.utils.backup_manager import create_backup

            schedule = os.getenv('BACKUP_SCHEDULE', 'disabled').lower()
            trigger_args = None
            if schedule == 'hourly':
                trigger, trigger_args = 'interval', {'hours': 1}
            elif schedule == 'daily':
                trigger, trigger_args = 'interval', {'days': 1}
            elif schedule == 'weekly':
                trigger, trigger_args = 'interval', {'weeks': 1}
            else:
                trigger = None

            if trigger:
                def backup_job_func():
                    with app.app_context():
                        create_backup()

                scheduler.add_job(
                    func=backup_job_func, trigger=trigger, id='backup_job',
                    replace_existing=True, **trigger_args
                )
                app.logger.info(f"Tâche de sauvegarde planifiée au démarrage : {schedule}")

        except ImportError:
            app.logger.warning("Module de sauvegarde non trouvé, la tâche de sauvegarde n'a pas été planifiée.")

    # Attach the scheduler to the app so it can be accessed in blueprints
    app.scheduler = scheduler

    return app
