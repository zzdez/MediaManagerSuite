# MediaManagerSuite/app/__init__.py

from flask import Flask, render_template, session, flash, request  # Importer les modules Flask nécessaires ici
from config import Config # Si config.py est à la racine du projet MediaManagerSuite/
                          # OU from .config import Config si config.py est dans MediaManagerSuite/app/

def create_app(config_class=Config):
    """
    Factory function pour créer et configurer l'application Flask.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialiser les extensions Flask ici si vous en avez (ex: SQLAlchemy, LoginManager)#
    # db.init_app(app)
    # login_manager.init_app(app)

    # Importer et enregistrer les Blueprints
    # Utiliser des imports relatifs car plex_editor et seedbox_ui sont des sous-modules de 'app'
    try:
        from .plex_editor import plex_editor_bp
        app.register_blueprint(plex_editor_bp)
        app.logger.info("Blueprint 'plex_editor' enregistré avec succès.") # <<< CORRIGÉ
    except ImportError as e_plex:
        app.logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint plex_editor: {e_plex}")
        # Vous pourriez vouloir lever l'erreur ici ou gérer différemment
        # raise e_plex

    try:
        from .seedbox_ui import seedbox_ui_bp
        app.register_blueprint(seedbox_ui_bp)
        app.logger.info("Blueprint 'seedbox_ui' enregistré avec succès.") # <<< CORRIGÉ
    except ImportError as e_seedbox:
        app.logger.error(f"Erreur lors de l'import ou de l'enregistrement du blueprint seedbox_ui: {e_seedbox}")
        # raise e_seedbox

    # Optionnel : Route d'accueil globale pour le portail
    # Cette route sera accessible à la racine de votre application (ex: http://localhost:5001/)
    @app.route('/')
    def home():
        # Ce template doit être dans MediaManagerSuite/app/templates/home_portal.html
        # ou MediaManagerSuite/app/plex_editor/templates/home_portal.html ou MediaManagerSuite/app/seedbox_ui/templates/home_portal.html
        # selon la configuration des template_folder des blueprints et de l'app.
        # Pour un template global, il est mieux de le mettre dans app/templates/
        return render_template('home_portal.html', title="Portail Media Manager Suite")

    # Gestionnaires d'erreur globaux pour l'application (facultatif si géré par les blueprints)
    # Si vous les définissez ici, ils s'appliqueront à toute l'application, y compris
    # les erreurs qui ne sont pas spécifiquement gérées par un blueprint.

    # @app.errorhandler(404)
    # def page_not_found_global(e):
    #     # Note: session, current_app, flash sont déjà importés en haut du fichier
    #     user_title = session.get('plex_user_title', 'Visiteur')
    #     # current_app.logger.warning(f"GLOBAL 404: {request.url}, User: {user_title}, Error: {e.description}") # request doit aussi être importé
    #     # Pour l'instant, utilisons un log simple. Importer 'request' si vous voulez l'URL.
    #     app.logger.warning(f"GLOBAL 404 non gérée par un blueprint: {e.description}")
    #     # Ce template doit être dans MediaManagerSuite/app/templates/404.html
    #     return render_template('404.html', error=e, user_title=user_title), 404

    # @app.errorhandler(500)
    # def internal_server_error_global(e):
    #     user_title = session.get('plex_user_title', 'Visiteur')
    #     app.logger.error(f"GLOBAL 500 non gérée par un blueprint: {e}", exc_info=True)
    #     flash("Une erreur interne globale est survenue sur le serveur.", "danger")
    #     # Ce template doit être dans MediaManagerSuite/app/templates/500.html
    #     return render_template('500.html', error=e, user_title=user_title), 500

    return app