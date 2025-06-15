# MediaManagerSuite/app/__init__.py

import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
import secrets # Added import
from functools import wraps # Added for login_required decorator

from flask import Flask, render_template, session, flash, request, redirect, url_for, current_app # Added current_app
from config import Config # Correct car config.py est à la racine du projet

logger = logging.getLogger(__name__)

# Décorateur login_required
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            session['next_url'] = request.url
            flash("Veuillez vous connecter pour accéder à cette page.", 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Configuration du logging de l'application
    if not app.debug and not app.testing:
        if app.config.get('LOG_TO_STDOUT'):
            stream_handler = logging.StreamHandler()
            stream_handler.setLevel(logging.INFO)
            app.logger.addHandler(stream_handler)
        else:
            if not os.path.exists('logs'): # Crée un dossier logs à la racine du projet
                os.mkdir('logs')
            file_handler = RotatingFileHandler('logs/mediamanager.log',
                                               maxBytes=10240, backupCount=10)
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

    # Route pour la page d'accueil/portail
    @app.route('/')
    @login_required
    def home():
        current_year = datetime.utcnow().year
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
    return app