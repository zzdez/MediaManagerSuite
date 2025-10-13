import os

# The source of truth for variable names and their order.
# Sections are represented by comments.
GOLDEN_ORDER = [
    "# --- FLASK CORE ---",
    "FLASK_APP",
    "FLASK_DEBUG",
    "SECRET_KEY",
    "APP_PASSWORD",
    "INTERNAL_API_KEY",
    "",
    "# --- PLEX ---",
    "PLEX_URL",
    "PLEX_TOKEN",
    "PLEX_LIBRARIES_TO_IGNORE",
    "",
    "# --- *ARR SUITE ---",
    "SONARR_URL",
    "SONARR_API_KEY",
    "DEFAULT_SONARR_ROOT_FOLDER",
    "DEFAULT_SONARR_PROFILE_ID",
    "RADARR_URL",
    "RADARR_API_KEY",
    "DEFAULT_RADARR_ROOT_FOLDER",
    "DEFAULT_RADARR_PROFILE_ID",
    "RADARR_TAG_ON_ARCHIVE",
    "PROWLARR_URL",
    "PROWLARR_API_KEY",
    "",
    "# --- SEEDBOX: rTORRENT/ruTORRENT API ---",
    "RTORRENT_API_URL",
    "RTORRENT_USER",
    "RTORRENT_PASSWORD",
    "RTORRENT_SSL_VERIFY",
    "",
    "# --- SEEDBOX: SFTP ---",
    "SEEDBOX_SFTP_HOST",
    "SEEDBOX_SFTP_PORT",
    "SEEDBOX_SFTP_USER",
    "SEEDBOX_SFTP_PASSWORD",
    "SEEDBOX_SFTP_REMOTE_PATH_MAPPING",
    "",
    "# --- PATHS & DIRECTORIES ---",
    "LOCAL_STAGING_PATH",
    "LOCAL_PROCESSED_LOG_PATH",
    "RTORRENT_LABEL_SONARR",
    "RTORRENT_LABEL_RADARR",
    "SEEDBOX_RTORRENT_INCOMING_SONARR_PATH",
    "SEEDBOX_RTORRENT_INCOMING_RADARR_PATH",
    "SEEDBOX_SCANNER_TARGET_SONARR_PATH",
    "SEEDBOX_SCANNER_TARGET_RADARR_PATH",
    "SEEDBOX_SCANNER_WORKING_SONARR_PATH",
    "SEEDBOX_SCANNER_WORKING_RADARR_PATH",
    "",
    "# --- YGGTORENT & FLARESOLVERR ---",
    "YGG_INDEXER_ID",
    "YGG_BASE_URL",
    "YGG_COOKIE",
    "YGG_USER_AGENT",
    "FLARESOLVERR_URL",
    "YGG_USERNAME",
    "YGG_PASSWORD",
    "YGG_PASSKEY",
    "YGG_DOMAIN",
    "COOKIE_DOWNLOAD_PATH",
    "",
    "# --- API Externes ---",
    "TVDB_API_KEY",
    "TVDB_PIN",
    "TMDB_API_KEY",
    "YOUTUBE_API_KEY",
    "GEMINI_API_KEY",
    "",
    "# --- ADVANCED & TASKS ---",
    "MMS_API_PROCESS_STAGING_URL",
    "SCHEDULER_SFTP_SCAN_INTERVAL_MINUTES",
    "SFTP_SCANNER_GUARDFRAIL_ENABLED",
    "ORPHAN_CLEANER_PERFORM_DELETION",
    "ORPHAN_CLEANER_EXTENSIONS",
    "MMS_ENV_FILE_PATH",
    "MMS_RESTART_COMMAND",
]

def parse_env_file(filepath):
    """Reads a .env file and returns a dictionary of key-value pairs."""
    env_vars = {}
    if not os.path.exists(filepath):
        return env_vars, f"Error: File not found at {filepath}"

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                # Store the most recently found value for a given key
                env_vars[key] = value
    return env_vars, None

def main():
    """Main function to clean the .env file."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, '.env')
    cleaned_env_path = os.path.join(project_root, '.env.cleaned')

    print(f"Reading existing .env file from: {env_path}")
    existing_vars, error = parse_env_file(env_path)
    if error:
        print(error)
        return

    print(f"Found {len(existing_vars)} variables to process.")

    with open(cleaned_env_path, 'w', encoding='utf-8') as f:
        for item in GOLDEN_ORDER:
            if item.startswith('#') or item == "":
                f.write(f"{item}\n")
            else:
                key = item
                value = existing_vars.get(key, '')
                f.write(f"{key}={value}\n")

    print(f"\nSuccessfully created cleaned .env file at: {cleaned_env_path}")
    print("Please review the file and, if it looks correct, you can replace your .env with it.")

if __name__ == "__main__":
    main()
