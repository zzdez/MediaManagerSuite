# app/seedbox_ui/routes.py
import os
import shutil
import logging
import time # Pour le délai
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
    item_name_from_frontend = data.get('item_name') # Nom du fichier/dossier cliqué dans l'UI
    series_id_from_frontend = data.get('series_id') # ID Sonarr de la série cible choisie par l'utilisateur

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    # Vérifications initiales
    if not all([item_name_from_frontend, series_id_from_frontend, sonarr_url, sonarr_api_key, staging_dir]):
        logger.error("trigger_sonarr_import: Données manquantes ou Sonarr non configuré.")
        return jsonify({"success": False, "error": "Données manquantes ou Sonarr non configuré."}), 400

    path_of_item_clicked_in_ui = os.path.join(staging_dir, item_name_from_frontend)
    if not os.path.exists(path_of_item_clicked_in_ui):
        logger.error(f"trigger_sonarr_import: L'item '{item_name_from_frontend}' (chemin: {path_of_item_clicked_in_ui}) n'existe pas.")
        return jsonify({"success": False, "error": f"L'item '{item_name_from_frontend}' n'existe pas."}), 404

    # Déterminer le chemin à passer à Sonarr pour le paramètre 'folder' de manualimport (GET)
    # D'après nos tests Insomnia, passer le dossier parent du fichier .mkv a fonctionné.
    path_to_scan_for_sonarr_get_step = ""
    if os.path.isfile(path_of_item_clicked_in_ui):
        # Si l'utilisateur a cliqué sur un fichier, on utilise son dossier parent pour le scan
        path_to_scan_for_sonarr_get_step = os.path.dirname(path_of_item_clicked_in_ui)
        logger.info(f"Item cliqué est un fichier. Sonarr (GET manualimport) scannera son dossier parent: {path_to_scan_for_sonarr_get_step}")
    elif os.path.isdir(path_of_item_clicked_in_ui):
        # Si l'utilisateur a cliqué sur un dossier, on utilise ce dossier pour le scan
        path_to_scan_for_sonarr_get_step = path_of_item_clicked_in_ui
        logger.info(f"Item cliqué est un dossier. Sonarr (GET manualimport) scannera ce dossier: {path_to_scan_for_sonarr_get_step}")
    else:
        logger.error(f"L'item '{path_of_item_clicked_in_ui}' n'est ni un fichier ni un dossier valide.")
        return jsonify({"success": False, "error": "L'item sélectionné n'est pas valide."}), 400

    # Convertir en chemin Windows avec backslashes pour Sonarr
    path_for_sonarr_api = path_to_scan_for_sonarr_get_step.replace('/', '\\')
    logger.info(f"Chemin pour API Sonarr (GET manualimport folder): {path_for_sonarr_api}")

    # --- Étape 1: GET /api/v3/manualimport (sans seriesId) ---
    manual_import_get_url = f"{sonarr_url.rstrip('/')}/api/v3/manualimport"
    get_params = {
        'folder': path_for_sonarr_api,
        'filterExistingFiles': 'false'
        # Note: seriesId n'est PAS inclus ici pour le GET
    }

    logger.debug(f"Appel GET à Sonarr ManualImport: URL={manual_import_get_url}, Params={get_params}")
    manual_import_candidates, error_msg_get = _make_arr_request('GET', manual_import_get_url, sonarr_api_key, params=get_params)

    if error_msg_get:
        logger.error(f"Erreur lors de l'appel GET à manualimport (Sonarr): {error_msg_get}")
        return jsonify({"success": False, "error": f"Sonarr (manualimport GET): {error_msg_get}"}), 500

    if not manual_import_candidates or not isinstance(manual_import_candidates, list):
        logger.warning(f"Aucun candidat à l'import trouvé par Sonarr pour le scan du dossier '{path_for_sonarr_api}'. Réponse: {manual_import_candidates}")
        return jsonify({"success": False, "error": "Aucun fichier importable trouvé par Sonarr dans le dossier spécifié."}), 404

    # --- Filtrage des candidats et préparation du payload pour le POST ---
    files_to_submit_for_post = []
    for candidate in manual_import_candidates:
        candidate_file_path = candidate.get('path') # Chemin du fichier .mkv DANS LE STAGING
        candidate_series_info = candidate.get('series')
        candidate_episodes_info = candidate.get('episodes')

        if not candidate_file_path:
            logger.warning(f"Candidat sans 'path' ignoré: {candidate}")
            continue

        # Validation 1: Le fichier candidat doit être DANS le dossier de staging qu'on a scanné
        # (pour éviter d'importer des fichiers de F:\Series\... que Sonarr pourrait lister par erreur)
        # os.path.normcase pour comparaison insensible à la casse
        normalized_scan_path = os.path.normcase(os.path.abspath(path_to_scan_for_sonarr_get_step))
        normalized_candidate_path = os.path.normcase(os.path.abspath(os.path.dirname(candidate_file_path)))

        if normalized_candidate_path != normalized_scan_path:
             # Si le dossier parent du candidat n'est pas celui qu'on a demandé de scanner, on l'ignore.
             # Ceci est une sécurité supplémentaire si Sonarr retourne des fichiers hors du 'folder' demandé.
             # D'après les tests Insomnia, cela ne devrait pas arriver si on ne passe pas seriesId.
            logger.warning(f"Candidat ignoré '{candidate_file_path}' car il n'est pas dans le dossier de scan attendu '{normalized_scan_path}'. Son dossier parent est '{normalized_candidate_path}'.")
            continue

        # Validation 2: La série détectée par Sonarr pour ce candidat correspond-elle à celle choisie par l'utilisateur ?
        if not candidate_series_info or candidate_series_info.get('id') != series_id_from_frontend:
            logger.warning(f"Candidat '{candidate_file_path}' ignoré: Série détectée ID "
                           f"{candidate_series_info.get('id') if candidate_series_info else 'N/A'} "
                           f"ne correspond pas à la série cible ID {series_id_from_frontend}.")
            continue

        # Validation 3: Y a-t-il des IDs d'épisodes valides ?
        if not candidate_episodes_info or not all(isinstance(ep, dict) and ep.get('id') for ep in candidate_episodes_info):
            logger.warning(f"Candidat '{candidate_file_path}' ignoré: Aucun episodeId valide trouvé. Episodes: {candidate_episodes_info}")
            continue
        episode_ids_for_post = [ep.get('id') for ep in candidate_episodes_info if ep.get('id')]
        if not episode_ids_for_post: # Double vérification
            logger.warning(f"Candidat '{candidate_file_path}' ignoré: Aucun episodeId après filtrage.")
            continue

        # Validation 4: Infos de qualité présentes ?
        quality_info_for_post = candidate.get('quality')
        if not quality_info_for_post or not quality_info_for_post.get('quality') or \
           not isinstance(quality_info_for_post.get('quality'), dict) or quality_info_for_post['quality'].get('id') is None:
            logger.warning(f"Candidat '{candidate_file_path}' ignoré: Information de qualité manquante ou invalide. Qualité: {quality_info_for_post}")
            continue

        # Gestion de la langue
        detected_languages_list = candidate.get('languages') # C'est une LISTE d'objets langue
        language_obj_for_post = None
        if detected_languages_list and isinstance(detected_languages_list, list) and len(detected_languages_list) > 0:
            # On prend la première langue détectée par Sonarr pour ce fichier
            if detected_languages_list[0].get('id') is not None and detected_languages_list[0].get('name'):
                language_obj_for_post = detected_languages_list[0]
            else:
                logger.warning(f"Candidat '{candidate_file_path}': Premier objet langue invalide dans la liste: {detected_languages_list[0]}")

        if not language_obj_for_post:
             logger.warning(f"Candidat '{candidate_file_path}': Aucune langue valide détectée ({detected_languages_list}). L'import se fera sans spécifier la langue (Sonarr utilisera le profil de la série).")

        # Construction du payload pour CE fichier
        single_file_payload = {
            "path": candidate_file_path,       # Chemin complet du fichier source .mkv dans le staging
            "seriesId": series_id_from_frontend, # ID de la série cible
            "episodeIds": episode_ids_for_post,  # Liste des IDs d'épisodes Sonarr
            "quality": quality_info_for_post,    # Objet qualité complet
            "releaseGroup": candidate.get('releaseGroup') # Peut être None
        }
        if language_obj_for_post:
            single_file_payload["language"] = language_obj_for_post # Objet langue {id, name}

        files_to_submit_for_post.append(single_file_payload)
        logger.info(f"Fichier '{candidate_file_path}' préparé pour POST ManualImport vers série ID {series_id_from_frontend}, épisode(s) ID(s) {episode_ids_for_post}.")

    if not files_to_submit_for_post:
        logger.warning(f"Aucun fichier du staging n'a pu être préparé pour l'import après filtrage des candidats. Scan de '{path_for_sonarr_api}', série cible ID {series_id_from_frontend}.")
        return jsonify({"success": False, "error": "Sonarr n'a pas trouvé de fichier correspondant à vos critères dans le dossier de staging, ou n'a pas pu l'associer à la série/épisodes cibles."}), 400

    # --- Étape 2: POST /api/v3/command avec name: "ManualImport" ---
    post_command_payload = {
        "name": "ManualImport",
        "files": files_to_submit_for_post, # 'files' est une liste d'objets
        "importMode": "Move"               # Déplace le fichier du staging si import réussi
    }

    command_post_url = f"{sonarr_url.rstrip('/')}/api/v3/command"
    logger.debug(f"Appel POST à Sonarr Command (ManualImport): URL={command_post_url}, Payload={post_command_payload}")

    response_data_post, error_msg_post = _make_arr_request('POST', command_post_url, sonarr_api_key, json_data=post_command_payload)

    if error_msg_post:
        logger.error(f"Erreur lors de l'envoi de la commande ManualImport (Sonarr POST): {error_msg_post}. Payload: {post_command_payload}")
        return jsonify({"success": False, "error": f"Sonarr (ManualImport POST): {error_msg_post}"}), 500

    if response_data_post and isinstance(response_data_post, dict) and response_data_post.get('name') == "ManualImport":
        sonarr_message = response_data_post.get('message', "Commande d'import manuel acceptée par Sonarr.")
        logger.info(f"Commande ManualImport acceptée par Sonarr pour {len(files_to_submit_for_post)} fichier(s). Message Sonarr: {sonarr_message}. Réponse complète: {response_data_post}")
        return jsonify({
            "success": True,
            "message": f"{len(files_to_submit_for_post)} fichier(s) soumis pour import manuel. {sonarr_message}. Vérifiez l'activité Sonarr."
        })
    else:
        logger.warning(f"Réponse inattendue après la commande ManualImport à Sonarr: {response_data_post}. Payload envoyé: {post_command_payload}")
        return jsonify({"success": False, "error": "Réponse inattendue de Sonarr après la commande d'import manuel."}), 500

@seedbox_ui_bp.route('/trigger-radarr-import', methods=['POST'])
def trigger_radarr_import():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name')
    movie_id_from_frontend = data.get('movie_id') # L'ID Radarr du film cible

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not all([item_name_from_frontend, movie_id_from_frontend, radarr_url, radarr_api_key, staging_dir]):
        logger.error("trigger_radarr_import: Données manquantes ou Radarr non configuré.")
        return jsonify({"success": False, "error": "Données manquantes ou Radarr non configuré."}), 400

    item_full_path = os.path.join(staging_dir, item_name_from_frontend)
    if not os.path.exists(item_full_path):
        logger.error(f"trigger_radarr_import: L'item '{item_name_from_frontend}' (chemin: {item_full_path}) n'existe pas.")
        return jsonify({"success": False, "error": f"L'item '{item_name_from_frontend}' n'existe pas."}), 404

    logger.info(f"Début de l'import manuel Radarr pour '{item_name_from_frontend}' vers le film ID {movie_id_from_frontend}.")

    # --- Étape 1: GET /api/v3/manualimport (Radarr) ---
    manual_import_url = f"{radarr_url.rstrip('/')}/api/v3/manualimport"
    params = {
        'folder': item_full_path,
        'movieId': movie_id_from_frontend, # Pour aider Radarr à identifier le film
        'filterExistingFiles': 'false'
    }

    logger.debug(f"Appel GET à Radarr ManualImport: URL={manual_import_url}, Params={params}")
    manual_import_candidates, error_msg = _make_arr_request('GET', manual_import_url, radarr_api_key, params=params)

    if error_msg:
        logger.error(f"Erreur lors de l'appel GET à manualimport (Radarr): {error_msg}")
        return jsonify({"success": False, "error": f"Radarr (manualimport GET): {error_msg}"}), 500

    if not manual_import_candidates or not isinstance(manual_import_candidates, list):
        logger.warning(f"Aucun candidat à l'import trouvé par Radarr pour le chemin '{item_full_path}' et le film ID {movie_id_from_frontend}. Réponse: {manual_import_candidates}")
        return jsonify({"success": False, "error": "Aucun fichier importable trouvé par Radarr pour ce film et ce chemin."}), 404

    # Pour Radarr, chaque candidat est un film potentiel.
    # On s'attend à ce qu'il y ait typiquement UN candidat si item_full_path est un seul fichier film.
    # Si item_full_path est un dossier avec plusieurs films, il pourrait y en avoir plusieurs.
    # On va essayer d'importer le premier candidat qui correspond au movieId.

    file_to_import_payload = None

    for candidate in manual_import_candidates:
        candidate_path = candidate.get('path')
        candidate_movie = candidate.get('movie') # Objet Movie de Radarr

        if not candidate_path:
            logger.warning(f"Candidat Radarr sans chemin ignoré: {candidate}")
            continue

        if not candidate_movie or candidate_movie.get('id') != movie_id_from_frontend:
            logger.warning(f"Candidat Radarr ignoré: le movie ID {candidate_movie.get('id') if candidate_movie else 'N/A'} ne correspond pas à {movie_id_from_frontend}. Fichier: {candidate_path}")
            continue

        quality_info = candidate.get('quality')
        if not quality_info or not quality_info.get('quality') or not isinstance(quality_info.get('quality'), dict) or quality_info['quality'].get('id') is None:
            logger.warning(f"Candidat Radarr ignoré: information de qualité manquante pour {candidate_path}. Qualité: {quality_info}")
            continue

        # Radarr `manualimport` ne retourne pas directement la langue dans l'objet principal du candidat
        # mais dans `candidate.movie.originalLanguage`. On peut la réutiliser.
        # Pour la commande `ManualImport`, Radarr s'attend à un objet langue.
        # Si nous n'avons pas d'objet langue, nous pourrions avoir besoin de le récupérer ou de le construire.
        # Pour l'instant, on essaie sans spécifier la langue explicitement dans le payload de la commande,
        # Radarr devrait pouvoir s'en sortir ou utiliser des défauts.
        # Alternativement, si `candidate.movie.originalLanguage` est disponible:
        # language_obj_for_payload = candidate.movie.originalLanguage # Si c'est déjà le bon format {id, name}
        # Ou, si on doit le chercher: GET /language, trouver l'ID pour la langue de `candidate.movie.originalLanguage.name`

        # Si le `candidate` a un `id` (différent du `movieId`), c'est un "release id" pour l'import.
        # Le payload de la commande ManualImport pour Radarr est un peu différent:
        # Il prend un `movieId`, `path`, `quality`, et optionnellement `downloadId`.

        file_to_import_payload = { # Radarr ManualImport prend UN seul fichier à la fois dans sa commande POST (contrairement à Sonarr qui prend une liste `files`)
            "path": candidate_path,
            "movieId": movie_id_from_frontend,
            "quality": quality_info, # Objet qualité complet
            # "language": language_obj_for_payload, # Optionnel, si on l'a
            "releaseGroup": candidate.get('releaseGroup'),
            # "downloadId": "MANUAL_RADARR_IMPORT_XYZ" # Optionnel
        }
        logger.info(f"Fichier '{candidate_path}' préparé pour l'import manuel Radarr vers film ID {movie_id_from_frontend}.")
        break # On prend le premier candidat correspondant pour un film

    if not file_to_import_payload:
        logger.warning(f"Aucun fichier n'a pu être préparé pour l'import Radarr après filtrage pour '{item_name_from_frontend}'.")
        return jsonify({"success": False, "error": "Radarr n'a pas pu associer le fichier au film sélectionné ou les informations de qualité sont manquantes."}), 400

    # --- Étape 2: POST /api/v3/command avec name: "ManualImport" (Radarr) ---
    # Radarr s'attend à ce que le payload de la commande ManualImport soit directement l'objet file, pas une liste.
    # Le name de la commande reste "ManualImport".
    # { "name": "ManualImport", "movieId": ..., "path": ..., ... }
    manual_import_command_payload = {
        "name": "ManualImport",
        **file_to_import_payload, # Fusionne les clés de file_to_import_payload ici
        "importMode": "Move"
    }

    command_url = f"{radarr_url.rstrip('/')}/api/v3/command"
    logger.debug(f"Appel POST à Radarr Command (ManualImport): URL={command_url}, Payload={manual_import_command_payload}")

    response_data, error_msg = _make_arr_request('POST', command_url, radarr_api_key, json_data=manual_import_command_payload)

    if error_msg:
        logger.error(f"Erreur lors de l'envoi de la commande ManualImport (Radarr): {error_msg}. Payload: {manual_import_command_payload}")
        return jsonify({"success": False, "error": f"Radarr (ManualImport POST): {error_msg}"}), 500

    if response_data and isinstance(response_data, dict) and response_data.get('name') == "ManualImport":
        status_message = response_data.get('message', "Commande d'import manuel acceptée par Radarr.")
        logger.info(f"Commande ManualImport acceptée par Radarr pour '{file_to_import_payload['path']}'. Message Radarr: {status_message}. Réponse complète: {response_data}")
        return jsonify({
            "success": True,
            "message": f"Fichier '{os.path.basename(file_to_import_payload['path'])}' soumis pour import manuel. {status_message}. Vérifiez l'activité Radarr."
        })
    else:
        logger.warning(f"Réponse inattendue après la commande ManualImport à Radarr: {response_data}. Payload envoyé: {manual_import_command_payload}")
        return jsonify({"success": False, "error": "Réponse inattendue de Radarr après la commande d'import manuel."}), 500