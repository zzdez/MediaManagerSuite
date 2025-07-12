# config.py (pour le projet fusionné MediaManagerSuite)
# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

# --- Configuration des Chemins de Base ---
basedir = os.path.abspath(os.path.dirname(__file__))
INSTANCE_FOLDER_PATH = os.path.join(basedir, 'instance')

dotenv_path = os.path.join(basedir, '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, verbose=True)
else:
    print(f"ATTENTION: Le fichier .env n'a pas été trouvé à: {dotenv_path}")
    print("           Les variables d'environnement pourraient ne pas être chargées.")

class Config:
    # --- FLASK CORE ---
    FLASK_APP = os.getenv('FLASK_APP', 'run.py').split('#')[0].strip()
    SECRET_KEY = os.getenv('SECRET_KEY', 'une-cle-secrete-tres-forte-et-aleatoire-a-definir-absolument')
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').split('#')[0].strip().lower() in ('true', '1', 't')
    APP_PASSWORD = os.getenv('APP_PASSWORD')

    # --- PLEX ---
    PLEX_URL = os.getenv('PLEX_URL')
    PLEX_TOKEN = os.getenv('PLEX_TOKEN')

    # --- *ARR SUITE ---
    SONARR_URL = os.getenv('SONARR_URL')
    SONARR_API_KEY = os.getenv('SONARR_API_KEY')
    DEFAULT_SONARR_ROOT_FOLDER = os.getenv('DEFAULT_SONARR_ROOT_FOLDER')
    DEFAULT_SONARR_PROFILE_ID = int(os.getenv('DEFAULT_SONARR_PROFILE_ID', '1').split('#')[0].strip())

    RADARR_URL = os.getenv('RADARR_URL')
    RADARR_API_KEY = os.getenv('RADARR_API_KEY')
    DEFAULT_RADARR_ROOT_FOLDER = os.getenv('DEFAULT_RADARR_ROOT_FOLDER')
    DEFAULT_RADARR_PROFILE_ID = int(os.getenv('DEFAULT_RADARR_PROFILE_ID', '1').split('#')[0].strip())
    RADARR_TAG_ON_ARCHIVE = os.getenv('RADARR_TAG_ON_ARCHIVE', 'vu').split('#')[0].strip()

    PROWLARR_URL = os.getenv('PROWLARR_URL')
    PROWLARR_API_KEY = os.getenv('PROWLARR_API_KEY')

    # --- SEEDBOX: rTORRENT/ruTORRENT API ---
    RTORRENT_API_URL = os.getenv('RTORRENT_API_URL')
    RTORRENT_USER = os.getenv('RTORRENT_USER')
    RTORRENT_PASSWORD = os.getenv('RTORRENT_PASSWORD')
    RTORRENT_SSL_VERIFY = os.getenv('RTORRENT_SSL_VERIFY', 'False').split('#')[0].strip().lower() in ('true', '1', 't')

    # --- SEEDBOX: SFTP ---
    SEEDBOX_SFTP_HOST = os.getenv('SEEDBOX_SFTP_HOST')
    SEEDBOX_SFTP_PORT = int(os.getenv('SEEDBOX_SFTP_PORT', '22').split('#')[0].strip())
    SEEDBOX_SFTP_USER = os.getenv('SEEDBOX_SFTP_USER')
    SEEDBOX_SFTP_PASSWORD = os.getenv('SEEDBOX_SFTP_PASSWORD')

    # --- PATHS & DIRECTORIES ---
    # -- Chemins LOCAUX (sur la machine qui exécute MMS) --
    LOCAL_STAGING_PATH = os.getenv('LOCAL_STAGING_PATH')
    LOCAL_PROCESSED_LOG_PATH = os.getenv('LOCAL_PROCESSED_LOG_PATH', os.path.join(INSTANCE_FOLDER_PATH, 'processed_sftp_items.json'))

    # -- Chemins DISTANTS (sur la seedbox Linux) --
    RTORRENT_LABEL_SONARR = os.getenv('RTORRENT_LABEL_SONARR', 'sonarr')
    RTORRENT_LABEL_RADARR = os.getenv('RTORRENT_LABEL_RADARR', 'radarr')
    SEEDBOX_RTORRENT_INCOMING_SONARR_PATH = os.getenv('SEEDBOX_RTORRENT_INCOMING_SONARR_PATH')
    SEEDBOX_RTORRENT_INCOMING_RADARR_PATH = os.getenv('SEEDBOX_RTORRENT_INCOMING_RADARR_PATH')
    SEEDBOX_SCANNER_TARGET_SONARR_PATH = os.getenv('SEEDBOX_SCANNER_TARGET_SONARR_PATH')
    SEEDBOX_SCANNER_TARGET_RADARR_PATH = os.getenv('SEEDBOX_SCANNER_TARGET_RADARR_PATH')
    SEEDBOX_SCANNER_WORKING_SONARR_PATH = os.getenv('SEEDBOX_SCANNER_WORKING_SONARR_PATH')
    SEEDBOX_SCANNER_WORKING_RADARR_PATH = os.getenv('SEEDBOX_SCANNER_WORKING_RADARR_PATH')
    
    # --- YGGTORENT ---
    YGG_INDEXER_ID = os.getenv('YGG_INDEXER_ID')
    YGG_BASE_URL = os.getenv('YGG_BASE_URL', 'https://www.yggtorrent.top')
    YGG_COOKIE = os.getenv('YGG_COOKIE')
    YGG_USER_AGENT = os.getenv('YGG_USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36')

    # --- ADVANCED & TASKS ---
    SCHEDULER_SFTP_SCAN_INTERVAL_MINUTES = int(os.getenv('SCHEDULER_SFTP_SCAN_INTERVAL_MINUTES', '15').split('#')[0].strip())
    ORPHAN_CLEANER_PERFORM_DELETION = os.getenv('ORPHAN_CLEANER_PERFORM_DELETION', 'False').split('#')[0].strip().lower() in ('true', '1', 't')
    _default_orphan_extensions_str = ".nfo,.jpg,.jpeg,.png,.txt,.srt,.sub,.idx,.lnk,.exe,.vsmeta,.edl"
    _orphan_extensions_env = os.getenv('ORPHAN_CLEANER_EXTENSIONS', _default_orphan_extensions_str).split('#')[0].strip()
    ORPHAN_CLEANER_EXTENSIONS = [ext.strip().lower() for ext in _orphan_extensions_env.split(',') if ext.strip()]
    MMS_API_PROCESS_STAGING_URL = os.getenv('MMS_API_PROCESS_STAGING_URL', f"http://127.0.0.1:{os.getenv('FLASK_RUN_PORT', '5001').split('#')[0].strip()}/seedbox/process-staging-item")
    SFTP_SCANNER_GUARDFRAIL_ENABLED = os.getenv('SFTP_SCANNER_GUARDFRAIL_ENABLED', 'True').split('#')[0].strip().lower() in ('true', '1', 't')


    # --- Anciennes variables (à supprimer/migrer après vérification que plus rien ne les utilise) ---
    PENDING_TORRENTS_MAP_FILE = os.getenv(
        'PENDING_TORRENTS_MAP_FILE',
        os.path.join(INSTANCE_FOLDER_PATH, 'pending_torrents_map.json')
    ) # Si utilisé, vérifier sa pertinence ou migrer vers LOCAL_PROCESSED_LOG_PATH si fonction similaire
    RTORRENT_POST_ADD_DELAY_SECONDS = int(os.getenv('RTORRENT_POST_ADD_DELAY_SECONDS', '3').split('#')[0].strip()) # Spécifique à rTorrent, garder si pertinent
    # SFTP_SCANNER_GUARDFRAIL_ENABLED = os.getenv('SFTP_SCANNER_GUARDFRAIL_ENABLED', 'True').lower() == 'true' # Garder si cette logique est toujours utilisée


# --- FIN DE LA CLASSE CONFIG ---


# --- Section de vérification et d'avertissements (exécutée une seule fois au démarrage) ---
def check_and_print_startup_info():
    if not Config.APP_PASSWORD:
        print("-" * 70)
        print("ATTENTION : Le mot de passe pour l'application (APP_PASSWORD) n'est pas défini dans .env !")
        print("            L'accès à la page de configuration ne sera pas sécurisé.")
        print("-" * 70)

    _missing_configs = []
    if not Config.PLEX_URL: _missing_configs.append("PLEX_URL")
    if not Config.PLEX_TOKEN: _missing_configs.append("PLEX_TOKEN")
    if not Config.SECRET_KEY or Config.SECRET_KEY == 'une-cle-secrete-tres-forte-et-aleatoire-a-definir-absolument':
        _missing_configs.append("SECRET_KEY (non sécurisée ou manquante)")
    if not Config.LOCAL_STAGING_PATH: _missing_configs.append("LOCAL_STAGING_PATH (anciennement STAGING_DIR)")
    if not Config.SONARR_URL: _missing_configs.append("SONARR_URL")
    if not Config.SONARR_API_KEY: _missing_configs.append("SONARR_API_KEY")
    if not Config.RADARR_URL: _missing_configs.append("RADARR_URL")
    if not Config.RADARR_API_KEY: _missing_configs.append("RADARR_API_KEY")
    if not Config.PROWLARR_URL: _missing_configs.append("PROWLARR_URL")
    if not Config.PROWLARR_API_KEY: _missing_configs.append("PROWLARR_API_KEY")
    if not Config.RTORRENT_API_URL: _missing_configs.append("RTORRENT_API_URL")
    if not Config.SEEDBOX_SFTP_HOST: _missing_configs.append("SEEDBOX_SFTP_HOST")
    if not Config.MMS_API_PROCESS_STAGING_URL: _missing_configs.append("MMS_API_PROCESS_STAGING_URL")


    if _missing_configs:
        print("-" * 70)
        print("ATTENTION : Variables de configuration manquantes ou non sécurisées dans .env !")
        for msg in _missing_configs:
            print(f"            - {msg}")
        print("            Veuillez les définir correctement dans votre fichier .env.")
        print("-" * 70)

    if not Config.ORPHAN_CLEANER_PERFORM_DELETION:
        print("-" * 70)
        print("INFO      : Mode SIMULATION (Dry Run) activé pour le nettoyage des dossiers.")
        print("            (ORPHAN_CLEANER_PERFORM_DELETION est 'False' ou non défini dans .env)")
        print("-" * 70)
    else:
        print("-" * 70)
        print("ATTENTION : Mode SUPPRESSION RÉELLE activé pour le nettoyage des dossiers !")
        print("            (ORPHAN_CLEANER_PERFORM_DELETION est 'True' dans .env)")
        print("-" * 70)

    print(f"INFO      : Extensions orphelines pour nettoyage : {Config.ORPHAN_CLEANER_EXTENSIONS}")
    # print(f"INFO      : Fichier de mapping des torrents configuré pour : {Config.PENDING_TORRENTS_MAP_FILE}") # Commenté car PENDING_TORRENTS_MAP_FILE est marqué comme ancien

# Appeler la fonction de vérification au moment de l'import du module config
check_and_print_startup_info()

# --- Fin de la classe Config ---

# Pour tester si les variables sont bien chargées (optionnel, commenter après vérification)
# if __name__ == '__main__':
#     print(f"Config.SECRET_KEY: {Config.SECRET_KEY}")
#     print(f"Config.FLASK_DEBUG: {Config.FLASK_DEBUG}")
#     print(f"Config.APP_PASSWORD: {Config.APP_PASSWORD}")
#     print(f"Config.PLEX_URL: {Config.PLEX_URL}")
#     print(f"Config.PLEX_TOKEN: {Config.PLEX_TOKEN}")
#     print(f"Config.SONARR_URL: {Config.SONARR_URL}")
#     print(f"Config.SONARR_API_KEY: {Config.SONARR_API_KEY}")
#     print(f"Config.RADARR_URL: {Config.RADARR_URL}")
#     print(f"Config.RADARR_API_KEY: {Config.RADARR_API_KEY}")
#     print(f"Config.PROWLARR_URL: {Config.PROWLARR_URL}")
#     print(f"Config.PROWLARR_API_KEY: {Config.PROWLARR_API_KEY}")
#     print(f"Config.RTORRENT_API_URL: {Config.RTORRENT_API_URL}")
#     print(f"Config.RTORRENT_USER: {Config.RTORRENT_USER}")
#     print(f"Config.RTORRENT_PASSWORD: {Config.RTORRENT_PASSWORD}")
#     print(f"Config.RTORRENT_SSL_VERIFY: {Config.RTORRENT_SSL_VERIFY}")
#     print(f"Config.SEEDBOX_SFTP_HOST: {Config.SEEDBOX_SFTP_HOST}")
#     print(f"Config.SEEDBOX_SFTP_PORT: {Config.SEEDBOX_SFTP_PORT}")
#     print(f"Config.SEEDBOX_SFTP_USER: {Config.SEEDBOX_SFTP_USER}")
#     print(f"Config.SEEDBOX_SFTP_PASSWORD: {Config.SEEDBOX_SFTP_PASSWORD}")
#     print(f"Config.LOCAL_STAGING_PATH: {Config.LOCAL_STAGING_PATH}")
#     print(f"Config.LOCAL_PROCESSED_LOG_PATH: {Config.LOCAL_PROCESSED_LOG_PATH}")
#     print(f"Config.RTORRENT_LABEL_SONARR: {Config.RTORRENT_LABEL_SONARR}")
#     print(f"Config.RTORRENT_LABEL_RADARR: {Config.RTORRENT_LABEL_RADARR}")
#     print(f"Config.SEEDBOX_RTORRENT_INCOMING_SONARR_PATH: {Config.SEEDBOX_RTORRENT_INCOMING_SONARR_PATH}")
#     print(f"Config.SEEDBOX_RTORRENT_INCOMING_RADARR_PATH: {Config.SEEDBOX_RTORRENT_INCOMING_RADARR_PATH}")
#     print(f"Config.SEEDBOX_SCANNER_TARGET_SONARR_PATH: {Config.SEEDBOX_SCANNER_TARGET_SONARR_PATH}")
#     print(f"Config.SEEDBOX_SCANNER_TARGET_RADARR_PATH: {Config.SEEDBOX_SCANNER_TARGET_RADARR_PATH}")
#     print(f"Config.SEEDBOX_SCANNER_WORKING_SONARR_PATH: {Config.SEEDBOX_SCANNER_WORKING_SONARR_PATH}")
#     print(f"Config.SEEDBOX_SCANNER_WORKING_RADARR_PATH: {Config.SEEDBOX_SCANNER_WORKING_RADARR_PATH}")
#     print(f"Config.YGG_INDEXER_ID: {Config.YGG_INDEXER_ID}")
#     print(f"Config.YGG_BASE_URL: {Config.YGG_BASE_URL}")
#     print(f"Config.YGG_COOKIE: {Config.YGG_COOKIE}")
#     print(f"Config.YGG_USER_AGENT: {Config.YGG_USER_AGENT}")
#     print(f"Config.SCHEDULER_SFTP_SCAN_INTERVAL_MINUTES: {Config.SCHEDULER_SFTP_SCAN_INTERVAL_MINUTES}")
#     print(f"Config.ORPHAN_CLEANER_PERFORM_DELETION: {Config.ORPHAN_CLEANER_PERFORM_DELETION}")
#     print(f"Config.ORPHAN_CLEANER_EXTENSIONS: {Config.ORPHAN_CLEANER_EXTENSIONS}")
#     print(f"Instance folder path: {INSTANCE_FOLDER_PATH}")
#     if not os.path.exists(INSTANCE_FOLDER_PATH):
#         try:
#             os.makedirs(INSTANCE_FOLDER_PATH)
#             print(f"Dossier 'instance' créé à : {INSTANCE_FOLDER_PATH}")
#         except OSError as e:
#             print(f"Erreur lors de la création du dossier 'instance' : {e}")
#     else:
#         print(f"Le dossier 'instance' existe déjà à : {INSTANCE_FOLDER_PATH}")