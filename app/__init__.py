# MediaManagerSuite/app/__init__.py

import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime

from flask import Flask, render_template, session, flash, request, redirect, url_for
from config import Config # Correct car config.py est à la racine du projet

logger = logging.getLogger(__name__)

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
    try:
        from app.plex_editor import plex_editor_bp # Correct car plex_editor est un sous-package de app
        app.register_blueprint(plex_editor_bp, url_prefix='/plex')
        logger.info("Blueprint 'plex_editor' enregistré avec succès.")
    except ImportError as e:
        logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint plex_editor: {e}")

    try:
        from app.seedbox_ui import seedbox_ui_bp # Correct car seedbox_ui est un sous-package de app
        app.register_blueprint(seedbox_ui_bp, url_prefix='/seedbox')
        logger.info("Blueprint 'seedbox_ui' enregistré avec succès.")
    except ImportError as e:
        logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint seedbox_ui: {e}")


    # Route pour la page d'accueil/portail
    @app.route('/')
    def home():
        current_year = datetime.utcnow().year
        return render_template('home_portal.html',
                               title="Portail Media Manager Suite",
                               current_year=current_year)

        # Option B: Rediriger vers un module par défaut
        # return redirect(url_for('seedbox_ui.index'))


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