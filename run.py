# run.py
from app import create_app # Importer la factory
import logging
import os

app = create_app() # Créer l'instance de l'application

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("plexapi").setLevel(logging.DEBUG) # Ou INFO en prod
# ...

if __name__ == '__main__':
    flask_debug_mode = os.environ.get('FLASK_DEBUG', '0').lower() in ('true', '1', 't')
    # Ou lisez app.config['DEBUG'] si vous préférez, après que create_app() a été appelé.
    # flask_debug_mode = app.config.get("DEBUG", False)

    app.logger.info(f"Démarrage MediaManagerSuite. Debug: {flask_debug_mode}, Reloader: False (pour test)")
    app.run(host='0.0.0.0', 
            port=5001, # Ou un autre port si Seedbox UI doit tourner sur un port différent de Plex Editor
            debug=flask_debug_mode, 
            use_reloader=False) # Garder False pour le débogage initial