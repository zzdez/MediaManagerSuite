# config.py (pour le projet fusionné MediaManagerSuite)
# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

# --- Configuration des Chemins de Base ---
# 'basedir' est la racine du projet MediaManagerSuite (là où se trouve ce fichier config.py, run.py, le dossier app/, etc.)
basedir = os.path.abspath(os.path.dirname(__file__))
INSTANCE_FOLDER_PATH = os.path.join(basedir, 'instance') # Le dossier 'instance/' sera à la racine du projet

# Chargement du fichier .env
dotenv_path = os.path.join(basedir, '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, verbose=True)
else:
    print(f"ATTENTION: Le fichier .env n'a pas été trouvé à l'emplacement attendu: {dotenv_path}")
    print("           Les variables d'environnement pourraient ne pas être chargées.")
    print("           Assurez-vous qu'il existe et qu'il est à la racine du projet.")

class Config:
    # --- Clé Secrète Globale ---
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'une-cle-secrete-tres-forte-et-aleatoire-a-definir-absolument'

    # --- Configuration Globale Flask ---
    DEBUG = os.environ.get('FLASK_DEBUG', '0').lower() in ('true', '1', 't')

    # --- Configurations pour Plex Web Editor ---
    PLEX_URL = os.environ.get('PLEX_URL')
    PLEX_TOKEN = os.environ.get('PLEX_TOKEN')
    PERFORM_ACTUAL_DELETION = os.environ.get('PERFORM_ACTUAL_DELETION', 'False').lower() in ('true', '1', 't')
    default_orphan_extensions_str = ".nfo,.jpg,.jpeg,.png,.txt,.srt,.sub,.idx,.lnk,.exe,.vsmeta,.edl"
    orphan_extensions_str = os.environ.get('ORPHAN_EXTENSIONS', default_orphan_extensions_str)
    ORPHAN_EXTENSIONS = [ext.strip().lower() for ext in orphan_extensions_str.split(',') if ext.strip()]

    # --- Configurations pour Seedbox UI / Torrent Management ---
    STAGING_DIR = os.environ.get('STAGING_DIR')
    SONARR_URL = os.environ.get('SONARR_URL')
    SONARR_API_KEY = os.environ.get('SONARR_API_KEY')
    RADARR_URL = os.environ.get('RADARR_URL')
    RADARR_API_KEY = os.environ.get('RADARR_API_KEY')

    # NOUVELLE CONFIGURATION pour le fichier de mapping des torrents dans le dossier 'instance'
    PENDING_TORRENTS_MAP_FILE = os.environ.get(
        'PENDING_TORRENTS_MAP_FILE',
        os.path.join(INSTANCE_FOLDER_PATH, 'pending_torrents_map.json')
    )

    # --- rTorrent/ruTorrent httprpc API Configuration ---
    RUTORRENT_API_URL = os.getenv('RUTORRENT_API_URL')
    RUTORRENT_USER = os.getenv('RUTORRENT_USER')
    RUTORRENT_PASSWORD = os.getenv('RUTORRENT_PASSWORD')
    _raw_ssl_verify = os.getenv('SEEDBOX_SSL_VERIFY', 'False')
    SEEDBOX_SSL_VERIFY = _raw_ssl_verify.lower() in ['true', '1', 't', 'yes']
    RTORRENT_LABEL_SONARR = os.getenv('RTORRENT_LABEL_SONARR', 'sonarr')
    RTORRENT_LABEL_RADARR = os.getenv('RTORRENT_LABEL_RADARR', 'radarr')
    RTORRENT_DOWNLOAD_DIR_SONARR = os.getenv('RTORRENT_DOWNLOAD_DIR_SONARR', '/downloads/incomplete/sonarr_temp/')
    RTORRENT_DOWNLOAD_DIR_RADARR = os.getenv('RTORRENT_DOWNLOAD_DIR_RADARR', '/downloads/incomplete/radarr_temp/')

    # --- SFTP Configuration (utilisé par remote_seedbox_view et potentiellement sftp_downloader_notifier.py) ---
    SEEDBOX_SFTP_HOST = os.environ.get('SEEDBOX_SFTP_HOST')
    SEEDBOX_SFTP_PORT = int(os.environ.get('SEEDBOX_SFTP_PORT', 22)) # Port SFTP par défaut est 22
    SEEDBOX_SFTP_USER = os.environ.get('SEEDBOX_SFTP_USER')
    SEEDBOX_SFTP_PASSWORD = os.environ.get('SEEDBOX_SFTP_PASSWORD')
    # Chemins sur la seedbox (pour remote_seedbox_view ou information)
    SEEDBOX_SONARR_FINISHED_PATH = os.environ.get('SEEDBOX_SONARR_FINISHED_PATH')
    SEEDBOX_RADARR_FINISHED_PATH = os.environ.get('SEEDBOX_RADARR_FINISHED_PATH')
    SEEDBOX_SONARR_WORKING_PATH = os.environ.get('SEEDBOX_SONARR_WORKING_PATH')
    SEEDBOX_RADARR_WORKING_PATH = os.environ.get('SEEDBOX_RADARR_WORKING_PATH')

    # Configuration du chemin JSON utilisé par le script sftp_downloader_notifier.py (si pertinent pour MMS)
    PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT = os.environ.get('PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT')


    # --- Vérifications et Avertissements au Démarrage ---
    # (Cette section est exécutée à l'import de Config, donc une seule fois au démarrage de l'app)
    _missing_configs = []
    if not PLEX_URL: _missing_configs.append("PLEX_URL")
    if not PLEX_TOKEN: _missing_configs.append("PLEX_TOKEN")
    if not SECRET_KEY or SECRET_KEY == 'une-cle-secrete-tres-forte-et-aleatoire-a-definir-absolument':
        _missing_configs.append("SECRET_KEY (non sécurisée ou manquante)")
    if not STAGING_DIR: _missing_configs.append("STAGING_DIR")
    if not SONARR_URL: _missing_configs.append("SONARR_URL")
    if not SONARR_API_KEY: _missing_configs.append("SONARR_API_KEY")
    if not RADARR_URL: _missing_configs.append("RADARR_URL")
    if not RADARR_API_KEY: _missing_configs.append("RADARR_API_KEY")
    # Vous pouvez ajouter des vérifications pour RUTORRENT_API_URL etc. si elles sont critiques

    if _missing_configs:
        print("-" * 70)
        print("ATTENTION : Variables de configuration manquantes ou non sécurisées dans .env !")
        for msg in _missing_configs:
            print(f"            - {msg}")
        print("            Veuillez les définir correctement dans votre fichier .env.")
        print("-" * 70)

    if not PERFORM_ACTUAL_DELETION:
        print("-" * 70)
        print("INFO      : Mode SIMULATION (Dry Run) activé pour le nettoyage des dossiers.")
        print("            (PERFORM_ACTUAL_DELETION est 'False' ou non défini dans .env)")
        print("-" * 70)
    else:
        print("-" * 70)
        print("ATTENTION : Mode SUPPRESSION RÉELLE activé pour le nettoyage des dossiers !")
        print("            (PERFORM_ACTUAL_DELETION est 'True' dans .env)")
        print("-" * 70)

    print(f"INFO      : Extensions orphelines pour nettoyage : {ORPHAN_EXTENSIONS}")
    print(f"INFO      : Fichier de mapping des torrents configuré pour : {PENDING_TORRENTS_MAP_FILE}")

# --- Fin de la classe Config ---

# Pour tester si les variables sont bien chargées (optionnel, commenter après vérification)
# if __name__ == '__main__':
#     print(f"Config.SECRET_KEY: {Config.SECRET_KEY}")
#     print(f"Config.PLEX_URL: {Config.PLEX_URL}")
#     print(f"Config.STAGING_DIR: {Config.STAGING_DIR}")
#     print(f"Config.PENDING_TORRENTS_MAP_FILE: {Config.PENDING_TORRENTS_MAP_FILE}")
#     print(f"Config.DEBUG: {Config.DEBUG}")
#     print(f"Instance folder path: {INSTANCE_FOLDER_PATH}")
#     # Vérifier si le dossier instance existe, sinon le créer
#     if not os.path.exists(INSTANCE_FOLDER_PATH):
#         try:
#             os.makedirs(INSTANCE_FOLDER_PATH)
#             print(f"Dossier 'instance' créé à : {INSTANCE_FOLDER_PATH}")
#         except OSError as e:
#             print(f"Erreur lors de la création du dossier 'instance' : {e}")
#     else:
#         print(f"Le dossier 'instance' existe déjà à : {INSTANCE_FOLDER_PATH}")