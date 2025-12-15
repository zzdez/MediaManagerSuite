import os
import json
import time
import re
import logging
from flask import current_app

logger = logging.getLogger(__name__)

def get_ygg_cookie_status():
    """
    Scans the configured download path for the latest YGG cookie file,
    validates its contents and expiration date, and returns a detailed status.
    """
    default_status = {
        "cookie_string": "",
        "is_valid": False,
        "expires_in_seconds": 0,
        "status_message": "Non configuré ou invalide."
    }

    # 1a. Trouver le fichier le plus récent
    try:
        download_path = current_app.config.get('COOKIE_DOWNLOAD_PATH')
        if not download_path:
            download_path = os.path.join(os.path.expanduser('~'), 'Downloads')
            logger.info(f"COOKIE_DOWNLOAD_PATH non défini, utilisation du répertoire par défaut : {download_path}")

        if not os.path.isdir(download_path):
            msg = f"Le répertoire de cookies '{download_path}' est invalide ou n'existe pas."
            logger.error(msg)
            return {**default_status, "status_message": msg}

        # Scan flexible (Regex) pour trouver tous les fichiers YGG quel que soit le domaine (.top, .org, etc.)
        # Pattern: www.yggtorrent.[n'importe quoi]_cookies[optionnel].json
        pattern = re.compile(r'^www\.yggtorrent\..+_cookies.*\.json$', re.IGNORECASE)

        all_files = os.listdir(download_path)
        cookie_files = [
            os.path.join(download_path, f)
            for f in all_files
            if pattern.match(f)
        ]

        if not cookie_files:
            msg = f"Aucun fichier de cookie trouvé dans '{download_path}'."
            logger.warning(msg)
            return {**default_status, "status_message": "Aucun fichier de cookie trouvé."}

        latest_file = max(cookie_files, key=os.path.getmtime)
        logger.info(f"Fichier de cookie le plus récent trouvé : {latest_file}")

    except Exception as e:
        msg = f"Erreur lors de la recherche du fichier de cookie : {e}"
        logger.error(msg, exc_info=True)
        return {**default_status, "status_message": msg}

    # 1b. Lire et parser le fichier
    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            cookies_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        msg = f"Impossible de lire ou parser le fichier cookie '{os.path.basename(latest_file)}': {e}"
        logger.error(msg)
        return {**default_status, "status_message": msg}

    # 1c. Vérifier la validité
    essential_cookies_info = {'cf_clearance': None, 'ygg_': None}
    all_cookies_map = {cookie['name']: cookie for cookie in cookies_data}

    for name in essential_cookies_info:
        if name in all_cookies_map:
            essential_cookies_info[name] = all_cookies_map[name]

    if not all(essential_cookies_info.values()):
        missing = [k for k, v in essential_cookies_info.items() if v is None]
        return {**default_status, "status_message": f"Cookie(s) essentiel(s) manquant(s): {', '.join(missing)}"}

    now = time.time()
    soonest_expiry = float('inf')

    for name, cookie in essential_cookies_info.items():
        expiry = cookie.get('expirationDate')
        logger.debug(f"Vérification du cookie '{name}': Timestamp d'expiration = {expiry}, Heure actuelle = {now}")
        if not expiry or expiry < now:
            msg = f"Le cookie '{name}' est expiré."
            logger.warning(msg)
            return {**default_status, "status_message": msg}
        soonest_expiry = min(soonest_expiry, expiry)

    # 1d. Construire la chaîne de cookie et retourner l'état
    cookie_parts = [f"{name}={cookie['value']}" for name, cookie in all_cookies_map.items()]
    cookie_string = "; ".join(cookie_parts)
    expires_in_seconds = int(soonest_expiry - now)

    minutes_left = expires_in_seconds // 60
    status_message = f"Valide (~{minutes_left} min)" if minutes_left > 0 else "Valide (< 1 min)"

    # Étape 3 (Optionnel, mais implémenté ici) : Nettoyage Automatique
    try:
        for file_path in cookie_files:
            if file_path != latest_file:
                os.remove(file_path)
                logger.info(f"Nettoyage : suppression de l'ancien fichier de cookie '{os.path.basename(file_path)}'")
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage des anciens fichiers de cookie : {e}", exc_info=True)

    return {
        "cookie_string": cookie_string,
        "is_valid": True,
        "expires_in_seconds": expires_in_seconds,
        "status_message": status_message
    }
