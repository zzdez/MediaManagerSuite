# run.py
import os
import logging
from dotenv import load_dotenv

# --- ÉTAPE 1: CHARGER L'ENVIRONNEMENT ---
# C'est la PREMIÈRE chose à faire.
load_dotenv()

# --- ÉTAPE 2: IMPORTER L'APPLICATION APRÈS LE CHARGEMENT ---
# L'import de 'app' déclenche la lecture de config.py, donc il doit venir après.
from app import create_app

# --- ÉTAPE 3: CRÉER L'INSTANCE DE L'APPLICATION ---
# Maintenant, create_app() sera appelée dans un environnement où les variables sont déjà chargées.
app = create_app()

# Configuration du logging (le reste du fichier est inchangé)
logging.basicConfig(level=logging.INFO)
logging.getLogger("plexapi").setLevel(logging.DEBUG) # Ou INFO en prod
# ...

if __name__ == '__main__':
    flask_debug_mode = os.environ.get('FLASK_DEBUG', '0').lower() in ('true', '1', 't')
    app.logger.info(f"Démarrage MediaManagerSuite. Debug: {flask_debug_mode}, Reloader: True (pour test)")
    app.run(host='0.0.0.0', 
            port=5001,
            debug=flask_debug_mode, 
            use_reloader=True)