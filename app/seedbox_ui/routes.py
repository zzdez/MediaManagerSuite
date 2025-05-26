# app/seedbox_ui/routes.py
import os
import shutil
import logging
import time # Pour le délai
import re
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

# ------------------------------------------------------------------------------
# --- Fonctions Utilitaires pour les API Sonarr/Radarr ---
# ------------------------------------------------------------------------------
def _make_arr_request(method, url, api_key, params=None, json_data=None, timeout=30):
    """Fonction helper pour faire des requêtes génériques aux API *Arr."""
    headers = {
        'X-Api-Key': api_key,
        'Content-Type': 'application/json'
    }
    try:
        if method.upper() == 'POST' and json_data:
            import json
            logger.debug(f"RAW JSON PAYLOAD BEING SENT TO {url}:\n{json.dumps(json_data, indent=4)}")

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
# ... (après _make_arr_request) ...

#FONCTION DE NETTOYAGE RÉCURSIVE
def cleanup_staging_subfolder_recursively(folder_path, staging_root_dir, orphan_extensions, is_top_level_call=True):
    """
    Nettoie récursivement un dossier dans le staging.
    Supprime les fichiers orphelins, puis supprime le dossier s'il devient vide.
    Fonctionne de l'intérieur vers l'extérieur pour les sous-dossiers.
    """
    logger.info(f"Nettoyage récursif demandé pour: {folder_path}")

    norm_folder_path = os.path.normpath(os.path.abspath(folder_path))
    norm_staging_root = os.path.normpath(os.path.abspath(staging_root_dir))

    if not norm_folder_path.startswith(norm_staging_root):
        logger.error(f"Nettoyage récursif annulé: {folder_path} est en dehors de {staging_root_dir}.")
        return False

    # Empêcher la suppression de la racine du staging, sauf si c'est l'appel initial ET qu'elle est vide/orpheline
    if norm_folder_path == norm_staging_root and not is_top_level_call:
        logger.debug(f"Nettoyage récursif: atteint la racine du staging {norm_staging_root} lors d'un appel récursif, arrêt.")
        return False

    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        logger.debug(f"Nettoyage récursif: {folder_path} n'existe pas ou n'est pas un dossier.")
        return True

    # Traiter d'abord les sous-dossiers
    # Lister les items avant de potentiellement les modifier pour éviter les problèmes d'itération
    items_in_folder = os.listdir(folder_path)
    for item_name in items_in_folder:
        item_path = os.path.join(folder_path, item_name)
        if os.path.isdir(item_path):
            cleanup_staging_subfolder_recursively(item_path, staging_root_dir, orphan_extensions, is_top_level_call=False)

    # Vérifier à nouveau si le dossier existe (il a pu être supprimé par un appel récursif si un sous-dossier était le seul contenu)
    if not os.path.exists(folder_path):
        logger.info(f"Dossier {folder_path} a été supprimé par un appel récursif (probablement devenu vide).")
        return True

    # Maintenant, vérifier le contenu du dossier actuel
    # Supprimer les fichiers orphelins
    remaining_items_after_orphan_removal = []
    items_in_folder_after_recursion = os.listdir(folder_path) # Relire le contenu

    for item_name in items_in_folder_after_recursion:
        item_path = os.path.join(folder_path, item_name)
        if os.path.isfile(item_path):
            _, ext = os.path.splitext(item_name)
            if ext.lower() in orphan_extensions:
                try:
                    logger.info(f"Suppression du fichier orphelin: {item_path}")
                    os.remove(item_path)
                except Exception as e:
                    logger.error(f"Impossible de supprimer le fichier orphelin {item_path}: {e}")
                    remaining_items_after_orphan_removal.append(item_name) # Le considérer comme restant
            else:
                remaining_items_after_orphan_removal.append(item_name) # Fichier non-orphelin
        elif os.path.isdir(item_path):
             remaining_items_after_orphan_removal.append(item_name) # Sous-dossier restant

    # Le dossier peut-il être supprimé ? (Seulement s'il est vide maintenant)
    if not remaining_items_after_orphan_removal:
        # Garde-fou final: ne pas supprimer le dossier racine du staging s'il a été passé comme folder_path initial
        if norm_folder_path == norm_staging_root and not is_top_level_call:
             logger.warning(f"Nettoyage final annulé pour {folder_path}: tentative de suppression récursive de la racine du staging.")
             return False # Sécurité

        try:
            logger.info(f"Suppression du dossier (devenu vide après nettoyage des orphelins/sous-dossiers): {folder_path}")
            os.rmdir(folder_path)
            logger.info(f"Dossier {folder_path} supprimé avec succès.")
            return True
        except OSError as e:
            logger.error(f"Erreur lors de la suppression du dossier {folder_path} avec os.rmdir (est-il vraiment vide?): {e}. Contenu: {os.listdir(folder_path) if os.path.exists(folder_path) else 'N/A'}")
            return False
    else:
        logger.info(f"Le dossier {folder_path} n'est pas vide après le nettoyage des orphelins/sous-dossiers. Items restants: {remaining_items_after_orphan_removal}. Pas de suppression du dossier.")
        return False
# FIN DE LA NOUVELLE FONCTION cleanup_staging_subfolder_recursively

# ------------------------------------------------------------------------------
# FONCTION DE NETTOYAGE DU STAGING
# ------------------------------------------------------------------------------
def cleanup_staging_subfolder(folder_path_in_staging, staging_root_dir, orphan_extensions):
    """
    Nettoie un sous-dossier spécifique dans le répertoire de staging.
    Le supprime s'il est vide ou ne contient que des fichiers orphelins.
    """
    logger.info(f"Tentative de nettoyage du dossier de staging: {folder_path_in_staging}")

    # Garde-fou : ne pas supprimer le dossier racine du staging lui-même
    norm_folder_path = os.path.normpath(os.path.abspath(folder_path_in_staging))
    norm_staging_root = os.path.normpath(os.path.abspath(staging_root_dir))

    if norm_folder_path == norm_staging_root:
        logger.warning(f"Nettoyage annulé : tentative de suppression du dossier racine du staging ({folder_path_in_staging}).")
        return False

    if not os.path.exists(folder_path_in_staging):
        logger.info(f"Dossier {folder_path_in_staging} n'existe déjà plus. Pas de nettoyage nécessaire.")
        return True

    if not os.path.isdir(folder_path_in_staging):
        logger.warning(f"Chemin {folder_path_in_staging} n'est pas un dossier. Nettoyage annulé.")
        return False

    all_files_are_orphans = True
    has_any_files = False
    has_subfolders = False # Pour vérifier s'il y a des sous-dossiers non vides

    for item_name in os.listdir(folder_path_in_staging):
        item_path = os.path.join(folder_path_in_staging, item_name)
        if os.path.isfile(item_path):
            has_any_files = True
            _, ext = os.path.splitext(item_name)
            if ext.lower() not in orphan_extensions:
                all_files_are_orphans = False
                logger.info(f"Nettoyage de {folder_path_in_staging} annulé: contient un fichier non-orphelin: {item_name}")
                break
        elif os.path.isdir(item_path):
            # Si on trouve un sous-dossier, on ne supprime pas le dossier parent pour l'instant
            # (on pourrait rendre cela récursif, mais pour le staging c'est peut-être trop)
            has_subfolders = True
            all_files_are_orphans = False # Considérez un sous-dossier comme non orphelin pour cette logique simple
            logger.info(f"Nettoyage de {folder_path_in_staging} annulé: contient un sous-dossier: {item_name}")
            break

    if not has_any_files and not has_subfolders: # Le dossier est complètement vide
        logger.info(f"Le dossier {folder_path_in_staging} est vide.")
        # all_files_are_orphans reste True par défaut si pas de fichiers ou sous-dossiers

    if all_files_are_orphans and not has_subfolders: # On supprime seulement si vide ou seulement orphelins, et pas de sous-dossiers
        try:
            logger.info(f"Suppression du dossier de staging (vide ou seulement orphelins): {folder_path_in_staging}")
            shutil.rmtree(folder_path_in_staging)
            logger.info(f"Dossier {folder_path_in_staging} supprimé avec succès.")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du dossier {folder_path_in_staging}: {e}")
            return False
    elif has_subfolders:
        logger.info(f"Nettoyage de {folder_path_in_staging} non effectué car il contient des sous-dossiers.")
    elif not all_files_are_orphans:
         logger.info(f"Nettoyage de {folder_path_in_staging} non effectué car il contient des fichiers non-orphelins.")

    return False
# ------------------------------------------------------------------------------
# FIN DE LA FONCTION DE NETTOYAGE
# ------------------------------------------------------------------------------

# NOUVELLE FONCTION HELPER POUR CONSTRUIRE L'ARBORESCENCE
def build_file_tree(directory_path, staging_root_for_relative_path):
    """
    Construit récursivement une structure arborescente pour un dossier donné.
    Chaque nœud contient : name, type ('file' ou 'directory'), path_id (chemin relatif encodé ou simple),
                          size_readable, last_modified, et 'children' pour les dossiers.
    """
    tree = []
    try:
        for item_name in sorted(os.listdir(directory_path), key=lambda x: (not os.path.isdir(os.path.join(directory_path, x)), x.lower())):
            item_path = os.path.join(directory_path, item_name)
            # path_id est le chemin relatif au staging_root_for_relative_path, utilisé pour les actions
            # Cela évite de passer des chemins absolus au frontend pour les actions
            # On le garde simple pour l'instant : juste item_name si c'est un item de premier niveau,
            # ou un chemin relatif plus complet si on veut gérer des actions sur des sous-niveaux.
            # Pour les actions actuelles (Mapper, Supprimer, Nettoyer dossier) qui opèrent sur
            # les items de premier niveau du staging, item_name est suffisant.
            # Si on voulait des actions sur des sous-fichiers/sous-dossiers, il faudrait un path_id plus complet.

            # Pour le path_id qui sera passé à url_for, il faut le chemin relatif au STAGING_DIR
            # pour que nos routes <path:item_name> fonctionnent.
            # Example: si staging_root_for_relative_path = X:\staging et item_path = X:\staging\DossierA\fichier.txt
            # alors relative_item_path = DossierA\fichier.txt
            relative_item_path = os.path.relpath(item_path, staging_root_for_relative_path)
            # Remplacer les backslashes par des slashes pour la cohérence dans les URLs (Flask s'en accommode)
            path_id_for_url = relative_item_path.replace('\\', '/')


            node = {
                'name': item_name,
                'path_for_actions': path_id_for_url, # Chemin relatif pour les url_for
                'is_dir': os.path.isdir(item_path)
            }
            try:
                stat_info = os.stat(item_path)
                node['size_bytes_raw'] = stat_info.st_size
                node['last_modified_timestamp'] = stat_info.st_mtime
                node['last_modified'] = datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

                if node['is_dir']:
                    node['size_readable'] = "N/A (dossier)" # Ou calculer la taille récursivement si souhaité (peut être lent)
                    node['children'] = build_file_tree(item_path, staging_root_for_relative_path) # Appel récursif
                else:
                    if stat_info.st_size == 0:
                        node['size_readable'] = "0 B"
                    else:
                        size_name = ("B", "KB", "MB", "GB", "TB")
                        i = 0
                        temp_size = float(stat_info.st_size)
                        while temp_size >= 1024 and i < len(size_name) - 1:
                            temp_size /= 1024.0
                            i += 1
                        node['size_readable'] = f"{temp_size:.2f} {size_name[i]}"
            except Exception as e_stat:
                logger.error(f"Erreur stat pour {item_path}: {e_stat}")
                node['size_readable'] = "Erreur"
                node['last_modified'] = "Erreur"
                if node['is_dir']: node['children'] = [] # S'assurer que children existe

            tree.append(node)
    except OSError as e:
        logger.error(f"Erreur lors de la lecture du dossier {directory_path} pour l'arbre: {e}")
    return tree
# FIN DE LA FONCTION HELPER build_file_tree

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
    if not staging_dir or not os.path.isdir(staging_dir): # Vérifier isdir aussi
        flash(f"Le dossier de staging '{staging_dir}' n'est pas configuré ou n'existe pas/n'est pas un dossier.", 'danger')
        return render_template('seedbox_ui/index.html', items_tree=[]) # Passer items_tree au lieu de items_details

    logger.info(f"Construction de l'arborescence pour le dossier de staging: {staging_dir}")
    # La fonction build_file_tree est appelée avec staging_dir comme base pour les chemins relatifs
    items_tree_data = build_file_tree(staging_dir, staging_dir)
    # items_tree_data sera une liste d'objets pour les items à la racine du staging_dir

    sonarr_configured = bool(current_app.config.get('SONARR_URL') and current_app.config.get('SONARR_API_KEY'))
    radarr_configured = bool(current_app.config.get('RADARR_URL') and current_app.config.get('RADARR_API_KEY'))

    return render_template('seedbox_ui/index.html',
                           items_tree=items_tree_data, # Nouvelle variable pour le template
                           can_scan_sonarr=sonarr_configured,
                           can_scan_radarr=radarr_configured,
                           staging_dir_display=staging_dir) # Pour afficher le chemin du staging si besoin

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


# ------------------------------------------------------------------------------
# FONCTION trigger_sonarr_import
# ------------------------------------------------------------------------------

@seedbox_ui_bp.route('/trigger-sonarr-import', methods=['POST'])
def trigger_sonarr_import():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name')
    series_id_from_frontend = data.get('series_id')

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    if not all([item_name_from_frontend, series_id_from_frontend, sonarr_url, sonarr_api_key, staging_dir]):
        logger.error("trigger_sonarr_import: Données manquantes ou Sonarr non configuré.")
        return jsonify({"success": False, "error": "Données manquantes ou Sonarr non configuré."}), 400

    path_of_item_clicked_in_ui = os.path.join(staging_dir, item_name_from_frontend)
    if not os.path.exists(path_of_item_clicked_in_ui):
        logger.error(f"trigger_sonarr_import: L'item UI '{item_name_from_frontend}' (chemin: {path_of_item_clicked_in_ui}) n'existe pas.")
        return jsonify({"success": False, "error": f"L'item '{item_name_from_frontend}' n'existe pas."}), 404

    path_to_scan_for_sonarr_get_step = ""
    if os.path.isfile(path_of_item_clicked_in_ui):
        path_to_scan_for_sonarr_get_step = os.path.dirname(path_of_item_clicked_in_ui)
    elif os.path.isdir(path_of_item_clicked_in_ui):
        path_to_scan_for_sonarr_get_step = path_of_item_clicked_in_ui
    else:
        logger.error(f"L'item '{path_of_item_clicked_in_ui}' n'est ni un fichier ni un dossier valide pour le scan.")
        return jsonify({"success": False, "error": "L'item sélectionné pour le scan n'est pas valide."}), 400

    path_for_sonarr_api_get = path_to_scan_for_sonarr_get_step.replace('/', '\\')

    manual_import_get_url = f"{sonarr_url.rstrip('/')}/api/v3/manualimport"
    get_params = {'folder': path_for_sonarr_api_get, 'filterExistingFiles': 'false'}
    logger.debug(f"Appel GET à Sonarr ManualImport (pour identification): URL={manual_import_get_url}, Params={get_params}")
    manual_import_candidates, error_msg_get = _make_arr_request('GET', manual_import_get_url, sonarr_api_key, params=get_params)

    if error_msg_get or not manual_import_candidates or not isinstance(manual_import_candidates, list):
        logger.error(f"Erreur ou aucun candidat de Sonarr GET manualimport: {error_msg_get or 'Pas de candidats'}. Dossier scanné: {path_for_sonarr_api_get}")
        # Si aucun candidat, on ne peut pas proposer de résolution de discordance.
        return jsonify({"success": False, "error": f"Sonarr n'a pas pu analyser le contenu du staging: {error_msg_get or 'Aucun candidat trouvé'}."}), 500

    valid_candidates_for_processing = []
    for candidate in manual_import_candidates:
        candidate_file_path_in_staging = candidate.get('path')
        candidate_series_info = candidate.get('series')
        candidate_episodes_info = candidate.get('episodes')

        if not candidate_file_path_in_staging: continue

        norm_staging_dir_abs = os.path.normcase(os.path.abspath(staging_dir))
        norm_candidate_path_abs = os.path.normcase(os.path.abspath(candidate_file_path_in_staging))
        if not norm_candidate_path_abs.startswith(norm_staging_dir_abs):
            logger.warning(f"Candidat Sonarr '{candidate_file_path_in_staging}' ignoré (hors STAGING_DIR).")
            continue

        if not candidate_series_info or candidate_series_info.get('id') != series_id_from_frontend:
            logger.info(f"Candidat Sonarr '{candidate_file_path_in_staging}' ignoré (série ID {candidate_series_info.get('id') if candidate_series_info else 'N/A'} != cible {series_id_from_frontend}).")
            continue

        if not candidate_episodes_info or not isinstance(candidate_episodes_info, list) or not candidate_episodes_info:
            logger.warning(f"Candidat Sonarr '{candidate_file_path_in_staging}' ignoré (pas d'informations d'épisodes).")
            continue

        first_episode_obj_from_sonarr = candidate_episodes_info[0]
        if not first_episode_obj_from_sonarr.get('id') or first_episode_obj_from_sonarr.get('seasonNumber') is None or first_episode_obj_from_sonarr.get('episodeNumber') is None:
            logger.warning(f"Candidat Sonarr '{candidate_file_path_in_staging}' ignoré (infos du premier épisode incomplètes: {first_episode_obj_from_sonarr}).")
            continue

        quality_info = candidate.get('quality')
        if not quality_info or not quality_info.get('quality') or not isinstance(quality_info.get('quality'), dict) or quality_info['quality'].get('id') is None:
            logger.warning(f"Candidat Sonarr '{candidate_file_path_in_staging}' ignoré (Information de qualité manquante ou invalide. Qualité: {quality_info})")
            continue

        valid_candidates_for_processing.append({
            "source_path_in_staging": candidate_file_path_in_staging,
            "sonarr_series_id": candidate_series_info.get('id'),
            "sonarr_episode_list": candidate_episodes_info,
            "sonarr_quality_obj": quality_info,
            "sonarr_language_list": candidate.get('languages', []),
            "original_filename": os.path.basename(candidate_file_path_in_staging)
        })
        logger.info(f"Candidat Sonarr valide ajouté pour traitement: {candidate_file_path_in_staging}")

    if not valid_candidates_for_processing:
        logger.error(f"Aucun fichier vidéo valide trouvé dans '{path_for_sonarr_api_get}' pour la série ID {series_id_from_frontend} après filtrage initial.")
        return jsonify({"success": False, "error": "Aucun fichier vidéo utilisable pour cette série n'a été trouvé dans le dossier de staging."}), 400

    # --- Vérification de discordance S/E ---
    # Pour cette fonctionnalité, on se concentre sur le premier candidat valide trouvé,
    # car l'UI actuelle ne gère qu'un "item de staging" à la fois pour le mapping.
    # Si un dossier de release contient plusieurs fichiers vidéos pour la même série,
    # cette logique de discordance s'appliquera au premier. Les autres seraient importés
    # normalement si le premier passe ou si l'utilisateur choisit une option.
    # Pour simplifier, si le premier candidat a une discordance, on propose de la résoudre pour LUI.

    file_info_to_check = valid_candidates_for_processing[0] # On vérifie le premier candidat pertinent
    original_filename_to_check = file_info_to_check["original_filename"]
    sonarr_episode_obj_to_check = file_info_to_check["sonarr_episode_list"][0]
    sonarr_season_num_to_check = sonarr_episode_obj_to_check.get('seasonNumber')
    sonarr_episode_num_to_check = sonarr_episode_obj_to_check.get('episodeNumber')

    filename_season_num = None
    filename_episode_num = None
    s_e_match = re.search(r'[._\s\[\(-]S(\d{1,3})[E._\s-]?(\d{1,3})', original_filename_to_check, re.IGNORECASE)

    if s_e_match:
        try:
            filename_season_num = int(s_e_match.group(1))
            filename_episode_num = int(s_e_match.group(2))
            logger.info(f"Validation S/E pour '{original_filename_to_check}': Fichier semble S{str(filename_season_num).zfill(2)}E{str(filename_episode_num).zfill(2)}. Sonarr identifie S{sonarr_season_num_to_check}E{sonarr_episode_num_to_check}.")

            # Condition de discordance (on se concentre sur la saison pour l'instant pour la décision de blocage/option)
            if filename_season_num != sonarr_season_num_to_check:
                logger.warning(f"DISCORDANCE DE SAISON DÉTECTÉE pour '{original_filename_to_check}'. Fichier: S{filename_season_num}, Sonarr: S{sonarr_season_num_to_check}.")
                return jsonify({
                    "success": False,
                    "action_required": "resolve_season_episode_mismatch", # Le frontend va gérer ça
                    "message": f"Discordance Saison/Épisode détectée pour '{original_filename_to_check}'.",
                    "details": {
                        "filename_season": filename_season_num,
                        "filename_episode": filename_episode_num,
                        "sonarr_season": sonarr_season_num_to_check,
                        "sonarr_episode": sonarr_episode_num_to_check,
                        "staging_item_name": item_name_from_frontend, # Nom de l'item UI pour le prochain appel
                        "series_id": series_id_from_frontend,
                        # On passe le chemin exact du fichier vidéo du staging, car c'est lui qu'on va déplacer
                        "source_video_file_path_in_staging": file_info_to_check["source_path_in_staging"]
                    }
                }), 200 # 200 OK car le client doit agir
        except ValueError:
            logger.warning(f"Erreur de conversion S/E pour '{original_filename_to_check}'. On se fie à Sonarr.")
            # Pas de discordance signalée si on ne peut pas parser le nom du fichier de manière fiable
    else:
        logger.warning(f"Impossible d'extraire SxxExx de '{original_filename_to_check}' pour validation. On se fie à Sonarr.")
        # Pas de discordance signalée

    # Si on arrive ici, soit il n'y a pas eu de discordance, soit on n'a pas pu valider,
    # donc on procède à l'import normal en se fiant aux infos de Sonarr pour chaque candidat.
    # La logique de déplacement gérée par l'application suit :

    series_details_url = f"{sonarr_url.rstrip('/')}/api/v3/series/{series_id_from_frontend}"
    series_data, error_msg_series_get = _make_arr_request('GET', series_details_url, sonarr_api_key)

    if error_msg_series_get or not series_data or not isinstance(series_data, dict):
        logger.error(f"Impossible de récupérer les détails de la série ID {series_id_from_frontend} de Sonarr: {error_msg_series_get or 'Pas de données'}")
        return jsonify({"success": False, "error": "Impossible de récupérer les détails de la série depuis Sonarr."}), 500

    series_root_folder_path = series_data.get('path')
    if not series_root_folder_path:
        logger.error(f"Chemin racine de la série non dispo pour série ID {series_id_from_frontend}.")
        return jsonify({"success": False, "error": "Chemin racine de la série non trouvé dans Sonarr."}), 500

    series_title_from_sonarr = series_data.get('title', 'Série Inconnue')
    logger.info(f"Chemin racine pour série '{series_title_from_sonarr}': {series_root_folder_path}")

    imported_files_count = 0
    any_error_during_process = False
    original_release_folder_in_staging = path_to_scan_for_sonarr_get_step
    first_processed_staging_filepath = None

    for file_info in valid_candidates_for_processing: # On itère sur tous les candidats valides
        main_video_file_source_path = file_info["source_path_in_staging"]
        # Pour la destination, on utilise les infos de Sonarr pour ce fichier spécifique
        sonarr_episode_obj = file_info["sonarr_episode_list"][0] # On prend le premier épisode pour la saison
        target_season_for_move = sonarr_episode_obj.get('seasonNumber')
        original_filename = file_info["original_filename"]

        if first_processed_staging_filepath is None:
            first_processed_staging_filepath = main_video_file_source_path

        season_folder_name = f"Season {str(target_season_for_move).zfill(2)}"
        destination_season_folder_path = os.path.join(series_root_folder_path, season_folder_name)
        destination_video_file_path = os.path.join(destination_season_folder_path, original_filename)

        logger.info(f"Déplacement pour: {main_video_file_source_path} -> {destination_video_file_path}")
        try:
            if not os.path.exists(destination_season_folder_path):
                os.makedirs(destination_season_folder_path, exist_ok=True)

            if os.path.normcase(os.path.abspath(main_video_file_source_path)) == os.path.normcase(os.path.abspath(destination_video_file_path)):
                logger.warning(f"Source et destination identiques ({main_video_file_source_path}). Pas de déplacement.")
                imported_files_count +=1
            else:
                shutil.move(main_video_file_source_path, destination_video_file_path)
                logger.info(f"Déplacement de '{original_filename}' réussi.")
                imported_files_count +=1
        except Exception as e_move:
            logger.error(f"Erreur shutil.move pour '{original_filename}': {e_move}. Tentative copie/suppr.")
            try:
                shutil.copy2(main_video_file_source_path, destination_video_file_path)
                os.remove(main_video_file_source_path)
                logger.info(f"Copie/suppression de '{original_filename}' réussie.")
                imported_files_count +=1
            except Exception as e_copy:
                logger.error(f"Erreur copie/suppression fallback pour '{original_filename}': {e_copy}")
                any_error_during_process = True

    if imported_files_count == 0:
        # Si any_error_during_process est True, une erreur a déjà été logguée.
        # Si on arrive ici sans erreur mais 0 import, c'est que tous les candidats ont été skippés (par discordance S/E par exemple, mais on aurait dû retourner avant)
        # Ce cas est maintenant moins probable car la discordance retourne plus tôt.
        logger.warning(f"Aucun fichier n'a été effectivement déplacé pour la série {series_id_from_frontend} (après boucle).")
        return jsonify({"success": False, "error": "Aucun fichier n'a été déplacé (vérifiez les logs pour les raisons)."}), 400

    if original_release_folder_in_staging and os.path.exists(original_release_folder_in_staging):
        logger.info(f"Nettoyage du dossier de staging: {original_release_folder_in_staging} après import de {imported_files_count} fichier(s).")
        time.sleep(1) # Réduit car on a fait le move nous-mêmes et on ne dépend plus de la vitesse de Sonarr.
        if cleanup_staging_subfolder_recursively(original_release_folder_in_staging, staging_dir, orphan_exts):
            logger.info("Nettoyage du dossier de staging réussi.")
        else:
            logger.warning("Échec du nettoyage du dossier de staging.")

    rescan_command_payload = {"name": "RescanSeries", "seriesId": series_id_from_frontend}
    command_url = f"{sonarr_url.rstrip('/')}/api/v3/command"
    logger.debug(f"Envoi RescanSeries à Sonarr: Payload={rescan_command_payload}")
    response_data_rescan, error_msg_rescan = _make_arr_request('POST', command_url, sonarr_api_key, json_data=rescan_command_payload)

    final_user_message = f"{imported_files_count} fichier(s) déplacé(s) pour '{series_title_from_sonarr}'."
    if error_msg_rescan:
        final_user_message += f" Rescan Sonarr a échoué: {error_msg_rescan}."
        return jsonify({"success": True, "message": final_user_message, "status_code_override": 207 })

    if response_data_rescan and isinstance(response_data_rescan, dict) and response_data_rescan.get('name') == "RescanSeries":
        final_user_message += " Rescan Sonarr initié."
        return jsonify({"success": True, "message": final_user_message})
    else:
        final_user_message += " Réponse inattendue au rescan Sonarr."
        return jsonify({"success": True, "message": final_user_message, "status_code_override": 207 })

# ------------------------------------------------------------------------------
# FIN DE trigger_sonarr_import
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# NOUVELLE ROUTE POUR L'IMPORT FORCÉ SONARR (PLACÉE ICI)
# ------------------------------------------------------------------------------
@seedbox_ui_bp.route('/force-sonarr-import-action', methods=['POST'])
def force_sonarr_import_action():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name') # Nom de l'item UI original (dossier ou fichier)
    series_id_from_frontend = data.get('series_id')
    target_season_for_move = data.get('target_season') # Saison choisie par l'utilisateur
    # target_episode_for_move = data.get('target_episode') # Épisode choisi (pourrait être utilisé pour nommage plus tard)

    logger.info(f"Action d'import forcé Sonarr reçue pour item: '{item_name_from_frontend}', "
                f"série ID: {series_id_from_frontend}, saison cible: {target_season_for_move}")

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    if not all([item_name_from_frontend, series_id_from_frontend, target_season_for_move is not None,
                sonarr_url, sonarr_api_key, staging_dir]):
        logger.error("force_sonarr_import_action: Données manquantes critiques.")
        return jsonify({"success": False, "error": "Données manquantes pour l'import forcé."}), 400

    # 1. Re-identifier le fichier vidéo principal dans le staging
    #    Cette logique doit être robuste pour retrouver le .mkv basé sur item_name_from_frontend
    path_of_item_clicked_in_ui = os.path.join(staging_dir, item_name_from_frontend)
    main_video_file_source_path = None
    original_release_folder_in_staging = None # Le dossier de plus haut niveau dans le staging pour cet item

    if os.path.isfile(path_of_item_clicked_in_ui):
        if any(path_of_item_clicked_in_ui.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
            main_video_file_source_path = path_of_item_clicked_in_ui
            original_release_folder_in_staging = os.path.dirname(main_video_file_source_path)
        else:
            logger.error(f"Force import: L'item cliqué '{path_of_item_clicked_in_ui}' n'est pas une vidéo reconnue.")
            return jsonify({"success": False, "error": "Le fichier source n'est pas une vidéo reconnue."}), 400
    elif os.path.isdir(path_of_item_clicked_in_ui):
        original_release_folder_in_staging = path_of_item_clicked_in_ui
        # Chercher un fichier vidéo à l'intérieur (logique simplifiée, prend le premier trouvé)
        for root, _, files in os.walk(original_release_folder_in_staging): # os.walk pour chercher récursivement
            for file_name in files:
                if any(file_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
                    main_video_file_source_path = os.path.join(root, file_name)
                    logger.info(f"Force import: Fichier vidéo trouvé via os.walk: {main_video_file_source_path}")
                    break # Prendre le premier
            if main_video_file_source_path:
                break

    if not main_video_file_source_path or not os.path.exists(main_video_file_source_path):
        logger.error(f"Force import: Impossible de trouver le fichier vidéo source pour '{item_name_from_frontend}' dans '{path_of_item_clicked_in_ui}'.")
        return jsonify({"success": False, "error": "Fichier vidéo source non trouvé pour l'import forcé."}), 404

    original_filename = os.path.basename(main_video_file_source_path)
    logger.info(f"Force import: Fichier vidéo source à déplacer: {main_video_file_source_path}")
    logger.info(f"Force import: Dossier de release d'origine (pour nettoyage): {original_release_folder_in_staging}")


    # 2. Récupérer les détails de la série (pour path racine)
    series_details_url = f"{sonarr_url.rstrip('/')}/api/v3/series/{series_id_from_frontend}"
    series_data, error_msg_series_get = _make_arr_request('GET', series_details_url, sonarr_api_key)
    if error_msg_series_get or not series_data:
        logger.error(f"Force import: Erreur récupération détails série {series_id_from_frontend}: {error_msg_series_get}")
        return jsonify({"success": False, "error": "Impossible de récupérer les détails de la série cible."}), 500

    series_root_folder_path = series_data.get('path')
    series_title_from_sonarr = series_data.get('title', 'Série Inconnue')
    if not series_root_folder_path:
        logger.error(f"Force import: Chemin racine non trouvé pour série {series_id_from_frontend}.")
        return jsonify({"success": False, "error": "Chemin racine de la série non trouvé dans Sonarr."}), 500

    # 3. Construire chemin de destination en utilisant target_season_for_move (choisi par l'utilisateur)
    season_folder_name = f"Season {str(target_season_for_move).zfill(2)}"
    destination_season_folder_path = os.path.join(series_root_folder_path, season_folder_name)
    destination_video_file_path = os.path.join(destination_season_folder_path, original_filename) # Garde nom original

    logger.info(f"Import forcé: Déplacement de '{main_video_file_source_path}' vers '{destination_video_file_path}' (Saison {target_season_for_move} choisie).")

    # 4. Logique de déplacement
    try:
        if not os.path.exists(destination_season_folder_path):
            os.makedirs(destination_season_folder_path, exist_ok=True)

        if os.path.normcase(os.path.abspath(main_video_file_source_path)) == os.path.normcase(os.path.abspath(destination_video_file_path)):
            logger.warning(f"Import forcé: Source et destination identiques.")
        else:
            shutil.move(main_video_file_source_path, destination_video_file_path)
        logger.info(f"Import forcé: Déplacement de '{original_filename}' réussi.")
    except Exception as e_move:
        logger.error(f"Import forcé: Erreur shutil.move: {e_move}. Tentative copie/suppr.")
        try:
            shutil.copy2(main_video_file_source_path, destination_video_file_path)
            os.remove(main_video_file_source_path)
            logger.info(f"Import forcé: Copie/suppression de '{original_filename}' réussie.")
        except Exception as e_copy:
            logger.error(f"Import forcé: Erreur copie/suppression fallback: {e_copy}")
            return jsonify({"success": False, "error": f"Erreur déplacement/copie fichier: {e_copy}"}), 500

    # 5. Nettoyage Staging (sur original_release_folder_in_staging)
    if original_release_folder_in_staging and os.path.exists(original_release_folder_in_staging):
        time.sleep(1)
        if cleanup_staging_subfolder_recursively(original_release_folder_in_staging, staging_dir, orphan_exts):
            logger.info(f"Import forcé: Nettoyage du dossier de staging '{original_release_folder_in_staging}' réussi.")
        else:
            logger.warning(f"Import forcé: Échec du nettoyage du dossier de staging '{original_release_folder_in_staging}'.")

    # 6. Rescan Sonarr
    rescan_payload = {"name": "RescanSeries", "seriesId": series_id_from_frontend}
    command_url = f"{sonarr_url.rstrip('/')}/api/v3/command"
    rescan_response, rescan_error = _make_arr_request('POST', command_url, sonarr_api_key, json_data=rescan_payload)

    user_message = f"Fichier pour '{series_title_from_sonarr}' (S{target_season_for_move}) déplacé vers '{destination_video_file_path}'."
    if rescan_error:
        user_message += f" Rescan Sonarr a échoué: {rescan_error}."
    elif rescan_response:
        user_message += " Rescan Sonarr initié."

    logger.info(f"Import forcé terminé. {user_message}")
    return jsonify({"success": True, "message": user_message})
# ------------------------------------------------------------------------------
# trigger_rdarr_import
# ------------------------------------------------------------------------------

@seedbox_ui_bp.route('/trigger-radarr-import', methods=['POST'])
def trigger_radarr_import():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name')
    movie_id_from_frontend = data.get('movie_id')

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    if not all([item_name_from_frontend, movie_id_from_frontend, radarr_url, radarr_api_key, staging_dir]):
        logger.error("trigger_radarr_import: Données manquantes ou Radarr non configuré.")
        return jsonify({"success": False, "error": "Données manquantes ou Radarr non configuré."}), 400

    path_of_item_clicked_in_ui = os.path.join(staging_dir, item_name_from_frontend)
    if not os.path.exists(path_of_item_clicked_in_ui):
        logger.error(f"trigger_radarr_import: L'item UI '{item_name_from_frontend}' (chemin: {path_of_item_clicked_in_ui}) n'existe pas.")
        return jsonify({"success": False, "error": f"L'item '{item_name_from_frontend}' n'existe pas."}), 404

    # --- Étape 1: Identifier le fichier vidéo principal via GET manualimport à Radarr ---
    path_to_scan_for_radarr_get_step = ""
    if os.path.isfile(path_of_item_clicked_in_ui):
        path_to_scan_for_radarr_get_step = os.path.dirname(path_of_item_clicked_in_ui)
    elif os.path.isdir(path_of_item_clicked_in_ui):
        path_to_scan_for_radarr_get_step = path_of_item_clicked_in_ui
    else:
        logger.error(f"L'item '{path_of_item_clicked_in_ui}' n'est ni un fichier ni un dossier valide pour le scan.")
        return jsonify({"success": False, "error": "L'item sélectionné pour le scan n'est pas valide."}), 400

    path_for_radarr_api_get = path_to_scan_for_radarr_get_step.replace('/', '\\')

    manual_import_get_url = f"{radarr_url.rstrip('/')}/api/v3/manualimport"
    get_params = {'folder': path_for_radarr_api_get, 'filterExistingFiles': 'false'}
    logger.debug(f"Appel GET à Radarr ManualImport (pour identification): URL={manual_import_get_url}, Params={get_params}")
    manual_import_candidates, error_msg_get = _make_arr_request('GET', manual_import_get_url, radarr_api_key, params=get_params)

    if error_msg_get or not manual_import_candidates or not isinstance(manual_import_candidates, list):
        logger.error(f"Erreur ou aucun candidat de Radarr GET manualimport: {error_msg_get or 'Pas de candidats'}. Dossier scanné: {path_for_radarr_api_get}")
        return jsonify({"success": False, "error": f"Radarr n'a pas pu analyser le contenu du staging: {error_msg_get or 'Aucun candidat trouvé'}."}), 500

    # Filtrer pour trouver LE candidat pertinent et ses infos
    main_video_file_source_path = None
    original_filename_for_dest = None
    # original_release_folder_in_staging est le dossier qu'on a scanné (et qu'on nettoiera)
    original_release_folder_in_staging = path_to_scan_for_radarr_get_step

    for candidate in manual_import_candidates:
        candidate_file_path_in_staging = candidate.get('path')
        candidate_movie_info = candidate.get('movie')

        if not candidate_file_path_in_staging: continue

        norm_staging_dir_abs = os.path.normcase(os.path.abspath(staging_dir))
        norm_candidate_path_abs = os.path.normcase(os.path.abspath(candidate_file_path_in_staging))
        if not norm_candidate_path_abs.startswith(norm_staging_dir_abs):
            logger.warning(f"Candidat Radarr '{candidate_file_path_in_staging}' ignoré (hors STAGING_DIR).")
            continue

        radarr_detected_movie_id = None
        if candidate_movie_info and candidate_movie_info.get('id') is not None:
            radarr_detected_movie_id = candidate_movie_info.get('id')

        if radarr_detected_movie_id is not None and radarr_detected_movie_id != movie_id_from_frontend:
            logger.warning(f"Candidat Radarr '{candidate_file_path_in_staging}' ignoré: Radarr l'associe au Movie ID "
                           f"{radarr_detected_movie_id}, mais l'utilisateur cible le Movie ID {movie_id_from_frontend}.")
            continue

        # On a un candidat du staging qui soit n'est pas associé par Radarr, soit est associé au bon film.
        main_video_file_source_path = candidate_file_path_in_staging
        original_filename_for_dest = os.path.basename(main_video_file_source_path)
        logger.info(f"Fichier vidéo du staging identifié pour import Radarr: {main_video_file_source_path}")
        logger.info(f"Movie détecté par Radarr: ID {radarr_detected_movie_id if radarr_detected_movie_id else 'Aucun'}. Cible utilisateur: ID {movie_id_from_frontend}.")
        break # Pour Radarr, on prend le premier fichier vidéo pertinent du dossier de release

    if not main_video_file_source_path:
        logger.error(f"Aucun fichier vidéo valide trouvé dans '{path_for_radarr_api_get}' pour le film ID {movie_id_from_frontend} après filtrage.")
        return jsonify({"success": False, "error": "Aucun fichier vidéo valide pour ce film n'a été trouvé dans le dossier de staging."}), 400

    # --- Étape 2: Récupérer les informations du film cible depuis Radarr (pour le chemin final) ---
    movie_details_url = f"{radarr_url.rstrip('/')}/api/v3/movie/{movie_id_from_frontend}"
    logger.debug(f"Appel GET à Radarr pour les détails du film {movie_id_from_frontend}: URL={movie_details_url}")
    movie_data, error_msg_movie_get = _make_arr_request('GET', movie_details_url, radarr_api_key)

    if error_msg_movie_get or not movie_data or not isinstance(movie_data, dict):
        logger.error(f"Impossible de récupérer les détails du film ID {movie_id_from_frontend} de Radarr: {error_msg_movie_get or 'Pas de données'}")
        return jsonify({"success": False, "error": "Impossible de récupérer les détails du film depuis Radarr."}), 500

    # 'path' dans la réponse de /api/v3/movie/{id} est le chemin complet où Radarr s'attend à ce que le dossier du film soit.
    # Ex: F:\Plex\Films\Nom du Film (Année)
    expected_movie_folder_path_from_radarr_api = movie_data.get('path')
    movie_title_from_radarr = movie_data.get('title', 'Titre Inconnu')

    if not expected_movie_folder_path_from_radarr_api:
        logger.error(f"Le film ID {movie_id_from_frontend} n'a pas de 'path' (chemin de destination) défini dans Radarr. Assurez-vous qu'il est bien configuré avec un Root Folder et que le chemin peut être déterminé.")
        return jsonify({"success": False, "error": f"Le film '{movie_title_from_radarr}' n'a pas de chemin de destination configuré dans Radarr."}), 500

    logger.info(f"Chemin du dossier final attendu par Radarr pour '{movie_title_from_radarr}': {expected_movie_folder_path_from_radarr_api}")

    # --- Étape 3: Créer le dossier de destination s'il n'existe pas ---
    # expected_movie_folder_path_from_radarr_api est déjà le chemin du dossier du film.
    destination_folder_for_movie = os.path.abspath(os.path.normpath(expected_movie_folder_path_from_radarr_api))
    try:
        if not os.path.exists(destination_folder_for_movie):
            logger.info(f"Création du dossier de destination: {destination_folder_for_movie}")
            os.makedirs(destination_folder_for_movie, exist_ok=True)
        else:
            logger.info(f"Le dossier de destination {destination_folder_for_movie} existe déjà.")
    except Exception as e:
        logger.error(f"Erreur lors de la création du dossier de destination {destination_folder_for_movie}: {e}")
        return jsonify({"success": False, "error": f"Erreur création dossier destination: {e}"}), 500

    # --- Étape 4: Déplacer le fichier vidéo ---
    # On garde le nom de fichier original du staging pour la destination.
    # Radarr le renommera si "Rename Movies" est activé lors du Rescan.
    destination_video_file_path = os.path.join(destination_folder_for_movie, original_filename_for_dest)

    if os.path.normcase(os.path.abspath(main_video_file_source_path)) == os.path.normcase(os.path.abspath(destination_video_file_path)):
        logger.warning(f"La source et la destination sont identiques ({main_video_file_source_path}). Pas de déplacement. Lancement rescan.")
    else:
        try:
            logger.info(f"Déplacement de '{main_video_file_source_path}' vers '{destination_video_file_path}'")
            shutil.move(main_video_file_source_path, destination_video_file_path)
            logger.info(f"Déplacement du fichier '{original_filename_for_dest}' réussi.")
        except Exception as e_move:
            logger.error(f"Erreur shutil.move pour '{original_filename_for_dest}': {e_move}. Tentative copie/suppr.")
            try:
                shutil.copy2(main_video_file_source_path, destination_video_file_path)
                logger.info(f"Copie de '{original_filename_for_dest}' vers '{destination_video_file_path}' réussie.")
                os.remove(main_video_file_source_path)
                logger.info(f"Source '{main_video_file_source_path}' supprimée après copie.")
            except Exception as e_copy:
                logger.error(f"Erreur copie/suppression fallback pour '{original_filename_for_dest}': {e_copy}")
                return jsonify({"success": False, "error": f"Erreur déplacement/copie fichier: {e_copy}"}), 500

    # --- Étape 5: Nettoyer le dossier de staging d'origine ---
    if original_release_folder_in_staging and os.path.exists(original_release_folder_in_staging):
        logger.info(f"Tentative de nettoyage du dossier de staging d'origine: {original_release_folder_in_staging}")
        time.sleep(2)
        if cleanup_staging_subfolder_recursively(original_release_folder_in_staging, staging_dir, orphan_exts):
            logger.info(f"Nettoyage du dossier de staging '{original_release_folder_in_staging}' réussi.")
        else:
            logger.warning(f"Échec du nettoyage du dossier de staging '{original_release_folder_in_staging}'.")
    # ... (autres logs si besoin) ...

    # --- Étape 6: Déclencher un "Rescan Movie" dans Radarr ---
    rescan_command_payload = {"name": "RescanMovie", "movieId": movie_id_from_frontend}
    command_url = f"{radarr_url.rstrip('/')}/api/v3/command"
    logger.debug(f"Envoi de la commande RescanMovie à Radarr: URL={command_url}, Payload={rescan_command_payload}")
    response_data_rescan, error_msg_rescan = _make_arr_request('POST', command_url, radarr_api_key, json_data=rescan_command_payload)

    final_user_message = ""
    if error_msg_rescan:
        logger.error(f"Erreur lors de l'envoi de la commande RescanMovie (Radarr): {error_msg_rescan}")
        final_user_message = f"Fichier déplacé vers '{destination_video_file_path}'. Le rescan Radarr a échoué: {error_msg_rescan}. Vérifiez et rafraîchissez manuellement dans Radarr."
        return jsonify({"success": True, "message": final_user_message, "status_code_override": 207 }) # 207 Multi-Status

    if response_data_rescan and isinstance(response_data_rescan, dict) and response_data_rescan.get('name') == "RescanMovie":
        logger.info(f"Commande RescanMovie acceptée par Radarr pour le film ID {movie_id_from_frontend}.")
        final_user_message = f"Fichier déplacé vers '{destination_video_file_path}'. Rescan Radarr initié."
        return jsonify({"success": True, "message": final_user_message})
    else:
        logger.warning(f"Réponse inattendue après RescanMovie (Radarr): {response_data_rescan}")
        final_user_message = f"Fichier déplacé vers '{destination_video_file_path}'. Réponse inattendue au rescan Radarr. Vérifiez et rafraîchissez manuellement."
        return jsonify({"success": True, "message": final_user_message, "status_code_override": 207 })


@seedbox_ui_bp.route('/cleanup-staging-item/<path:item_name>', methods=['POST'])
def cleanup_staging_item_action(item_name):
    staging_dir = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    # item_name est le nom de l'item tel qu'affiché dans l'UI (peut être un dossier ou un fichier à la racine du staging)
    item_to_cleanup_path = os.path.join(staging_dir, item_name)
    item_to_cleanup_path = os.path.normpath(os.path.abspath(item_to_cleanup_path)) # Sécurisation

    logger.info(f"Action de nettoyage manuel demandée pour l'item de staging: {item_to_cleanup_path}")

    # Sécurité : Vérifier que item_to_cleanup_path est bien dans staging_dir
    if not item_to_cleanup_path.startswith(os.path.normpath(os.path.abspath(staging_dir))):
        flash("Tentative de nettoyage d'un chemin invalide.", 'danger')
        logger.warning(f"Tentative de nettoyage de chemin invalide : {item_to_cleanup_path}")
        return redirect(url_for('seedbox_ui.index'))

    # On ne nettoie que les dossiers avec cette action pour l'instant
    if not os.path.isdir(item_to_cleanup_path):
        flash(f"L'action de nettoyage ne s'applique qu'aux dossiers. '{item_name}' n'est pas un dossier.", 'warning')
        logger.warning(f"Tentative de nettoyage sur un non-dossier : {item_to_cleanup_path}")
        return redirect(url_for('seedbox_ui.index'))

    # Si le dossier est le staging_dir lui-même, on ne fait rien (la fonction de cleanup a aussi ce garde-fou)
    if item_to_cleanup_path == os.path.normpath(os.path.abspath(staging_dir)):
        flash("Impossible de nettoyer le dossier de staging racine directement.", "danger")
        logger.warning("Tentative de nettoyage du dossier de staging racine via l'UI.")
        return redirect(url_for('seedbox_ui.index'))

    if os.path.exists(item_to_cleanup_path):
        # Le is_top_level_call=True est important ici car c'est le dossier de base qu'on veut nettoyer.
        # La fonction récursive passera False pour ses appels internes.
        success = cleanup_staging_subfolder_recursively(item_to_cleanup_path, staging_dir, orphan_exts, is_top_level_call=True)
        if success:
            # Vérifier si le dossier lui-même a été supprimé ou juste son contenu orphelin
            if not os.path.exists(item_to_cleanup_path):
                flash(f"Le dossier '{item_name}' et/ou son contenu orphelin ont été nettoyés avec succès.", 'success')
                logger.info(f"Nettoyage manuel de '{item_to_cleanup_path}' réussi, dossier supprimé.")
            else:
                flash(f"Les fichiers orphelins dans '{item_name}' ont été nettoyés. Le dossier lui-même reste (il contient des fichiers/dossiers non-orphelins).", 'info')
                logger.info(f"Nettoyage manuel de '{item_to_cleanup_path}' effectué, fichiers orphelins supprimés, dossier conservé.")
        else:
            flash(f"Échec du nettoyage du dossier '{item_name}'. Vérifiez les logs.", 'danger')
            logger.warning(f"Échec du nettoyage manuel de '{item_to_cleanup_path}'.")
    else:
        flash(f"Le dossier '{item_name}' n'existe plus. Pas de nettoyage nécessaire.", 'info')
        logger.info(f"Nettoyage manuel : Le dossier '{item_to_cleanup_path}' n'existe déjà plus.")

    return redirect(url_for('seedbox_ui.index'))
# ------------------------------------------------------------------------------
# FIN DE trigger_rdarr_import
# ------------------------------------------------------------------------------