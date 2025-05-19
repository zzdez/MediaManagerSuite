import os
import shutil
import logging
from datetime import datetime
import requests # Pour les appels API
from requests.exceptions import RequestException # Pour gérer les erreurs de connexion

from flask import Blueprint, render_template, current_app, request, flash, redirect, url_for, jsonify

# Définition du Blueprint pour seedbox_ui
# Le Blueprint lui-même est défini dans app/seedbox_ui/__init__.py
# from . import seedbox_ui_bp # Ceci serait pour importer le bp si on en avait besoin ici, mais on l'utilise pour décorer les routes.
# Pour l'instant, on va supposer que les routes sont décorées avec un bp défini ailleurs (dans __init__.py)

# Création du Blueprint (normalement fait dans __init__.py, mais pour le contexte si ce fichier était autonome)
# Si tu as bien from . import seedbox_ui_bp dans routes.py et que seedbox_ui_bp = Blueprint(...) est dans __init__.py, c'est bon.
# Sinon, il faut s'assurer que seedbox_ui_bp est accessible ici.
# En regardant ton GitHub, __init__.py définit bien seedbox_ui_bp et routes.py l'importe avec:
# from app.seedbox_ui import seedbox_ui_bp
# C'est parfait.

# Configuration du logger pour ce module
logger = logging.getLogger(__name__)

# --- Fonctions Utilitaires pour les API Sonarr/Radarr ---

def _make_arr_request(method, url, api_key, params=None, json_data=None, timeout=30):
    """Fonction helper pour faire des requêtes génériques aux API *Arr."""
    headers = {
        'X-Api-Key': api_key,
        'Content-Type': 'application/json'
    }
    try:
        response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=timeout)
        response.raise_for_status() # Lève une exception pour les codes 4xx/5xx

        # Pour les commandes POST qui retournent 201 ou 202, ou GET qui retourne 200
        if response.status_code in [200, 201, 202]:
            # Si la réponse est JSON, la retourner, sinon True pour succès
            try:
                return response.json(), None
            except requests.exceptions.JSONDecodeError:
                return True, None # Succès sans corps JSON (ex: 201 Created)
        else:
            logger.warning(f"Réponse inattendue de {url} (Code: {response.status_code}): {response.text}")
            return None, f"Réponse inattendue de l'API (Code: {response.status_code})."

    except RequestException as e:
        logger.error(f"Erreur de communication avec l'API {url}: {e}")
        error_details = str(e)
        if "Failed to establish a new connection" in error_details:
            return None, f"Erreur : Impossible de se connecter. L'URL est-elle correcte et l'application *Arr est-elle lancée ?"
        elif "401" in error_details: # Unauthorized
             return None, f"Erreur 401 : Non autorisé. La clé API est-elle correcte ?"
        elif "403" in error_details: # Forbidden (souvent pour IP Whitelisting ou mauvais base URL)
            return None, f"Erreur 403 : Interdit. Vérifiez la configuration de l'API (ex: IP whitelist, base URL)."
        elif "404" in error_details: # Not Found
             return None, f"Erreur 404 : Non trouvé. L'URL de l'API ({url}) est-elle correcte ?"
        else:
            return None, f"Erreur de communication avec l'API : {error_details}"
    except Exception as e:
        logger.error(f"Erreur inattendue lors de l'appel API vers {url}: {e}")
        return None, f"Erreur inattendue : {e}"

def send_arr_command(base_url, api_key, command_name, item_path_to_scan=None):
    """Appelle l'API Sonarr/Radarr pour déclencher une commande (ex: scan)."""
    api_endpoint = f"{base_url.rstrip('/')}/api/v3/command"
    payload = {"name": command_name}

    if command_name in ["DownloadedEpisodesScan", "DownloadedMoviesScan"] and item_path_to_scan:
        payload["path"] = item_path_to_scan
        payload["importMode"] = "Move" # Tente de déplacer/supprimer après import
        # downloadClientId peut souvent être omis ou vide
        # payload["downloadClientId"] = ""

    # Pour d'autres commandes, des paramètres spécifiques peuvent être nécessaires
    # Par exemple, pour ManualImport, le payload serait différent.

    logger.info(f"Envoi de la commande '{command_name}' à {api_endpoint} avec le payload: {payload}")

    response_data, error_msg = _make_arr_request('POST', api_endpoint, api_key, json_data=payload)

    if error_msg:
        return False, error_msg

    # Un POST à /command retourne généralement un corps JSON avec les détails de la commande
    if response_data and isinstance(response_data, dict) and response_data.get('name') == command_name:
        logger.info(f"Commande '{command_name}' acceptée par {base_url} pour le chemin '{item_path_to_scan if item_path_to_scan else 'global'}'.")
        return True, f"Commande '{command_name}' envoyée avec succès."
    else:
        logger.warning(f"Réponse inattendue après la commande {command_name} à {base_url}: {response_data}")
        return False, f"Réponse inattendue de l'API après la commande. Vérifiez les logs de l'application *Arr."


# --- Routes du Blueprint seedbox_ui ---
# Assurez-vous que `seedbox_ui_bp` est importé depuis `app.seedbox_ui.__init__.py`
# Exemple d'import si `__init__.py` contient `seedbox_ui_bp = Blueprint(...)`:
from . import seedbox_ui_bp # Ou from app.seedbox_ui import seedbox_ui_bp si la structure l'exige

@seedbox_ui_bp.route('/')
def index():
    staging_dir = current_app.config.get('STAGING_DIR')
    if not staging_dir or not os.path.exists(staging_dir):
        flash(f"Le dossier de staging '{staging_dir}' n'est pas configuré ou n'existe pas.", 'danger')
        return render_template('seedbox_ui/index.html', items_details=[])

    items_in_staging = []
    try:
        items_in_staging = os.listdir(staging_dir)
    except OSError as e:
        flash(f"Erreur lors de la lecture du dossier '{staging_dir}': {e}", 'danger')
        return render_template('seedbox_ui/index.html', items_details=[])

    items_details = []
    for item_name in items_in_staging:
        item_path = os.path.join(staging_dir, item_name)
        try:
            is_dir = os.path.isdir(item_path)
            size_bytes_raw = 0 # Pour le tri

            if is_dir:
                # Pour la taille des dossiers, une estimation rapide ou N/A pour éviter la lenteur
                # Ici, je vais mettre N/A pour les dossiers pour l'instant, optimisation possible plus tard
                size_readable = "N/A (dossier)"
                # Si tu veux calculer la taille (peut être lent):
                # for dirpath, dirnames, filenames in os.walk(item_path):
                #     for f in filenames:
                #         fp = os.path.join(dirpath, f)
                #         if not os.path.islink(fp):
                #             size_bytes_raw += os.path.getsize(fp)
            else:
                size_bytes_raw = os.path.getsize(item_path)

            # Conversion taille lisible pour fichiers
            if not is_dir:
                if size_bytes_raw == 0:
                    size_readable = "0 B"
                else:
                    size_name = ("B", "KB", "MB", "GB", "TB")
                    i = 0
                    temp_size = float(size_bytes_raw)
                    while temp_size >= 1024 and i < len(size_name)-1 :
                        temp_size /= 1024.0
                        i += 1
                    size_readable = f"{temp_size:.2f} {size_name[i]}"

            mtime_timestamp = os.path.getmtime(item_path)
            last_modified = datetime.fromtimestamp(mtime_timestamp).strftime('%Y-%m-%d %H:%M:%S')

            items_details.append({
                'name': item_name,
                'path': item_path,
                'is_dir': is_dir,
                'size_bytes_raw': size_bytes_raw, # Pour un tri potentiel
                'size_readable': size_readable,
                'last_modified': last_modified
            })
        except Exception as e:
            logger.error(f"Erreur lors du traitement de {item_path}: {e}")
            items_details.append({
                'name': item_name + " (Erreur de lecture)",
                'path': item_path,
                'is_dir': False,
                'size_readable': "N/A",
                'last_modified': "N/A"
            })

    items_details.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))

    sonarr_configured = bool(current_app.config.get('SONARR_URL') and current_app.config.get('SONARR_API_KEY'))
    radarr_configured = bool(current_app.config.get('RADARR_URL') and current_app.config.get('RADARR_API_KEY'))

    return render_template('seedbox_ui/index.html',
                           items_details=items_details,
                           can_scan_sonarr=sonarr_configured,
                           can_scan_radarr=radarr_configured)

@seedbox_ui_bp.route('/delete/<path:item_name>', methods=['POST'])
def delete_item(item_name):
    staging_dir = current_app.config.get('STAGING_DIR')
    item_path = os.path.join(staging_dir, item_name) # item_name peut contenir des sous-dossiers, d'où <path:>

    # Sécurité : Vérifier que item_path est bien dans staging_dir
    if not os.path.abspath(item_path).startswith(os.path.abspath(staging_dir)):
        flash("Tentative de suppression d'un chemin invalide.", 'danger')
        logger.warning(f"Tentative de suppression de chemin invalide : {item_path}")
        return redirect(url_for('seedbox_ui.index'))

    if not os.path.exists(item_path):
        flash(f"L'item '{item_name}' n'existe plus.", 'warning')
        return redirect(url_for('seedbox_ui.index'))

    try:
        if os.path.isfile(item_path):
            os.remove(item_path)
            msg = f"Fichier '{item_name}' supprimé."
        elif os.path.isdir(item_path):
            shutil.rmtree(item_path)
            msg = f"Dossier '{item_name}' supprimé."
        else:
            msg = f"Impossible de déterminer le type de '{item_name}' pour le supprimer."
            flash(msg, 'danger')
            return redirect(url_for('seedbox_ui.index'))

        flash(msg, 'success')
        logger.info(msg + f" (Chemin: {item_path})")
    except OSError as e:
        flash(f"Erreur lors de la suppression de '{item_name}': {e}", 'danger')
        logger.error(f"Erreur suppression {item_path}: {e}")

    return redirect(url_for('seedbox_ui.index'))

@seedbox_ui_bp.route('/scan-sonarr/<path:item_name>', methods=['POST'])
def scan_sonarr(item_name):
    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not sonarr_url or not sonarr_api_key:
        flash("Sonarr n'est pas configuré.", 'danger')
        return redirect(url_for('seedbox_ui.index'))

    item_path = os.path.join(staging_dir, item_name)
    if not os.path.exists(item_path): # Vérifier si l'item existe toujours
        flash(f"L'item '{item_name}' n'existe pas dans le staging.", 'warning')
        return redirect(url_for('seedbox_ui.index'))

    success, message = send_arr_command(sonarr_url, sonarr_api_key, "DownloadedEpisodesScan", item_path)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('seedbox_ui.index'))

@seedbox_ui_bp.route('/scan-radarr/<path:item_name>', methods=['POST'])
def scan_radarr(item_name):
    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not radarr_url or not radarr_api_key:
        flash("Radarr n'est pas configuré.", 'danger')
        return redirect(url_for('seedbox_ui.index'))

    item_path = os.path.join(staging_dir, item_name)
    if not os.path.exists(item_path):
        flash(f"L'item '{item_name}' n'existe pas dans le staging.", 'warning')
        return redirect(url_for('seedbox_ui.index'))

    success, message = send_arr_command(radarr_url, radarr_api_key, "DownloadedMoviesScan", item_path)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('seedbox_ui.index'))


# --- Routes pour la recherche et le mapping (Priorité 1) ---

@seedbox_ui_bp.route('/search-sonarr-api') # GET request
def search_sonarr_api():
    query = request.args.get('query')
    # original_item_name = request.args.get('original_item_name') # Peut être utile pour le contexte

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')

    if not sonarr_url or not sonarr_api_key:
        return jsonify({"error": "Sonarr non configuré"}), 500
    if not query:
        return jsonify({"error": "Terme de recherche manquant"}), 400

    # API Sonarr pour rechercher des séries: /api/v3/series/lookup?term={query} ou /api/v3/series?term={query}
    # series/lookup est généralement pour rechercher sur TheTVDB par nom/ID.
    # series?term= recherche dans les séries déjà ajoutées à Sonarr.
    # Pour une nouvelle association, 'lookup' est plus pertinent.
    search_api_url = f"{sonarr_url.rstrip('/')}/api/v3/series/lookup"
    params = {'term': query}

    results, error_msg = _make_arr_request('GET', search_api_url, sonarr_api_key, params=params)

    if error_msg:
        return jsonify({"error": error_msg}), 500

    # results est une liste de séries trouvées. On peut les filtrer ou les formater si besoin.
    # Exemple: logger.info(f"Résultats recherche Sonarr pour '{query}': {results}")
    return jsonify(results if results else [])


@seedbox_ui_bp.route('/search-radarr-api') # GET request
def search_radarr_api():
    query = request.args.get('query')
    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')

    if not radarr_url or not radarr_api_key:
        return jsonify({"error": "Radarr non configuré"}), 500
    if not query:
        return jsonify({"error": "Terme de recherche manquant"}), 400

    # API Radarr pour rechercher des films: /api/v3/movie/lookup?term={query}
    search_api_url = f"{radarr_url.rstrip('/')}/api/v3/movie/lookup"
    params = {'term': query}

    results, error_msg = _make_arr_request('GET', search_api_url, radarr_api_key, params=params)

    if error_msg:
        return jsonify({"error": error_msg}), 500

    return jsonify(results if results else [])


@seedbox_ui_bp.route('/trigger-sonarr-import', methods=['POST'])
def trigger_sonarr_import():
    data = request.get_json()
    item_name = data.get('item_name')
    series_id = data.get('series_id') # ID Sonarr de la série (pas TVDB ID directement ici)

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not all([item_name, series_id, sonarr_url, sonarr_api_key, staging_dir]):
        return jsonify({"success": False, "error": "Données manquantes ou Sonarr non configuré."}), 400

    item_path = os.path.join(staging_dir, item_name)
    if not os.path.exists(item_path):
         return jsonify({"success": False, "error": f"L'item '{item_name}' n'existe pas."}), 404

    # TODO: Implémentation de l'import manuel vers une série spécifique.
    # Approche 1 (simple mais moins ciblée) : Déclencher un scan sur le path.
    # Sonarr doit être assez intelligent pour l'associer si la série `series_id` est monitorée.
    # Cette approche ne garantit pas l'association à `series_id` si d'autres séries matchent.
    # success, message = send_arr_command(sonarr_url, sonarr_api_key, "DownloadedEpisodesScan", item_path)
    # if success:
    #    return jsonify({"success": True, "message": f"Scan Sonarr initié pour {item_name}. Message: {message}"})
    # else:
    #    return jsonify({"success": False, "error": f"Erreur scan Sonarr: {message}"}), 500

    # Approche 2 (plus complexe, workflow ManualImport API):
    # 1. GET /api/v3/manualimport?folder={item_path}&seriesId={series_id} (facultatif, mais peut aider à filtrer)
    #    Ceci liste les fichiers importables.
    # 2. L'utilisateur (ou le code) sélectionne les fichiers à importer depuis cette liste.
    # 3. POST /api/v3/command avec name: "ManualImport", et un body contenant les `files` avec `seriesId`, `episodeIds`, etc.

    # Pour l'instant, utilisons la première approche (scan du path), qui est plus simple.
    # L'utilisateur a "mappé" visuellement, maintenant on demande à Sonarr de vérifier ce path.
    logger.info(f"Tentative d'import Sonarr pour l'item '{item_name}' (path: {item_path}) en lien avec la série ID: {series_id} (non utilisé directement par DownloadedEpisodesScan).")

    success, cmd_message = send_arr_command(sonarr_url, sonarr_api_key, "DownloadedEpisodesScan", item_path_to_scan=item_path)

    if success:
        # Il n'y a pas de confirmation directe que l'item a été importé pour CETTE série.
        # Le message est juste que la commande de scan a été acceptée.
        message = f"Scan Sonarr pour '{item_name}' initié. Sonarr va tenter de l'importer. Vérifiez l'activité Sonarr."
        flash(message, 'info') # Ou succès, mais info est plus précis
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "error": cmd_message}), 500


@seedbox_ui_bp.route('/trigger-radarr-import', methods=['POST'])
def trigger_radarr_import():
    data = request.get_json()
    item_name = data.get('item_name')
    movie_id = data.get('movie_id') # ID Radarr du film

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not all([item_name, movie_id, radarr_url, radarr_api_key, staging_dir]):
        return jsonify({"success": False, "error": "Données manquantes ou Radarr non configuré."}), 400

    item_path = os.path.join(staging_dir, item_name)
    if not os.path.exists(item_path):
         return jsonify({"success": False, "error": f"L'item '{item_name}' n'existe pas."}), 404

    # Similaire à Sonarr, pour l'instant, on déclenche un scan du path.
    logger.info(f"Tentative d'import Radarr pour l'item '{item_name}' (path: {item_path}) en lien avec le film ID: {movie_id} (non utilisé directement par DownloadedMoviesScan).")

    success, cmd_message = send_arr_command(radarr_url, radarr_api_key, "DownloadedMoviesScan", item_path_to_scan=item_path)

    if success:
        message = f"Scan Radarr pour '{item_name}' initié. Radarr va tenter de l'importer. Vérifiez l'activité Radarr."
        flash(message, 'info')
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "error": cmd_message}), 500