import os
import json
import time
from flask import current_app

def get_ygg_cookie_status():
    """
    Lit le fichier ygg_cookies.json, vérifie la validité des cookies essentiels,
    et retourne un dictionnaire d'état.

    Returns:
        dict: Un dictionnaire contenant la chaîne de cookie, sa validité,
              et le temps en secondes avant l'expiration.
    """
    default_status = {
        "cookie_string": "",
        "is_valid": False,
        "expires_in_seconds": 0,
        "status_message": "Fichier de cookie non trouvé ou non configuré."
    }

    instance_path = current_app.instance_path
    cookie_file_path = os.path.join(instance_path, 'ygg_cookies.json')

    if not os.path.exists(cookie_file_path):
        return default_status

    try:
        with open(cookie_file_path, 'r') as f:
            cookies_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        current_app.logger.error(f"Impossible de lire ou parser ygg_cookies.json: {e}")
        return {**default_status, "status_message": f"Erreur de lecture du fichier cookie : {e}"}

    essential_cookies_info = {
        'cf_clearance': None,
        'ygg_': None
    }

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
        if not expiry or expiry < now:
            return {**default_status, "status_message": f"Le cookie '{name}' est expiré."}
        soonest_expiry = min(soonest_expiry, expiry)

    # Construire la chaîne de cookie finale à partir de tous les cookies du fichier
    cookie_parts = []
    # Prioriser les cookies essentiels dans l'ordre
    for name in ['cf_clearance', 'ygg_']:
         if name in all_cookies_map:
            cookie_parts.append(f"{name}={all_cookies_map[name]['value']}")

    # Ajouter les autres cookies
    for name, cookie in all_cookies_map.items():
        if name not in ['cf_clearance', 'ygg_']:
            cookie_parts.append(f"{name}={cookie['value']}")

    cookie_string = "; ".join(cookie_parts)
    expires_in_seconds = int(soonest_expiry - now)

    minutes_left = expires_in_seconds // 60
    status_message = f"Valide (expire dans ~{minutes_left} min)" if minutes_left > 0 else "Valide (expire dans moins d'une minute)"

    return {
        "cookie_string": cookie_string,
        "is_valid": True,
        "expires_in_seconds": expires_in_seconds,
        "status_message": status_message
    }
