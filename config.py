# config.py (pour le projet fusionné MediaManagerSuite)
# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv
# S'assurer que basedir pointe vers la racine du projet MediaManagerSuite
# Si config.py est dans MediaManagerSuite/config.py (et non MediaManagerSuite/app/config.py)
# alors c'est correct.
# Si config.py est dans MediaManagerSuite/app/config.py, alors basedir devrait être os.path.dirname(os.path.dirname(__file__))
# Assumons que config.py est à la racine du projet MediaManagerSuite pour cet exemple.
basedir = os.path.abspath(os.path.dirname(__file__))
dotenv_path = os.path.join(basedir, '.env') # .env doit être à la racine du projet MediaManagerSuite

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, verbose=True)
else:
    print(f"ATTENTION: Le fichier .env n'a pas été trouvé à l'emplacement attendu: {dotenv_path}")
    print("           Les variables d'environnement pourraient ne pas être chargées.")

class Config:
    # --- Clé Secrète Globale (utilisée par les deux modules/blueprints) ---
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'une-cle-secrete-tres-forte-et-aleatoire-a-definir-absolument'

    # --- Configurations pour Plex Web Editor ---
    PLEX_URL = os.environ.get('PLEX_URL')
    PLEX_TOKEN = os.environ.get('PLEX_TOKEN')

    # Configurations pour le nettoyage des dossiers (utilisé par Plex Web Editor, potentiellement par SeedboxWebUI)
    PERFORM_ACTUAL_DELETION = os.environ.get('PERFORM_ACTUAL_DELETION', 'False').lower() in ('true', '1', 't')

    default_orphan_extensions_str = ".nfo,.jpg,.jpeg,.png,.txt,.srt,.sub,.idx,.lnk,.exe,.vsmeta,.edl"
    orphan_extensions_str = os.environ.get('ORPHAN_EXTENSIONS', default_orphan_extensions_str)
    ORPHAN_EXTENSIONS = [ext.strip().lower() for ext in orphan_extensions_str.split(',') if ext.strip()]

    #Configuration du chemin JSON du script seedbox
    PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT = os.environ.get('PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT')

    # PLEX_LIBRARY_ROOTS et PLEX_BASE_PATH_GUARD sont déterminés dynamiquement dans les routes de Plex Web Editor.

    # --- Configurations pour SeedboxWebUI ---
    STAGING_DIR = os.environ.get('STAGING_DIR')
    SONARR_URL = os.environ.get('SONARR_URL')
    SONARR_API_KEY = os.environ.get('SONARR_API_KEY')
    RADARR_URL = os.environ.get('RADARR_URL')
    RADARR_API_KEY = os.environ.get('RADARR_API_KEY')
    PENDING_TORRENTS_MAP_FILE = os.getenv('PENDING_TORRENTS_MAP_FILE', 'pending_torrents_map.json')

    # --- rTorrent/ruTorrent httprpc API Configuration ---
    RUTORRENT_API_URL = os.getenv('RUTORRENT_API_URL') # Full URL to action.php
    RUTORRENT_USER = os.getenv('RUTORRENT_USER')
    RUTORRENT_PASSWORD = os.getenv('RUTORRENT_PASSWORD')
    # Convert string 'False' or 'True' to boolean for SEEDBOX_SSL_VERIFY
    _raw_ssl_verify = os.getenv('SEEDBOX_SSL_VERIFY', 'False') # Default to 'False' as string
    SEEDBOX_SSL_VERIFY = _raw_ssl_verify.lower() in ['true', '1', 't', 'yes']

    RTORRENT_LABEL_SONARR = os.getenv('RTORRENT_LABEL_SONARR', 'sonarr') # Default label
    RTORRENT_LABEL_RADARR = os.getenv('RTORRENT_LABEL_RADARR', 'radarr') # Default label

    # These are the initial download directories rTorrent will be instructed to use
    # Ensure your rTorrent user has write permissions to these paths on the seedbox
    # And that your rTorrent setup (e.g. autotools) might monitor these or use labels for further sorting.
    RTORRENT_DOWNLOAD_DIR_SONARR = os.getenv('RTORRENT_DOWNLOAD_DIR_SONARR', '/downloads/incomplete/sonarr_temp/') # Example
    RTORRENT_DOWNLOAD_DIR_RADARR = os.getenv('RTORRENT_DOWNLOAD_DIR_RADARR', '/downloads/incomplete/radarr_temp/') # Example

    # --- Configuration Globale Flask ---
    # Le mode DEBUG est souvent activé par FLASK_DEBUG=1 dans .env,
    # et lu par Flask directement ou par app.config['DEBUG'] si vous le chargez.
    # Ici, on s'assure qu'il y a une valeur par défaut si FLASK_DEBUG n'est pas dans .env
    DEBUG = os.environ.get('FLASK_DEBUG', '0').lower() in ('true', '1', 't')


    # --- Vérifications et Avertissements au Démarrage (Fusionnés) ---
    # Afficher une seule fois pour chaque catégorie de problème
    missing_configs = []
    if not PLEX_URL: missing_configs.append("PLEX_URL")
    if not PLEX_TOKEN: missing_configs.append("PLEX_TOKEN")
    if not SECRET_KEY or SECRET_KEY == 'une-cle-secrete-tres-forte-et-aleatoire-a-definir-absolument':
        missing_configs.append("SECRET_KEY (non sécurisée ou manquante)")

    # Pour SeedboxWebUI (si vous voulez les rendre obligatoires)
    if not STAGING_DIR: missing_configs.append("STAGING_DIR")
    if not SONARR_URL: missing_configs.append("SONARR_URL")
    if not SONARR_API_KEY: missing_configs.append("SONARR_API_KEY")
    if not RADARR_URL: missing_configs.append("RADARR_URL")
    if not RADARR_API_KEY: missing_configs.append("RADARR_API_KEY")

    if missing_configs:
        print("-------------------------------------------------------------------------------")
        print("ATTENTION : Variables de configuration manquantes ou non sécurisées dans .env !")
        for msg in missing_configs:
            print(f"            - {msg}")
        print("            Veuillez les définir correctement dans votre fichier .env.")
        print("-------------------------------------------------------------------------------")

    # Avertissement pour le mode de nettoyage (déjà bien dans votre code)
    if not PERFORM_ACTUAL_DELETION:
        print("-----------------------------------------------------------------------------------")
        print("INFO      : Mode SIMULATION (Dry Run) activé pour le nettoyage des dossiers.")
        print("            (PERFORM_ACTUAL_DELETION est 'False' ou non défini dans .env)")
        print("-----------------------------------------------------------------------------------")
    else:
        print("-----------------------------------------------------------------------------------")
        print("ATTENTION : Mode SUPPRESSION RÉELLE activé pour le nettoyage des dossiers !")
        print("            (PERFORM_ACTUAL_DELETION est 'True' dans .env)")
        print("-----------------------------------------------------------------------------------")

    print(f"INFO      : Extensions orphelines pour nettoyage : {ORPHAN_EXTENSIONS}")

    # Vous pouvez ajouter d'autres configurations globales ici si nécessaire
    # Par exemple : ITEMS_PER_PAGE = 50
    SEEDBOX_SFTP_HOST = os.environ.get('SEEDBOX_SFTP_HOST')
    SEEDBOX_SFTP_PORT = int(os.environ.get('SEEDBOX_SFTP_PORT') or 22) # Mettre un port par défaut
    SEEDBOX_SFTP_USER = os.environ.get('SEEDBOX_SFTP_USER')
    SEEDBOX_SFTP_PASSWORD = os.environ.get('SEEDBOX_SFTP_PASSWORD')
    SEEDBOX_SONARR_FINISHED_PATH = os.environ.get('SEEDBOX_SONARR_FINISHED_PATH')
    SEEDBOX_RADARR_FINISHED_PATH = os.environ.get('SEEDBOX_RADARR_FINISHED_PATH')
    SEEDBOX_SONARR_WORKING_PATH = os.environ.get('SEEDBOX_SONARR_WORKING_PATH')
    SEEDBOX_RADARR_WORKING_PATH = os.environ.get('SEEDBOX_RADARR_WORKING_PATH')