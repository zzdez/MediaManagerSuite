# app/seedbox_ui/routes.py

# --- Imports Python Standards ---
import os
from app import login_required
import shutil
import logging
import time
import re
from pathlib import Path
import base64
import urllib.parse
import json # Pour les payloads/réponses JSON et potentiellement interagir avec des données JSON
import stat # Si vous l'utilisez pour vérifier les types de fichiers/dossiers (ex: SFTP view)
from datetime import datetime
# --- Imports Flask ---
from flask import (
    Blueprint, render_template, current_app, request,
    flash, redirect, url_for, jsonify, session
)
from app.seedbox_ui import seedbox_ui_bp
# --- Imports de paquets externes (si vous en avez d'autres) ---
import requests # Pour les appels API externes (Sonarr, Radarr, rTorrent)
from requests.exceptions import RequestException # Pour gérer les erreurs de connexion
import paramiko
# --- Imports spécifiques à l'application MediaManagerSuite ---

# Client rTorrent (assurez-vous que ce chemin est correct pour votre projet)
from app.utils.rtorrent_client import (
    list_torrents as rtorrent_list_torrents_api,
    add_magnet as rtorrent_add_magnet_httprpc,
    add_torrent_file as rtorrent_add_torrent_file_httprpc,
    get_torrent_hash_by_name as rtorrent_get_hash_by_name
)

# Gestionnaire de la map des torrents (NOUVELLE FAÇON D'IMPORTER)
# Ceci suppose que le fichier app/utils/mapping_manager.py contient le NOUVEAU code que je vous ai fourni.
from app.utils import mapping_manager as torrent_map_manager

# Si vous avez des fonctions utilitaires spécifiques à seedbox_ui dans un fichier utils.py
# à l'intérieur du dossier app/seedbox_ui/, vous les importeriez comme ceci :
# from .utils import nom_de_votre_fonction_utilitaire
# (Mais _make_arr_request et cleanup_staging_subfolder_recursively sont déjà dans ce fichier routes.py)

# --- Configuration du Logger ---
# Il est préférable d'obtenir le logger via current_app.logger dans vos fonctions,
# mais si vous avez besoin d'un logger au niveau du module, vous pouvez faire :
# logger = logging.getLogger(__name__)
# Et ensuite utiliser `logger.info(...)` au lieu de `current_app.logger.info(...)`
# Pour l'instant, nous avons utilisé current_app.logger dans les fonctions modifiées.

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

# Minimal bencode parser function (copied from previous attempt)
def _decode_bencode_name(bencoded_data):
    """
    Minimalistic bencode decoder to find info['name'].
    Returns the value of info['name'] as a string, or None if not found or error.
    Expects bencoded_data as bytes.
    """
    try:
        # Find '4:infod' (start of info dict)
        info_dict_match = re.search(b'4:infod', bencoded_data)
        if not info_dict_match:
            # Use current_app.logger if available and in context, otherwise module logger
            try: current_app.logger.debug("Bencode: '4:infod' not found.")
            except RuntimeError: logger.debug("Bencode: '4:infod' not found (no app context).")
            return None

        start_index = info_dict_match.end(0) # Position after '4:infod'

        name_key_match = re.search(b'4:name', bencoded_data[start_index:])
        if not name_key_match:
            try: current_app.logger.debug("Bencode: '4:name' not found after '4:infod'.")
            except RuntimeError: logger.debug("Bencode: '4:name' not found after '4:infod' (no app context).")
            return None

        pos_after_name_key = start_index + name_key_match.end(0)

        len_match = re.match(rb'(\d+):', bencoded_data[pos_after_name_key:])
        if not len_match:
            try: current_app.logger.debug("Bencode: Length prefix for name value not found.")
            except RuntimeError: logger.debug("Bencode: Length prefix for name value not found (no app context).")
            return None

        str_len = int(len_match.group(1))
        pos_after_len_colon = pos_after_name_key + len_match.end(0)

        if (pos_after_len_colon + str_len) > len(bencoded_data):
            try: current_app.logger.debug(f"Bencode: Declared name length {str_len} is out of bounds.")
            except RuntimeError: logger.debug(f"Bencode: Declared name length {str_len} is out of bounds (no app context).")
            return None

        name_bytes = bencoded_data[pos_after_len_colon : pos_after_len_colon + str_len]

        try:
            return name_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                return name_bytes.decode('latin-1')
            except UnicodeDecodeError:
                return name_bytes.decode('utf-8', errors='replace')

    except Exception as e:
        # Use current_app.logger if available and in context, otherwise module logger
        try: current_app.logger.warning(f"Exception in _decode_bencode_name: {e}", exc_info=True)
        except RuntimeError: logger.warning(f"Exception in _decode_bencode_name (no app context): {e}", exc_info=True)
        return None

def add_torrent_to_rutorrent(logger, torrent_url_or_magnet, download_dir, label, rutorrent_api_url, username, password, ssl_verify_str):
    """
    Ajoute un torrent (via URL de fichier .torrent ou magnet link) à ruTorrent.

    :param logger: Instance de logger pour enregistrer les messages.
    :param torrent_url_or_magnet: URL du fichier .torrent ou magnet link.
    :param download_dir: Répertoire de téléchargement cible dans ruTorrent.
    :param label: Label à assigner au torrent dans ruTorrent.
    :param rutorrent_api_url: URL de l'API httprpc de ruTorrent (ex: https://host.dom/rutorrent/plugins/httprpc/action.php).
    :param username: Nom d'utilisateur pour l'authentification HTTP Basic (si nécessaire).
    :param password: Mot de passe pour l'authentification HTTP Basic (si nécessaire).
    :param ssl_verify_str: Chaîne "False" pour désactiver la vérification SSL, sinon True.
    :return: Tuple (bool_success, message_str).
    """
    logger.info(f"Tentative d'ajout de torrent à ruTorrent: '{torrent_url_or_magnet[:100]}...'")

    ssl_verify = False if ssl_verify_str == "False" else True
    if not ssl_verify:
        logger.warning("La vérification SSL est désactivée pour les requêtes vers ruTorrent.")
        # Supprimer les avertissements d'insecure request si la vérification SSL est désactivée
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


    session = requests.Session()
    if username and password:
        session.auth = (username, password)
        logger.debug("Authentification HTTP Basic configurée pour la session ruTorrent.")

    try:
        if torrent_url_or_magnet.startswith("magnet:"):
            logger.info("Détection d'un magnet link.")
            data = {
                'mode': 'add', # Mode pour httprpc, action est implicite par le endpoint
                'url': torrent_url_or_magnet,
                'dir_edit': download_dir,
                'label': label
            }
            # Pour httprpc, l'action est souvent déterminée par le endpoint ou des params spécifiques
            # L'URL de base pour httprpc est généralement /plugins/httprpc/action.php
            # et on POST les données dessus. 'action=addtorrent' n'est pas un standard httprpc.
            # On va supposer que le plugin httprpc est assez intelligent pour gérer 'url' comme un magnet.
            # Alternativement, certains plugins httprpc utilisent des params comme 'load_url' pour les magnets.
            # On va utiliser une approche générique.
            # Le plugin rutorrent "addtorrent" classique utilise 'action=add-url' pour les magnets.
            # Si c'est bien httprpc, le mode 'add' et 'url' devraient suffire.
            # Le endpoint pour httprpc est souvent action.php, qui prend 'mode=add'
            # et d'autres paramètres comme 'url', 'dir_edit', 'label'.

            # La requête POST doit être envoyée à l'URL de base de httprpc.
            # Exemple: https://myrutorrent.com/rutorrent/plugins/httprpc/action.php
            # Les 'data' sont les paramètres POST.
            logger.debug(f"Préparation de la requête POST pour magnet link vers {rutorrent_api_url} avec data: {data}")
            response = session.post(rutorrent_api_url, data=data, verify=ssl_verify, timeout=30)
            logger.debug(f"Réponse brute de ruTorrent (magnet): {response.status_code} - {response.text[:500]}")

        else: # URL vers un fichier .torrent
            logger.info(f"Détection d'une URL de fichier .torrent: {torrent_url_or_magnet}")
            # 1. Télécharger le fichier .torrent
            logger.debug(f"Téléchargement du fichier .torrent depuis {torrent_url_or_magnet}")
            torrent_file_response = requests.get(torrent_url_or_magnet, verify=ssl_verify, timeout=60, stream=True)
            torrent_file_response.raise_for_status() # Lève une exception pour les codes 4xx/5xx

            torrent_content = torrent_file_response.content # Lire le contenu
            filename = os.path.basename(torrent_url_or_magnet.split('?')[0]) # Essayer d'extraire un nom de fichier
            if not filename.lower().endswith(".torrent"):
                filename = "file.torrent" # Nom générique si non extractible ou invalide
            logger.debug(f"Fichier .torrent téléchargé, nom: '{filename}', taille: {len(torrent_content)} bytes.")

            # 2. Préparer la requête multipart/form-data pour httprpc
            # Pour httprpc, l'upload de fichier se fait typiquement avec 'mode=addtorrent' (ou similaire)
            # et le fichier est envoyé en multipart.
            files = {'torrent_file': (filename, torrent_content, 'application/x-bittorrent')}
            # Les paramètres 'dir_edit' et 'label' sont envoyés dans 'data'
            data_payload = {
                'mode': 'addtorrent', # Mode spécifique pour l'upload de fichier via httprpc
                'dir_edit': download_dir,
                'label': label
            }
            logger.debug(f"Préparation de la requête POST (multipart) pour fichier .torrent vers {rutorrent_api_url} avec data: {data_payload} et fichier: {filename}")
            response = session.post(rutorrent_api_url, files=files, data=data_payload, verify=ssl_verify, timeout=60)
            logger.debug(f"Réponse brute de ruTorrent (fichier): {response.status_code} - {response.text[:500]}")

        response.raise_for_status() # Vérifier le statut HTTP après l'envoi à ruTorrent

        # Le plugin httprpc retourne généralement un code 200 et un corps JSON vide ou minimal en cas de succès.
        # Il n'y a pas de "page HTML de succès" comme avec l'interface web.
        # On se fie au code 200 et à l'absence d'exception.
        if response.status_code == 200:
            # Certaines implémentations de httprpc peuvent retourner un JSON, d'autres non.
            # Par exemple, le plugin "addtorrent" via httprpc peut ne rien retourner ou un simple {"success": true}
            # On va considérer 200 comme un succès si pas d'exception.
            # Si la réponse contient du texte, on peut le logger.
            # Si c'est du JSON et qu'il contient "error", c'est un échec.
            try:
                json_response = response.json()
                if isinstance(json_response, dict) and json_response.get("error"):
                    error_msg = f"ruTorrent a retourné une erreur: {json_response.get('error_details', json_response['error'])}"
                    logger.error(error_msg)
                    return False, error_msg
                # Si c'est un JSON mais pas d'erreur explicite, on loggue et on continue.
                logger.info(f"Torrent ajouté avec succès (réponse JSON de ruTorrent: {json_response})")
            except ValueError: # Pas de JSON dans la réponse, mais statut 200
                logger.info(f"Torrent ajouté avec succès (réponse non-JSON de ruTorrent, statut {response.status_code}, texte: {response.text[:200]})")

            # Si on arrive ici, c'est un succès.
            return True, "Torrent ajouté avec succès à ruTorrent."
        else:
            # Ce cas ne devrait pas être atteint si raise_for_status() est utilisé,
            # mais par sécurité, on le garde.
            error_msg = f"Échec de l'ajout du torrent, statut HTTP inattendu: {response.status_code}. Réponse: {response.text[:500]}"
            logger.error(error_msg)
            return False, error_msg

    except requests.exceptions.HTTPError as e_http:
        # Erreur HTTP lors du téléchargement du .torrent ou de la communication avec ruTorrent
        error_msg = f"Erreur HTTP: {e_http}. URL: {e_http.request.url}. Réponse: {e_http.response.text[:500] if e_http.response else 'N/A'}"
        logger.error(error_msg)
        return False, error_msg
    except requests.exceptions.ConnectionError as e_conn:
        error_msg = f"Erreur de connexion vers ruTorrent ({rutorrent_api_url}): {e_conn}"
        logger.error(error_msg)
        return False, error_msg
    except requests.exceptions.Timeout as e_timeout:
        error_msg = f"Timeout lors de la communication avec ruTorrent ({rutorrent_api_url}): {e_timeout}"
        logger.error(error_msg)
        return False, error_msg
    except requests.exceptions.RequestException as e_req:
        # Autres erreurs requests (ex: URL malformée, etc.)
        error_msg = f"Erreur générale de requête lors de la communication avec ruTorrent: {e_req}"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e_general:
        # Autres exceptions imprévues
        error_msg = f"Erreur inattendue lors de l'ajout du torrent à ruTorrent: {e_general}"
        logger.error(error_msg, exc_info=True)
        return False, error_msg
    finally:
        if 'requests' in locals() and not ssl_verify: # Rétablir les avertissements si on les avait désactivés
            requests.packages.urllib3.enable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


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

# NOUVELLE FONCTION HELPER SFTP (Version modifiée)
def sftp_build_remote_file_tree(sftp_client, remote_current_path_posix, local_staging_dir_pathobj_to_check, base_remote_path_for_actions):
    """
    Construit récursivement une structure arborescente pour un dossier distant SFTP.
    Chaque nœud contient : name, type ('file' ou 'directory'), path_for_actions (chemin distant complet et POSIX),
                          size_readable, last_modified, is_in_local_staging, et 'children' pour les dossiers.
    'base_remote_path_for_actions' n'est pas utilisé ici car full_remote_path est déjà complet.
    """
    tree = []
    logger.debug(f"SFTP Tree: Listage de {remote_current_path_posix}")
    try:
        remote_item_attrs = []
        try:
            # Vérifier si le chemin existe et est un dossier avant de lister
            path_stat = sftp_client.stat(remote_current_path_posix)
            if not stat.S_ISDIR(path_stat.st_mode):
                logger.warning(f"SFTP Tree: {remote_current_path_posix} n'est pas un dossier. Ne peut pas lister.")
                return [] # Retourner une liste vide si ce n'est pas un dossier
        except FileNotFoundError:
            logger.warning(f"SFTP Tree: Le chemin distant {remote_current_path_posix} n'existe pas lors du listage.")
            return []
        except Exception as e_stat_check:
            logger.error(f"SFTP Tree: Erreur stat sur {remote_current_path_posix} avant listdir: {e_stat_check}")
            return []

        remote_item_attrs = sftp_client.listdir_attr(remote_current_path_posix)

        # Trier pour avoir les dossiers en premier, puis par nom
        # Note: attr.st_mode peut être None si le serveur SFTP est limité. Gérer cela.
        def get_sort_key(attr):
            is_dir_sort = False
            if attr.st_mode is not None:
                is_dir_sort = stat.S_ISDIR(attr.st_mode)
            return (not is_dir_sort, attr.filename.lower())

        sorted_remote_item_attrs = sorted(remote_item_attrs, key=get_sort_key)

        for attr in sorted_remote_item_attrs:
            if attr.filename in ['.', '..']:
                continue

            item_full_remote_path_posix = Path(remote_current_path_posix).joinpath(attr.filename).as_posix()

            potential_local_path = local_staging_dir_pathobj_to_check / attr.filename # Pour les items de premier niveau seulement
            # Calculer le chemin relatif de l'item courant par rapport à base_remote_path_for_actions
            # item_full_remote_path_posix est le chemin complet de l'item distant actuel
            # base_remote_path_for_actions est le chemin racine du scan SFTP

            # S'assurer que les deux chemins sont des objets Path et normalisés pour la comparaison relative_to
            path_obj_item_full_remote = Path(item_full_remote_path_posix)
            path_obj_base_remote = Path(base_remote_path_for_actions)

            is_present_in_local_staging = False
            try:
                # Obtenir le chemin relatif
                # .relative_to() s'attend à ce que path_obj_base_remote soit un parent de path_obj_item_full_remote
                # ou identique. Si item_full_remote_path_posix est "/scan/base/Movies/movie.mkv"
                # et base_remote_path_for_actions est "/scan/base/", alors relative_path sera "Movies/movie.mkv".
                # Si les chemins ne sont pas relatifs (par exemple, base_remote_path_for_actions est un sous-dossier
                # de item_full_remote_path_posix, ou ils sont complètement différents), une ValueError sera levée.
                # Cela ne devrait pas arriver si base_remote_path_for_actions est bien la racine du scan.
                if item_full_remote_path_posix.startswith(base_remote_path_for_actions):
                    relative_path = path_obj_item_full_remote.relative_to(path_obj_base_remote)
                    # Construire le chemin local potentiel en joignant le répertoire de staging local et le chemin relatif
                    potential_local_path = local_staging_dir_pathobj_to_check.joinpath(relative_path)
                    is_present_in_local_staging = potential_local_path.exists()
                else:
                    # Ce cas peut se produire si item_full_remote_path_posix n'est pas DANS base_remote_path_for_actions
                    # ce qui pourrait être une erreur de logique en amont ou une structure de dossier inattendue.
                    # Pour l'instant, on considère que l'item n'est pas dans le staging local.
                    logger.debug(f"SFTP Tree: Item {item_full_remote_path_posix} n'est pas relatif à la base {base_remote_path_for_actions}. "
                                 f"Impossible de vérifier 'is_in_local_staging' précisément pour cet item via chemin relatif.")
                    # On pourrait aussi choisir de vérifier uniquement le nom de fichier à la racine du staging comme fallback:
                    # is_present_in_local_staging = (local_staging_dir_pathobj_to_check / attr.filename).exists()
                    # Mais la consigne est d'utiliser le chemin relatif.
                    is_present_in_local_staging = False


            except ValueError as e_rel_path:
                # Cela peut arriver si base_remote_path_for_actions n'est pas un parent de item_full_remote_path_posix.
                # Ex: item_full_remote_path_posix = /foo/bar, base_remote_path_for_actions = /other/path
                logger.warning(f"SFTP Tree: Erreur de calcul du chemin relatif pour {item_full_remote_path_posix} par rapport à {base_remote_path_for_actions}: {e_rel_path}. "
                               f"is_in_local_staging sera False.")
                is_present_in_local_staging = False
            except Exception as e_path_logic:
                logger.error(f"SFTP Tree: Erreur inattendue dans la logique de is_in_local_staging pour {attr.filename}: {e_path_logic}", exc_info=True)
                is_present_in_local_staging = False

            node = {
                'name': attr.filename,
                'path_for_actions': item_full_remote_path_posix, # Chemin distant complet, POSIX
                'is_dir': False,
                'size_bytes': 0,
                'size_readable': "N/A",
                'mtime_timestamp': None,
                'last_modified': "N/A",
                'is_in_local_staging': is_present_in_local_staging,
                'children': []
            }

            if attr.st_mode is not None:
                node['is_dir'] = stat.S_ISDIR(attr.st_mode)
                if not node['is_dir'] and attr.st_size is not None:
                    node['size_bytes'] = attr.st_size

            if attr.st_mtime is not None:
                node['mtime_timestamp'] = attr.st_mtime
                node['last_modified'] = datetime.fromtimestamp(attr.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

            if node['is_dir']:
                node['size_readable'] = "N/A (dossier)"
                # Appel récursif pour les enfants
                node['children'] = sftp_build_remote_file_tree(sftp_client, item_full_remote_path_posix, local_staging_dir_pathobj_to_check, base_remote_path_for_actions)
            elif node['size_bytes'] == 0:
                node['size_readable'] = "0 B"
            else:
                s_name = ("B", "KB", "MB", "GB", "TB")
                s_idx = 0
                s_temp = float(node['size_bytes'])
                while s_temp >= 1024 and s_idx < len(s_name) - 1:
                    s_temp /= 1024.0
                    s_idx += 1
                node['size_readable'] = f"{s_temp:.2f} {s_name[s_idx]}"

            tree.append(node)
    except OSError as e_os:
        logger.error(f"SFTP Tree: Erreur OS lors du listage de {remote_current_path_posix}: {e_os}")
    except Exception as e_list:
        logger.error(f"SFTP Tree: Erreur inattendue lors du listage de {remote_current_path_posix}: {e_list}", exc_info=True)

    return tree

@seedbox_ui_bp.route('/process-staging-item', methods=['POST'])
@login_required
def process_staging_item_api(): # Renommé pour éviter conflit si vous aviez une var 'process_staging_item'
    """
    API endpoint to be called by sftp_downloader_notifier.py after an item
    is downloaded to the local staging directory.
    This endpoint will try to automatically import the item using pre-associations.
    """
    logger = current_app.logger # Utiliser le logger de Flask

    auth_header = request.headers.get('Authorization')
    # Optionnel: Sécuriser cet endpoint.
    # Pour l'instant, on assume qu'il est appelé depuis un script local approuvé.
    # Vous pourriez ajouter une clé API simple dans l'en-tête ou un token si nécessaire.
    # Example:
    # expected_token = current_app.config.get('SFTPSCRIPT_API_TOKEN')
    # if not expected_token or not auth_header or auth_header != f"Bearer {expected_token}":
    #     logger.warning("process_staging_item_api: Unauthorized access attempt.")
    #     return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json()
    if not data or 'item_name_in_staging' not in data:
        logger.warning("process_staging_item_api: POST request missing 'item_name_in_staging' in JSON body.")
        return jsonify({"status": "error", "message": "Missing 'item_name_in_staging' in JSON payload"}), 400

    item_name_in_staging = data['item_name_in_staging']
    # Sécurité simple: s'assurer que item_name_in_staging ne contient pas de traversée de répertoire
    if ".." in item_name_in_staging or "/" in item_name_in_staging or "\\" in item_name_in_staging:
        logger.error(f"process_staging_item_api: Invalid item_name_in_staging (path traversal attempt?): {item_name_in_staging}")
        return jsonify({"status": "error", "message": "Invalid item name"}), 400

    logger.info(f"process_staging_item_api: Received request to process staging item: '{item_name_in_staging}'")

    # Utiliser torrent_map_manager pour trouver l'association
    # Note: find_torrent_by_release_name s'attend au nom de la release tel qu'il est dans le staging
    torrent_hash, mapping_data = torrent_map_manager.find_torrent_by_release_name(item_name_in_staging)

    if not mapping_data:
        logger.info(f"process_staging_item_api: No pre-association found for release name: '{item_name_in_staging}'. Item will require manual mapping.")
        # On pourrait mettre à jour un log interne ou une DB d'items non mappés ici si besoin.
        # Le script SFTP pourrait être informé de cela pour qu'il ne retente pas indéfiniment pour cet item
        return jsonify({"status": "no_association_found", "message": "No pre-association found. Manual mapping required."}), 202 # 202 Accepted

    logger.info(f"process_staging_item_api: Found pre-association for '{item_name_in_staging}': Torrent Hash {torrent_hash}, Type: {mapping_data.get('app_type')}, Target ID: {mapping_data.get('target_id')}")

    full_staging_path_str = str((Path(current_app.config['STAGING_DIR']) / item_name_in_staging).resolve())

    # Vérifier si le chemin existe réellement dans le staging
    if not os.path.exists(full_staging_path_str):
        err_msg = f"Staging path '{full_staging_path_str}' does not exist for item '{item_name_in_staging}'."
        logger.error(f"process_staging_item_api: {err_msg}")
        torrent_map_manager.update_torrent_status_in_map(torrent_hash, "error_staging_path_missing_on_api_call", err_msg)
        return jsonify({"status": "error", "message": err_msg}), 404 # Not Found

    # Mettre à jour le statut dans la map avant de commencer le traitement
    torrent_map_manager.update_torrent_status_in_map(
        torrent_hash,
        "processing_by_mms_api",
        f"MMS API processing started for {item_name_in_staging}"
    )

    result_from_handler = {}
    app_type = mapping_data.get('app_type')
    target_id = mapping_data.get('target_id')

    # path_to_cleanup est le nom de l'item dans le staging, car nos helpers attendent cela
    # pour la fonction cleanup_staging_subfolder_recursively.
    path_to_cleanup = item_name_in_staging # Le nom du dossier/fichier principal dans STAGING_DIR

    if app_type == 'sonarr':
        # Pour l'import automatique, on ne force pas de saison.
        # _handle_staged_sonarr_item essaiera de la parser ou de se fier à Sonarr.
        # Si une saison spécifique était stockée dans mapping_data, on pourrait la passer.
        # Exemple: user_chosen_season_from_map = mapping_data.get('season_number')
        result_from_handler = _handle_staged_sonarr_item(
            item_name_in_staging=item_name_in_staging, # Le nom du dossier/fichier dans STAGING_DIR
            series_id_target=target_id,
            path_to_cleanup_in_staging_after_success=full_staging_path_str, # Chemin absolu de l'item à nettoyer
            user_chosen_season=None, # Laisser le helper déterminer ou se fier à Sonarr
            automated_import=True,
            torrent_hash_for_status_update=torrent_hash
        )
    elif app_type == 'radarr':
        result_from_handler = _handle_staged_radarr_item(
            item_name_in_staging=item_name_in_staging, # Le nom du dossier/fichier dans STAGING_DIR
            movie_id_target=target_id,
            path_to_cleanup_in_staging_after_success=full_staging_path_str, # Chemin absolu de l'item à nettoyer
            automated_import=True,
            torrent_hash_for_status_update=torrent_hash
        )
    else:
        err_msg = f"Unknown association type '{app_type}' for torrent {torrent_hash}, item '{item_name_in_staging}'."
        logger.error(f"process_staging_item_api: {err_msg}")
        torrent_map_manager.update_torrent_status_in_map(torrent_hash, "error_unknown_association_type", err_msg)
        return jsonify({"status": "error", "message": err_msg}), 500

    # Analyser le résultat du helper
    if result_from_handler.get("success"):
        logger.info(f"process_staging_item_api: Successfully processed '{item_name_in_staging}' for {app_type} ID {target_id}.")
        # Le statut aura été mis à "imported_by_mms" par le helper.

        # Maintenant, supprimer l'entrée du map puisque l'import est réussi.
        if torrent_hash: # S'assurer qu'on a bien un hash (devrait toujours être le cas ici)
            if torrent_map_manager.remove_torrent_from_map(torrent_hash):
                logger.info(f"process_staging_item_api: Association pour torrent hash '{torrent_hash}' (Release: {item_name_in_staging}) supprimée du map après import réussi.")
            else:
                logger.warning(f"process_staging_item_api: Échec de la suppression de l'association pour hash '{torrent_hash}' du map, bien que l'import ait réussi.")
        else:
            logger.warning(f"process_staging_item_api: Aucun torrent_hash disponible pour la suppression du map pour {item_name_in_staging}, bien que l'import ait réussi.")

        return jsonify({"status": "success", "message": f"Successfully processed '{item_name_in_staging}'. Details: {result_from_handler.get('message')}"}), 200
    elif result_from_handler.get("manual_required"):
        logger.warning(f"process_staging_item_api: Processing '{item_name_in_staging}' requires manual intervention. Reason: {result_from_handler.get('message')}")
        # Le statut aura déjà été mis à jour par le helper avec une erreur spécifique.
        return jsonify({"status": "manual_intervention_required", "message": result_from_handler.get('message')}), 202 # Accepted, mais nécessite action
    else: # Erreur générique non gérée comme "manual_required" par le helper (devrait être rare)
        err_msg = f"Error processing '{item_name_in_staging}'. Reason: {result_from_handler.get('message', 'Unknown error from handler')}"
        logger.error(f"process_staging_item_api: {err_msg}")
        # Le statut peut ou peut ne pas avoir été mis à jour par le helper, s'assurer qu'il y a une indication d'erreur
        current_status_data = torrent_map_manager.get_torrent_by_hash(torrent_hash)
        if current_status_data and not current_status_data.get("status", "").startswith("error_"):
             torrent_map_manager.update_torrent_status_in_map(torrent_hash, "error_mms_api_processing_failed", err_msg)
        return jsonify({"status": "error", "message": err_msg}), 500


# ==============================================================================
# NOUVELLE FONCTION HELPER POUR TRAITER UN ITEM SONARR DÉJÀ DANS LE STAGING
# ==============================================================================

# Dans app/seedbox_ui/routes.py

def _handle_staged_sonarr_item(item_name_in_staging, series_id_target,
                               path_to_cleanup_in_staging_after_success, # Chemin absolu du dossier de release dans le staging
                               user_chosen_season=None, # Saison choisie pour TOUS les épisodes si c'est un pack de saison mal nommé
                               automated_import=False,
                               torrent_hash_for_status_update=None):
    logger = current_app.logger
    log_prefix = f"HDL_SONARR (Auto:{automated_import}, Hash:{torrent_hash_for_status_update}, Item:'{item_name_in_staging}', SeriesID:{series_id_target}, ChosenS:{user_chosen_season}): "
    logger.info(f"{log_prefix}Début du traitement.")

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir_str = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    # path_to_process_abs est le dossier de la release (ou le fichier unique) dans le staging
    path_to_process_abs = (Path(staging_dir_str) / item_name_in_staging).resolve()

    if not path_to_process_abs.exists():
        err_msg = f"Item '{item_name_in_staging}' non trouvé à '{path_to_process_abs}'."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and automated_import:
            torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_staging_path_missing", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    # Récupérer les détails de la série pour le chemin racine (fait une seule fois)
    series_details_url = f"{sonarr_url.rstrip('/')}/api/v3/series/{series_id_target}"
    series_data, error_series_data = _make_arr_request('GET', series_details_url, sonarr_api_key)
    if error_series_data or not series_data:
        err_msg = f"Impossible de récupérer détails série Sonarr ID {series_id_target}: {error_series_data}"
        # ... (gestion d'erreur et retour comme avant) ...
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and automated_import:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_sonarr_api", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    series_root_folder_path_str = series_data.get('path')
    series_title_from_sonarr = series_data.get('title', 'Série Inconnue')
    if not series_root_folder_path_str:
        err_msg = f"Chemin racine pour série '{series_title_from_sonarr}' (ID {series_id_target}) non trouvé dans Sonarr."
        # ... (gestion d'erreur et retour) ...
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and automated_import:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_sonarr_config", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    series_root_path = Path(series_root_folder_path_str)

    video_files_to_process = []
    if path_to_process_abs.is_file():
        if any(str(path_to_process_abs).lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi']):
            video_files_to_process.append({"path": path_to_process_abs, "original_filename": path_to_process_abs.name})
        else:
            err_msg = f"Item fichier '{item_name_in_staging}' n'est pas une vidéo reconnue."
            logger.error(f"{log_prefix}{err_msg}")
            return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}
    elif path_to_process_abs.is_dir():
        for root, _, files in os.walk(path_to_process_abs):
            for file_name in files:
                if any(file_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi']):
                    video_files_to_process.append({"path": Path(root) / file_name, "original_filename": file_name})
        if not video_files_to_process:
            err_msg = f"Aucun fichier vidéo trouvé dans le dossier '{item_name_in_staging}'."
            logger.error(f"{log_prefix}{err_msg}")
            return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}
    else:
        err_msg = "Item de staging non valide."
        # ... (gestion d'erreur et retour) ...
        logger.error(f"{log_prefix}{err_msg}")
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    logger.info(f"{log_prefix} Fichiers vidéo à traiter: {[str(f['path']) for f in video_files_to_process]}")

    successful_moves = 0
    failed_moves_details = []
    processed_filenames_for_message = []

    for video_file_info in video_files_to_process:
        current_video_file_path = video_file_info["path"]
        original_video_filename = video_file_info["original_filename"]
        logger.info(f"{log_prefix}Traitement du fichier vidéo: {original_video_filename}")

        # --- Détermination Saison/Épisode pour CE fichier ---
        # (Similaire à la logique existante, mais appliquée par fichier)
        sonarr_identified_season_num_for_file = None
        # Path à scanner pour Sonarr (dossier parent du fichier vidéo actuel)
        path_to_scan_for_file_api = str(current_video_file_path.parent).replace('/', '\\')

        manual_import_get_url = f"{sonarr_url.rstrip('/')}/api/v3/manualimport"
        # On passe le dossier parent du fichier pour que Sonarr puisse analyser le nom du fichier
        get_params_file = {'folder': path_to_scan_for_file_api, 'filterExistingFiles': 'false', 'seriesId': series_id_target}
        logger.debug(f"{log_prefix}GET Sonarr ManualImport pour fichier '{original_video_filename}': Params={get_params_file}")
        candidates, error_get_file = _make_arr_request('GET', manual_import_get_url, sonarr_api_key, params=get_params_file)

        if not error_get_file and isinstance(candidates, list):
            for cand in candidates:
                # Sonarr retourne 'path' relatif au 'folder' scanné.
                # On compare le nom de fichier.
                if Path(cand.get('path','')).name.lower() == original_video_filename.lower():
                    ep_info = cand.get('episodes', [])
                    if ep_info:
                        sonarr_identified_season_num_for_file = ep_info[0].get('seasonNumber')
                        logger.info(f"{log_prefix}Sonarr a identifié S{sonarr_identified_season_num_for_file} pour '{original_video_filename}'.")
                    break
        else:
            logger.warning(f"{log_prefix}Pas de candidat Sonarr ou erreur pour '{original_video_filename}': {error_get_file}")

        # Logique de détermination de la saison (user_chosen_season a la priorité pour tous les fichiers du pack)
        season_for_this_file = None
        if user_chosen_season is not None:
            season_for_this_file = user_chosen_season
            logger.info(f"{log_prefix}Utilisation saison forcée '{user_chosen_season}' pour '{original_video_filename}'.")
        else:
            # Parsing du nom de CE fichier
            s_e_match = re.search(r'[._\s\[\(-]S(\d{1,3})([E._\s-]\d{1,3})?', original_video_filename, re.IGNORECASE)
            if s_e_match:
                try: season_for_this_file = int(s_e_match.group(1))
                except (ValueError, IndexError): pass

            if season_for_this_file is not None:
                logger.info(f"{log_prefix}Saison S{season_for_this_file} parsée du nom de fichier '{original_video_filename}'.")
                if sonarr_identified_season_num_for_file is not None and sonarr_identified_season_num_for_file != season_for_this_file:
                    logger.warning(f"{log_prefix}Discordance (info): Nom fichier S{season_for_this_file} vs Sonarr S{sonarr_identified_season_num_for_file}. Priorité au nom de fichier.")
            elif sonarr_identified_season_num_for_file is not None:
                season_for_this_file = sonarr_identified_season_num_for_file
                logger.info(f"{log_prefix}Utilisation saison S{season_for_this_file} identifiée par Sonarr pour '{original_video_filename}'.")
            else:
                # Cas problématique : pas de saison choisie, pas de parsing, pas d'info Sonarr
                # En mode automatisé, c'est un échec pour ce fichier.
                # En mode manuel (depuis UI), on pourrait demander la saison pour le pack.
                # Pour l'instant, si automatisé et pas de saison, on logue une erreur pour CE fichier.
                err_msg_file = f"Impossible de déterminer la saison pour '{original_video_filename}'."
                logger.error(f"{log_prefix}{err_msg_file}")
                failed_moves_details.append({"file": original_video_filename, "reason": err_msg_file})
                # Si on est en mode automatisé et qu'on ne peut pas déterminer une saison, on pourrait skipper ce fichier.
                if automated_import: # Si l'appel vient de l'API automatique
                    # Mettre à jour le statut du torrent principal pour indiquer un problème
                    if torrent_hash_for_status_update:
                         torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_sonarr_season_undefined_for_file", f"Saison manquante pour {original_video_filename}")
                    # On pourrait choisir de retourner une erreur ici si on veut que TOUT échoue si un fichier échoue
                    # ou juste continuer avec les autres fichiers. Pour l'instant, on continue.
                continue # Passer au fichier vidéo suivant

        if season_for_this_file is None: # Double check, au cas où la logique ci-dessus a un trou
            err_msg_file = f"Saison non déterminée pour '{original_video_filename}' après toutes les vérifications."
            logger.error(f"{log_prefix}{err_msg_file}")
            failed_moves_details.append({"file": original_video_filename, "reason": err_msg_file})
            continue

        # --- Déplacement de CE fichier ---
        dest_season_folder_name = f"Season {str(season_for_this_file).zfill(2)}"
        dest_season_path_abs = series_root_path / dest_season_folder_name
        dest_file_path_abs = dest_season_path_abs / original_video_filename

        logger.info(f"{log_prefix}Déplacement MMS: '{current_video_file_path}' vers '{dest_file_path_abs}'")
        try:
            dest_season_path_abs.mkdir(parents=True, exist_ok=True)
            if current_video_file_path.resolve() != dest_file_path_abs.resolve():
                shutil.move(str(current_video_file_path), str(dest_file_path_abs))
            else:
                logger.warning(f"{log_prefix}Source et destination identiques pour {original_video_filename}.")
            successful_moves += 1
            processed_filenames_for_message.append(original_video_filename)
        except Exception as e_move:
            logger.error(f"{log_prefix}Erreur déplacement '{original_video_filename}': {e_move}. Tentative copie/suppr.")
            try:
                if current_video_file_path.parent.exists():
                    shutil.copy2(str(current_video_file_path), str(dest_file_path_abs))
                    os.remove(str(current_video_file_path))
                    successful_moves += 1
                    processed_filenames_for_message.append(original_video_filename)
                else: # Source parent does not exist, something is wrong
                    logger.error(f"{log_prefix}Parent source {current_video_file_path.parent} inexistant. Échec copie/suppression pour {original_video_filename}")
                    failed_moves_details.append({"file": original_video_filename, "reason": f"Erreur de déplacement (parent source manquant): {e_move}"})
            except Exception as e_copy:
                logger.error(f"{log_prefix}Erreur copie/suppr '{original_video_filename}': {e_copy}")
                failed_moves_details.append({"file": original_video_filename, "reason": f"Échec copie/suppression: {e_copy}"})
    # --- Fin de la boucle sur les fichiers vidéo ---

    if successful_moves == 0 and video_files_to_process: # Si aucun fichier n'a pu être déplacé
        final_err_msg = "Aucun fichier vidéo n'a pu être déplacé."
        if failed_moves_details:
            final_err_msg += f" Premier échec: {failed_moves_details[0]['reason']}"
        logger.error(f"{log_prefix}{final_err_msg}")
        if torrent_hash_for_status_update and automated_import:
            torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_all_files_failed_move", final_err_msg)
        return {"success": False, "message": final_err_msg, "manual_required": True if automated_import else False}

    # --- Nettoyage du dossier de staging d'origine (path_to_cleanup_in_staging_after_success) ---
    # path_to_cleanup_in_staging_after_success est le chemin absolu du dossier de release passé à la fonction
    actual_folder_to_cleanup = Path(path_to_cleanup_in_staging_after_success)
    # Si l'item original était un fichier, on cible son parent pour le cleanup.
    # Mais si on traite un pack, path_to_cleanup_in_staging_after_success est déjà le dossier.
    if actual_folder_to_cleanup.is_file(): # Devrait rarement arriver si on traite des packs de dossier
         actual_folder_to_cleanup = actual_folder_to_cleanup.parent

    if actual_folder_to_cleanup.exists() and actual_folder_to_cleanup.is_dir():
        logger.info(f"{log_prefix}Nettoyage du dossier de staging: {actual_folder_to_cleanup}")
        time.sleep(1)
        try:
            # La fonction cleanup_staging_subfolder_recursively devrait maintenant vider le dossier
            # car tous les fichiers vidéo principaux ont été déplacés.
            cleanup_staging_subfolder_recursively(str(actual_folder_to_cleanup), staging_dir_str, orphan_exts)
        except Exception as e_cleanup:
            logger.error(f"{log_prefix}Erreur lors du nettoyage de {actual_folder_to_cleanup}: {e_cleanup}")
            # Ne pas considérer cela comme un échec bloquant de l'import si les fichiers ont été déplacés.
    else:
        logger.warning(f"{log_prefix}Dossier à nettoyer {actual_folder_to_cleanup} non trouvé ou n'est pas un dossier.")


    # --- Rescan Sonarr (une seule fois après tous les déplacements) ---
    rescan_payload = {"name": "RescanSeries", "seriesId": series_id_target}
    command_url = f"{sonarr_url.rstrip('/')}/api/v3/command"
    _, error_rescan = _make_arr_request('POST', command_url, sonarr_api_key, json_data=rescan_payload)

    final_message = f"{successful_moves} fichier(s) (pour '{series_title_from_sonarr}') déplacé(s) avec succès."
    if processed_filenames_for_message:
        final_message += f" Fichiers: {', '.join(processed_filenames_for_message[:3])}{'...' if len(processed_filenames_for_message) > 3 else ''}."
    if failed_moves_details:
        final_message += f" {len(failed_moves_details)} fichier(s) ont échoué (voir logs)."

    if error_rescan:
        final_message += f" Échec du Rescan Sonarr: {error_rescan}."
        logger.warning(f"{log_prefix}Rescan Sonarr échoué: {error_rescan}")
    else:
        final_message += " Rescan Sonarr initié."
        logger.info(f"{log_prefix}Rescan Sonarr initié pour série ID {series_id_target}.")

    if torrent_hash_for_status_update and automated_import:
        # Si certains fichiers ont échoué mais d'autres non, le statut est un peu ambigu.
        # On pourrait créer un statut "imported_partial_error"
        current_status_update = "imported_by_mms" if not failed_moves_details else "imported_partial_mms_error"
        torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, current_status_update, final_message)
        # Si tout est ok et pas d'échecs, et que la config est de supprimer du map:
        # if not failed_moves_details and current_app.config.get('AUTO_REMOVE_SUCCESSFUL_FROM_MAP', True):
        #    torrent_map_manager.remove_torrent_from_map(torrent_hash_for_status_update)

    return {"success": True if not failed_moves_details else False, # Succès global si aucun échec de fichier individuel
            "message": final_message,
            "manual_required": bool(failed_moves_details) } # Manuel requis s'il y a eu des échecs

# ==============================================================================
# FIN DE LA FONCTION HELPER _handle_staged_sonarr_item
# ==============================================================================
# ==============================================================================
# NOUVELLE FONCTION HELPER POUR TRAITER UN ITEM RADARR DÉJÀ DANS LE STAGING
# ==============================================================================
# Ligne juste avant : la fonction _handle_staged_sonarr_item (ou d'autres helpers)

def _handle_staged_radarr_item(item_name_in_staging, movie_id_target,
                               path_to_cleanup_in_staging_after_success,
                               automated_import=False, # NOUVEAU
                               torrent_hash_for_status_update=None): # NOUVEAU
    """
    Gère l'import d'un item Radarr déjà présent dans le staging local.
    - MediaManagerSuite effectue le déplacement.
    - Déclenche un RescanMovie.
    - Nettoie le dossier de staging.
    """
    logger = current_app.logger
    log_prefix = f"HELPER _handle_staged_radarr_item (Automated: {automated_import}, Hash: {torrent_hash_for_status_update}): "
    logger.info(f"{log_prefix}Traitement de '{item_name_in_staging}' pour Movie ID {movie_id_target}.")

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir_str = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    path_of_item_in_staging_abs = (Path(staging_dir_str) / item_name_in_staging).resolve()
    if not path_of_item_in_staging_abs.exists():
        err_msg = f"Item '{item_name_in_staging}' (résolu en {path_of_item_in_staging_abs}) non trouvé."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and automated_import:
            torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_staging_path_missing", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    main_video_file_abs_path_in_staging = None
    original_filename_of_video = None

    if path_of_item_in_staging_abs.is_file() and any(str(path_of_item_in_staging_abs).lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
        main_video_file_abs_path_in_staging = path_of_item_in_staging_abs
        original_filename_of_video = path_of_item_in_staging_abs.name
    elif path_of_item_in_staging_abs.is_dir():
        for root, _, files in os.walk(path_of_item_in_staging_abs):
            for file in files:
                if any(file.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
                    main_video_file_abs_path_in_staging = Path(root) / file
                    original_filename_of_video = file
                    break
            if main_video_file_abs_path_in_staging:
                break
        if not main_video_file_abs_path_in_staging:
            err_msg = f"Aucun fichier vidéo trouvé dans le dossier '{item_name_in_staging}'."
            logger.error(f"{log_prefix}{err_msg}")
            return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}
    else:
        err_msg = "Item de staging non valide (ni fichier, ni dossier)."
        logger.error(f"{log_prefix}{err_msg}")
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    logger.info(f"{log_prefix}Fichier vidéo principal: {main_video_file_abs_path_in_staging}")

    movie_details_url = f"{radarr_url.rstrip('/')}/api/v3/movie/{movie_id_target}"
    logger.debug(f"{log_prefix}GET Radarr Movie Details: URL={movie_details_url}")
    movie_data, error_movie_data = _make_arr_request('GET', movie_details_url, radarr_api_key)

    if error_movie_data or not movie_data or not isinstance(movie_data, dict):
        err_msg = f"Erreur détails film {movie_id_target}: {error_movie_data or 'Pas de données Radarr'}"
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and automated_import:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_radarr_api", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    expected_movie_folder_path_from_radarr_api = movie_data.get('path')
    movie_title = movie_data.get('title', 'Film Inconnu')
    if not expected_movie_folder_path_from_radarr_api:
        err_msg = f"Chemin ('path') manquant pour film ID {movie_id_target} ('{movie_title}') dans Radarr."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and automated_import:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_radarr_config", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    logger.info(f"{log_prefix}Chemin dossier final Radarr pour '{movie_title}': {expected_movie_folder_path_from_radarr_api}")

    destination_folder_for_movie = Path(expected_movie_folder_path_from_radarr_api).resolve()
    destination_video_file_path_abs = destination_folder_for_movie / original_filename_of_video

    logger.info(f"{log_prefix}Déplacement MMS: '{main_video_file_abs_path_in_staging}' vers '{destination_video_file_path_abs}'")
    imported_successfully = False
    try:
        destination_folder_for_movie.mkdir(parents=True, exist_ok=True)
        if main_video_file_abs_path_in_staging.resolve() != destination_video_file_path_abs.resolve():
            shutil.move(str(main_video_file_abs_path_in_staging), str(destination_video_file_path_abs))
        else:
            logger.warning(f"{log_prefix}Source et destination identiques: {main_video_file_abs_path_in_staging}")
        imported_successfully = True
    except Exception as e_move:
        logger.error(f"{log_prefix}Erreur move '{original_filename_of_video}': {e_move}. Tentative copie/suppr.")
        try:
            if main_video_file_abs_path_in_staging.parent.exists():
                shutil.copy2(str(main_video_file_abs_path_in_staging), str(destination_video_file_path_abs))
                os.remove(str(main_video_file_abs_path_in_staging))
                imported_successfully = True
            else:
                logger.error(f"{log_prefix}Parent du fichier source {main_video_file_abs_path_in_staging.parent} n'existe pas. Abandon copie/suppr.")
                imported_successfully = False
        except Exception as e_copy:
            err_msg = f"Échec du déplacement (copie/suppression) du fichier '{original_filename_of_video}': {e_copy}"
            logger.error(f"{log_prefix}{err_msg}")
            if torrent_hash_for_status_update and automated_import:
                 torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_file_move", err_msg)
            return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    if not imported_successfully:
        err_msg = f"Échec inattendu du déplacement de '{original_filename_of_video}'."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and automated_import:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_file_move", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if automated_import else False}

    actual_folder_to_cleanup = Path(path_to_cleanup_in_staging_after_success)
    if actual_folder_to_cleanup.is_file():
        actual_folder_to_cleanup = actual_folder_to_cleanup.parent

    if actual_folder_to_cleanup.exists() and actual_folder_to_cleanup.is_dir():
        logger.info(f"{log_prefix}Nettoyage dossier staging: {actual_folder_to_cleanup}")
        time.sleep(1)
        try:
            cleanup_staging_subfolder_recursively(str(actual_folder_to_cleanup), staging_dir_str, orphan_exts)
        except NameError:
            logger.error(f"{log_prefix}Fonction 'cleanup_staging_subfolder_recursively' non trouvée. Nettoyage manuel requis pour {actual_folder_to_cleanup}")
        except Exception as e_cleanup:
            logger.error(f"{log_prefix}Erreur lors du nettoyage de {actual_folder_to_cleanup}: {e_cleanup}")

    rescan_payload = {"name": "RescanMovie", "movieId": movie_id_target}
    command_url = f"{radarr_url.rstrip('/')}/api/v3/command"
    _, error_rescan = _make_arr_request('POST', command_url, radarr_api_key, json_data=rescan_payload)

    final_message = f"Fichier pour '{movie_title}' déplacé avec succès."
    if error_rescan:
        final_message += f" Échec du Rescan Radarr: {error_rescan}."
        logger.warning(f"{log_prefix}Rescan Radarr échoué: {error_rescan}")
    else:
        final_message += " Rescan Radarr initié."
        logger.info(f"{log_prefix}Rescan Radarr initié pour movie ID {movie_id_target}.")

    if torrent_hash_for_status_update and automated_import:
        torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "imported_by_mms", final_message)
        # Optionnel: remove_torrent_from_map(torrent_hash_for_status_update)

    return {"success": True, "message": final_message, "manual_required": False}

# Ligne juste après : vos autres routes, ou la fin du fichier.

# FIN de _handle_staged_radarr_item
def sftp_delete_recursive(sftp_client, remote_path_posix, current_logger):
    """
    Supprime un fichier ou un dossier (récursivement) sur le serveur SFTP.
    Retourne True si succès total, False sinon.
    """
    current_logger.info(f"SFTP Delete: Tentative de suppression de '{remote_path_posix}'")
    try:
        item_stat = sftp_client.stat(remote_path_posix)
    except FileNotFoundError:
        current_logger.warning(f"SFTP Delete: Item '{remote_path_posix}' non trouvé. Considéré comme supprimé.")
        return True # Si déjà parti, c'est un succès en quelque sorte
    except Exception as e_stat:
        current_logger.error(f"SFTP Delete: Erreur STAT sur '{remote_path_posix}': {e_stat}")
        return False

    if stat.S_ISDIR(item_stat.st_mode):
        # C'est un dossier, supprimer son contenu récursivement
        current_logger.debug(f"SFTP Delete: '{remote_path_posix}' est un dossier. Listage du contenu...")
        all_children_deleted_successfully = True
        try:
            for item_name in sftp_client.listdir(remote_path_posix):
                if item_name in ['.', '..']:
                    continue
                child_path_posix = Path(remote_path_posix).joinpath(item_name).as_posix()
                if not sftp_delete_recursive(sftp_client, child_path_posix, current_logger):
                    all_children_deleted_successfully = False
                    # On pourrait choisir d'arrêter ici si un enfant ne peut pas être supprimé
                    # ou continuer et rapporter un échec partiel. Pour l'instant, on continue.

            if all_children_deleted_successfully:
                current_logger.info(f"SFTP Delete: Tous les enfants de '{remote_path_posix}' supprimés (ou étaient inexistants). Suppression du dossier lui-même.")
                sftp_client.rmdir(remote_path_posix)
                current_logger.info(f"SFTP Delete: Dossier '{remote_path_posix}' supprimé avec succès.")
                return True
            else:
                current_logger.error(f"SFTP Delete: Échec de la suppression de certains enfants de '{remote_path_posix}'. Le dossier n'a pas été supprimé.")
                return False
        except Exception as e_list_rm:
            current_logger.error(f"SFTP Delete: Erreur lors du listage ou de la suppression des enfants de '{remote_path_posix}': {e_list_rm}")
            return False
    elif stat.S_ISREG(item_stat.st_mode):
        # C'est un fichier
        try:
            sftp_client.remove(remote_path_posix)
            current_logger.info(f"SFTP Delete: Fichier '{remote_path_posix}' supprimé avec succès.")
            return True
        except Exception as e_remove_file:
            current_logger.error(f"SFTP Delete: Erreur lors de la suppression du fichier '{remote_path_posix}': {e_remove_file}")
            return False
    else:
        current_logger.warning(f"SFTP Delete: Type d'item inconnu pour '{remote_path_posix}'. Non supprimé.")
        return False
# NOUVELLE FONCTION HELPER (adaptée de ton script)
def _download_sftp_item_recursive_local(sftp_client, remote_item_path_str, local_item_path_obj, current_logger):
    """Télécharge un fichier ou un dossier (récursivement) via SFTP."""
    current_logger.debug(f"SFTP Recursive Download: Tentative pour distant='{remote_item_path_str}', local='{local_item_path_obj}'")
    try:
        item_stat = sftp_client.stat(remote_item_path_str)
    except FileNotFoundError:
        current_logger.error(f"SFTP Erreur: Élément distant {remote_item_path_str} non trouvé.")
        return False
    except Exception as e:
        current_logger.error(f"SFTP Erreur lors de stat sur {remote_item_path_str}: {e}")
        return False

    if stat.S_ISREG(item_stat.st_mode):
        current_logger.info(f"Téléchargement du fichier: {remote_item_path_str} -> {local_item_path_obj}")
        try:
            local_item_path_obj.parent.mkdir(parents=True, exist_ok=True)
            sftp_client.get(remote_item_path_str, str(local_item_path_obj))
            return True
        except Exception as e:
            current_logger.error(f"SFTP Erreur lors du get sur {remote_item_path_str}: {e}")
            if local_item_path_obj.exists(): # Nettoyer le fichier partiel
                try: local_item_path_obj.unlink()
                except: pass
            return False
    elif stat.S_ISDIR(item_stat.st_mode):
        current_logger.info(f"Téléchargement du dossier: {remote_item_path_str} -> {local_item_path_obj}")
        try:
            local_item_path_obj.mkdir(parents=True, exist_ok=True)
        except Exception as e_mkdir:
            current_logger.error(f"Impossible de créer le dossier local {local_item_path_obj}: {e_mkdir}")
            return False

        all_success = True
        try:
            for item_name in sftp_client.listdir(remote_item_path_str):
                if item_name in [".", ".."]: continue

                # Construire les chemins en s'assurant que remote_item_path_str est traité comme un dossier
                current_remote_dir_posix = Path(remote_item_path_str).as_posix()
                if not current_remote_dir_posix.endswith('/'):
                    current_remote_dir_posix += '/'

                next_remote_item_path_str = current_remote_dir_posix + item_name
                next_local_item_path_obj = local_item_path_obj / item_name

                if not _download_sftp_item_recursive_local(sftp_client, next_remote_item_path_str, next_local_item_path_obj, current_logger):
                    all_success = False
                    # On pourrait décider d'arrêter ici ou de continuer avec les autres fichiers du dossier
                    # Pour l'instant, on continue mais on marque comme échec partiel/total
        except Exception as e:
            current_logger.error(f"SFTP Erreur lors de listdir sur {remote_item_path_str} ou DL sous-élément: {e}")
            all_success = False
        return all_success
    else:
        current_logger.warning(f"Type d'élément inconnu pour {remote_item_path_str}, non téléchargé.")
        return False

# NOUVELLE FONCTION HELPER (adaptée de ton script)
def _notify_arr_api_local(app_type, local_path_to_import_str, current_logger, app_config):
    """Notifie Sonarr ou Radarr via leur API pour scanner un chemin local."""
    current_logger.info(f"Notification API à '{app_type}' pour importer depuis: '{local_path_to_import_str}'")

    if app_type == "sonarr":
        base_url = app_config.get('SONARR_URL')
        api_key = app_config.get('SONARR_API_KEY')
        command_name = "DownloadedEpisodesScan"
    elif app_type == "radarr":
        base_url = app_config.get('RADARR_URL')
        api_key = app_config.get('RADARR_API_KEY')
        command_name = "DownloadedMoviesScan"
    else:
        current_logger.error(f"Type d'application inconnu pour notification API: {app_type}")
        return False

    if not base_url or not api_key:
        current_logger.error(f"URL ou clé API manquante pour {app_type} dans la configuration.")
        return False

    # Le chemin pour l'API doit être celui que Sonarr/Radarr peuvent atteindre.
    # Si MediaManagerSuite et Sonarr/Radarr sont sur la même machine et peuvent voir X:\, c'est bon.
    # Sinon, il faudrait un path mapping.
    path_for_api = str(local_path_to_import_str).replace('/', '\\') # Assurer backslashes pour Windows

    api_url = f"{base_url.rstrip('/')}/api/v3/command"
    headers = {"X-Api-Key": api_key}
    payload = {
        "name": command_name,
        "path": path_for_api,
        "importMode": "Move" # Sonarr/Radarr devraient le déplacer du staging vers la destination finale
    }
    current_logger.info(f"Appel API ({app_type}) vers {api_url} avec payload: {json.dumps(payload)}")
    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        current_logger.info(f"Commande '{command_name}' envoyée à {app_type}. Réponse: {response.status_code}")
        return True
    except requests.exceptions.Timeout:
        current_logger.error(f"Timeout lors de l'appel API à {app_type} pour {path_for_api}.")
    except requests.exceptions.RequestException as e:
        current_logger.error(f"Erreur API {app_type} pour {path_for_api}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            current_logger.error(f"Détail réponse API: Statut {e.response.status_code} - {e.response.text[:300]}")
    return False
# FIN DES NOUVELLES FONCTIONS HELPER

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
def build_file_tree(directory_path, staging_root_for_relative_path, pending_associations):
    """
    Construit récursivement une structure arborescente pour un dossier donné.
    Chaque nœud contient : name, type ('file' ou 'directory'), path_id (chemin relatif encodé ou simple),
                          size_readable, last_modified, 'association' (si trouvée), et 'children' pour les dossiers.
    """
    tree = []
    try:
        for item_name in sorted(os.listdir(directory_path), key=lambda x: (not os.path.isdir(os.path.join(directory_path, x)), x.lower())):
            item_path = os.path.join(directory_path, item_name)
            relative_item_path = os.path.relpath(item_path, staging_root_for_relative_path)
            path_id_for_url = relative_item_path.replace('\\', '/')

            node = {
                'name': item_name,
                'path_for_actions': path_id_for_url,
                'is_dir': os.path.isdir(item_path),
                'association': pending_associations.get(item_name) # Ajout de l'association si elle existe
            }

            try:
                stat_info = os.stat(item_path)
                node['size_bytes_raw'] = stat_info.st_size
                node['last_modified_timestamp'] = stat_info.st_mtime
                node['last_modified'] = datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

                if node['is_dir']:
                    node['size_readable'] = "N/A (dossier)"
                    node['children'] = build_file_tree(item_path, staging_root_for_relative_path, pending_associations) # Propager pending_associations
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
                if node['is_dir']: node['children'] = []
                node['association'] = None # S'assurer qu'il n'y a pas d'association partielle en cas d'erreur stat

            tree.append(node)
    except OSError as e:
        logger.error(f"Erreur lors de la lecture du dossier {directory_path} pour l'arbre: {e}")
    return tree
# FIN DE LA FONCTION HELPER build_file_tree
# ==============================================================================
# NOUVELLES FONCTIONS HELPER REFACTORISÉES POUR L'IMPORT MMS
# ==============================================================================
def _execute_mms_sonarr_import(item_name_in_staging, # Nom du fichier/dossier dans le staging local (relatif à STAGING_DIR)
                               series_id_target,
                               original_release_folder_name_in_staging, # Nom du dossier de premier niveau dans le staging à nettoyer
                               user_forced_season=None, # Saison fournie par l'utilisateur si discordance
                               torrent_hash_for_status_update=None, # Pour mettre à jour le map
                               is_automated_flow=False): # Pour adapter les logs/retours
    """
    Logique principale pour l'import Sonarr par MediaManagerSuite:
    - Déplace le(s) fichier(s) vidéo du staging vers la destination finale de la série.
    - Déclenche un RescanSeries.
    - Nettoie le dossier de release original dans le staging.
    Retourne un dictionnaire: {"success": bool, "message": str, "manual_required": bool (optionnel)}
    """
    logger = current_app.logger
    log_prefix = f"EXEC_MMS_SONARR (Item:'{item_name_in_staging}', SeriesID:{series_id_target}, CleanupFolder:'{original_release_folder_name_in_staging}', ForcedS:{user_forced_season}, Hash:{torrent_hash_for_status_update}, Auto:{is_automated_flow}): "
    logger.info(f"{log_prefix}Début de l'import MMS.")

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir_str = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    path_of_item_in_staging_abs = (Path(staging_dir_str) / item_name_in_staging).resolve()

    if not path_of_item_in_staging_abs.exists():
        err_msg = f"Item '{item_name_in_staging}' non trouvé à '{path_of_item_in_staging_abs}'."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and is_automated_flow:
            torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_staging_path_missing", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    # Récupérer les détails de la série pour le chemin racine
    series_details_url = f"{sonarr_url.rstrip('/')}/api/v3/series/{series_id_target}"
    series_data, error_series_data = _make_arr_request('GET', series_details_url, sonarr_api_key)
    if error_series_data or not series_data:
        err_msg = f"Impossible de récupérer détails série Sonarr ID {series_id_target}: {error_series_data}"
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and is_automated_flow:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_sonarr_api", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    series_root_folder_path_str = series_data.get('path')
    series_title_from_sonarr = series_data.get('title', 'Série Inconnue')
    if not series_root_folder_path_str:
        err_msg = f"Chemin racine pour série '{series_title_from_sonarr}' (ID {series_id_target}) non trouvé dans Sonarr."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and is_automated_flow:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_sonarr_config", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}
    series_root_path = Path(series_root_folder_path_str)

    video_files_to_process = []
    if path_of_item_in_staging_abs.is_file():
        if any(str(path_of_item_in_staging_abs).lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
            video_files_to_process.append({"path": path_of_item_in_staging_abs, "original_filename": path_of_item_in_staging_abs.name})
        else: # Ne devrait pas arriver si les checks en amont sont bons
            err_msg = f"L'item '{item_name_in_staging}' est un fichier mais pas une vidéo reconnue."
            logger.error(f"{log_prefix}{err_msg}")
            return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}
    elif path_of_item_in_staging_abs.is_dir():
        for root, _, files in os.walk(path_of_item_in_staging_abs):
            for file_name in files:
                if any(file_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
                    video_files_to_process.append({"path": Path(root) / file_name, "original_filename": file_name})
        if not video_files_to_process:
            err_msg = f"Aucun fichier vidéo trouvé dans le dossier '{item_name_in_staging}'."
            logger.error(f"{log_prefix}{err_msg}")
            # Pas besoin de mettre à jour le map ici, car l'item est toujours dans le staging.
            return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}
    else: # Symlink ou autre, non géré
        err_msg = f"Type d'item non supporté dans le staging: {item_name_in_staging}"
        logger.error(f"{log_prefix}{err_msg}")
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    logger.info(f"{log_prefix} Fichiers vidéo à traiter: {[str(f['path']) for f in video_files_to_process]}")
    successful_moves = 0
    failed_moves_details = []
    processed_filenames_for_message = []

    for video_file_info in video_files_to_process:
        current_video_file_path = video_file_info["path"]
        original_video_filename = video_file_info["original_filename"]
        logger.info(f"{log_prefix}Traitement du fichier vidéo: {original_video_filename}")

        season_for_this_file = None
        if user_forced_season is not None:
            season_for_this_file = int(user_forced_season)
            logger.info(f"{log_prefix}Utilisation saison forcée S{season_for_this_file} pour '{original_video_filename}'.")
        else:
            # Tenter de parser depuis le nom de fichier
            s_match = re.search(r'[._\s\[\(-]S(\d{1,3})([E._\s-](\d{1,3}))?', original_video_filename, re.IGNORECASE)
            if s_match:
                try: season_for_this_file = int(s_match.group(1))
                except (ValueError, IndexError): pass

            if season_for_this_file is not None:
                logger.info(f"{log_prefix}Saison S{season_for_this_file} parsée du nom de fichier '{original_video_filename}'.")
            else:
                # Si pas de saison forcée ET pas de parsing possible, on pourrait essayer de demander à Sonarr
                # via manualimport, mais cela complexifie le flux "MMS Import".
                # Pour l'instant, si pas de saison déterminable, c'est un échec pour ce fichier.
                err_msg_file = f"Impossible de déterminer la saison pour '{original_video_filename}' (pas de saison forcée et parsing échoué)."
                logger.error(f"{log_prefix}{err_msg_file}")
                failed_moves_details.append({"file": original_video_filename, "reason": err_msg_file})
                if torrent_hash_for_status_update and is_automated_flow:
                     torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_sonarr_season_undefined", err_msg_file)
                continue # Passer au fichier suivant

        dest_season_folder_name = f"Season {str(season_for_this_file).zfill(2)}"
        dest_season_path_abs = series_root_path / dest_season_folder_name
        dest_file_path_abs = dest_season_path_abs / original_video_filename # Utiliser le nom de fichier original

        logger.info(f"{log_prefix}Déplacement MMS: '{current_video_file_path}' vers '{dest_file_path_abs}'")
        try:
            dest_season_path_abs.mkdir(parents=True, exist_ok=True)
            if current_video_file_path.resolve() != dest_file_path_abs.resolve():
                shutil.move(str(current_video_file_path), str(dest_file_path_abs))
            else:
                logger.warning(f"{log_prefix}Source et destination identiques pour {original_video_filename}.")
            successful_moves += 1
            processed_filenames_for_message.append(original_video_filename)
        except Exception as e_move:
            logger.error(f"{log_prefix}Erreur déplacement '{original_video_filename}': {e_move}. Tentative copie/suppr.")
            try:
                if current_video_file_path.parent.exists(): # S'assurer que le parent source existe toujours
                    shutil.copy2(str(current_video_file_path), str(dest_file_path_abs))
                    os.remove(str(current_video_file_path))
                    successful_moves += 1
                    processed_filenames_for_message.append(original_video_filename)
                else:
                    logger.error(f"{log_prefix}Parent source {current_video_file_path.parent} inexistant. Échec copie/suppression pour {original_video_filename}")
                    failed_moves_details.append({"file": original_video_filename, "reason": f"Erreur de déplacement (parent source manquant): {e_move}"})
            except Exception as e_copy:
                logger.error(f"{log_prefix}Erreur copie/suppr '{original_video_filename}': {e_copy}")
                failed_moves_details.append({"file": original_video_filename, "reason": f"Échec copie/suppression: {e_copy}"})

    if successful_moves == 0 and video_files_to_process: # Si aucun fichier n'a pu être déplacé
        final_err_msg = "Aucun fichier vidéo n'a pu être déplacé."
        if failed_moves_details: final_err_msg += f" Premier échec: {failed_moves_details[0]['reason']}"
        logger.error(f"{log_prefix}{final_err_msg}")
        if torrent_hash_for_status_update and is_automated_flow:
            torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_all_files_failed_move", final_err_msg)
        return {"success": False, "message": final_err_msg, "manual_required": True if is_automated_flow else False}

    # Nettoyage du dossier de release original dans le staging
    path_to_cleanup_abs = (Path(staging_dir_str) / original_release_folder_name_in_staging).resolve()
    if path_to_cleanup_abs.exists() and path_to_cleanup_abs.is_dir():
        logger.info(f"{log_prefix}Nettoyage du dossier de staging: {path_to_cleanup_abs}")
        time.sleep(1)
        try:
            cleanup_staging_subfolder_recursively(str(path_to_cleanup_abs), staging_dir_str, orphan_exts)
        except Exception as e_cleanup:
            logger.error(f"{log_prefix}Erreur lors du nettoyage de {path_to_cleanup_abs}: {e_cleanup}")
    else:
        logger.warning(f"{log_prefix}Dossier à nettoyer '{path_to_cleanup_abs}' (depuis '{original_release_folder_name_in_staging}') non trouvé ou n'est pas un dossier.")

    # Rescan Sonarr
    rescan_payload = {"name": "RescanSeries", "seriesId": series_id_target}
    command_url = f"{sonarr_url.rstrip('/')}/api/v3/command"
    _, error_rescan = _make_arr_request('POST', command_url, sonarr_api_key, json_data=rescan_payload)

    final_message = f"{successful_moves} fichier(s) pour '{series_title_from_sonarr}' déplacé(s) par MMS."
    if processed_filenames_for_message:
        final_message += f" Fichiers: {', '.join(processed_filenames_for_message[:3])}{'...' if len(processed_filenames_for_message) > 3 else ''}."
    if failed_moves_details:
        final_message += f" {len(failed_moves_details)} fichier(s) ont échoué (voir logs)."

    if error_rescan:
        final_message += f" Échec du Rescan Sonarr: {error_rescan}."
        logger.warning(f"{log_prefix}Rescan Sonarr échoué: {error_rescan}")
    else:
        final_message += " Rescan Sonarr initié."
        logger.info(f"{log_prefix}Rescan Sonarr initié pour série ID {series_id_target}.")

    if torrent_hash_for_status_update and is_automated_flow:
        current_status_update_map = "imported_by_mms" if not failed_moves_details else "imported_partial_mms_error"
        torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, current_status_update_map, final_message)
        if not failed_moves_details and current_app.config.get('AUTO_REMOVE_SUCCESSFUL_FROM_MAP', True):
           if torrent_map_manager.remove_torrent_from_map(torrent_hash_for_status_update):
               logger.info(f"{log_prefix} Association pour hash {torrent_hash_for_status_update} supprimée après import MMS réussi.")

    return {"success": True if not failed_moves_details else False,
            "message": final_message,
            "manual_required": bool(failed_moves_details) if is_automated_flow else False }


def _execute_mms_radarr_import(item_name_in_staging, # Nom du fichier/dossier dans le staging local (relatif à STAGING_DIR)
                               movie_id_target,
                               original_release_folder_name_in_staging, # Nom du dossier de premier niveau dans le staging à nettoyer
                               torrent_hash_for_status_update=None, # Pour mettre à jour le map
                               is_automated_flow=False): # Pour adapter les logs/retours
    """
    Logique principale pour l'import Radarr par MediaManagerSuite:
    - Déplace le fichier vidéo principal du staging vers la destination finale du film.
    - Déclenche un RescanMovie.
    - Nettoie le dossier de release original dans le staging.
    Retourne un dictionnaire: {"success": bool, "message": str, "manual_required": bool (optionnel)}
    """
    logger = current_app.logger
    log_prefix = f"EXEC_MMS_RADARR (Item:'{item_name_in_staging}', MovieID:{movie_id_target}, CleanupFolder:'{original_release_folder_name_in_staging}', Hash:{torrent_hash_for_status_update}, Auto:{is_automated_flow}): "
    logger.info(f"{log_prefix}Début de l'import MMS.")

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir_str = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    path_of_item_in_staging_abs = (Path(staging_dir_str) / item_name_in_staging).resolve()

    if not path_of_item_in_staging_abs.exists():
        err_msg = f"Item '{item_name_in_staging}' non trouvé à '{path_of_item_in_staging_abs}'."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and is_automated_flow:
            torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_staging_path_missing", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    # Identifier le fichier vidéo principal
    main_video_file_abs_path_in_staging = None
    original_filename_of_video = None
    if path_of_item_in_staging_abs.is_file():
        if any(str(path_of_item_in_staging_abs).lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
            main_video_file_abs_path_in_staging = path_of_item_in_staging_abs
            original_filename_of_video = path_of_item_in_staging_abs.name
        else:
            err_msg = f"L'item '{item_name_in_staging}' est un fichier mais pas une vidéo reconnue."
            logger.error(f"{log_prefix}{err_msg}")
            return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}
    elif path_of_item_in_staging_abs.is_dir():
        for root, _, files in os.walk(path_of_item_in_staging_abs):
            for file_name in files:
                if any(file_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
                    main_video_file_abs_path_in_staging = Path(root) / file_name
                    original_filename_of_video = file_name # Utiliser le nom du fichier trouvé
                    break
            if main_video_file_abs_path_in_staging: break
        if not main_video_file_abs_path_in_staging:
            err_msg = f"Aucun fichier vidéo trouvé dans le dossier '{item_name_in_staging}'."
            logger.error(f"{log_prefix}{err_msg}")
            return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}
    else:
        err_msg = f"Type d'item non supporté dans le staging: {item_name_in_staging}"
        logger.error(f"{log_prefix}{err_msg}")
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    logger.info(f"{log_prefix}Fichier vidéo principal identifié: {main_video_file_abs_path_in_staging} (nom original: {original_filename_of_video})")

    # Récupérer les détails du film pour le chemin racine
    movie_details_url = f"{radarr_url.rstrip('/')}/api/v3/movie/{movie_id_target}"
    movie_data, error_movie_data = _make_arr_request('GET', movie_details_url, radarr_api_key)
    if error_movie_data or not movie_data or not isinstance(movie_data, dict):
        err_msg = f"Erreur détails film Radarr ID {movie_id_target}: {error_movie_data or 'Pas de données Radarr'}"
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and is_automated_flow:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_radarr_api", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    movie_folder_path_from_radarr_api = movie_data.get('path')
    movie_title = movie_data.get('title', 'Film Inconnu')
    if not movie_folder_path_from_radarr_api:
        err_msg = f"Chemin ('path') manquant pour film ID {movie_id_target} ('{movie_title}') dans Radarr."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and is_automated_flow:
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_radarr_config", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    destination_movie_folder_abs = Path(movie_folder_path_from_radarr_api).resolve()
    destination_video_file_abs = destination_movie_folder_abs / original_filename_of_video

    logger.info(f"{log_prefix}Déplacement MMS: '{main_video_file_abs_path_in_staging}' vers '{destination_video_file_abs}'")
    imported_successfully = False
    try:
        destination_movie_folder_abs.mkdir(parents=True, exist_ok=True)
        if main_video_file_abs_path_in_staging.resolve() != destination_video_file_abs.resolve():
            shutil.move(str(main_video_file_abs_path_in_staging), str(destination_video_file_abs))
        else:
            logger.warning(f"{log_prefix}Source et destination identiques: {main_video_file_abs_path_in_staging}")
        imported_successfully = True
    except Exception as e_move:
        logger.error(f"{log_prefix}Erreur move '{original_filename_of_video}': {e_move}. Tentative copie/suppr.")
        try:
            if main_video_file_abs_path_in_staging.parent.exists():
                shutil.copy2(str(main_video_file_abs_path_in_staging), str(destination_video_file_abs))
                os.remove(str(main_video_file_abs_path_in_staging))
                imported_successfully = True
            else: # Source parent does not exist
                logger.error(f"{log_prefix}Parent du fichier source {main_video_file_abs_path_in_staging.parent} n'existe pas. Abandon copie/suppr.")
                # Pas besoin de mettre à jour le map ici, l'erreur sera retournée.
        except Exception as e_copy:
            err_msg = f"Échec du déplacement (copie/suppression) du fichier '{original_filename_of_video}': {e_copy}"
            logger.error(f"{log_prefix}{err_msg}")
            if torrent_hash_for_status_update and is_automated_flow:
                 torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_file_move", err_msg)
            return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    if not imported_successfully: # Si on arrive ici, c'est que le fallback a échoué ou n'a pas été tenté
        err_msg = f"Échec inattendu du déplacement de '{original_filename_of_video}' (après tentatives)."
        logger.error(f"{log_prefix}{err_msg}")
        if torrent_hash_for_status_update and is_automated_flow: # Mettre à jour le map seulement si le hash est fourni
             torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "error_mms_file_move_final", err_msg)
        return {"success": False, "message": err_msg, "manual_required": True if is_automated_flow else False}

    # Nettoyage du dossier de release original dans le staging
    path_to_cleanup_abs = (Path(staging_dir_str) / original_release_folder_name_in_staging).resolve()
    if path_to_cleanup_abs.exists() and path_to_cleanup_abs.is_dir():
        logger.info(f"{log_prefix}Nettoyage du dossier de staging: {path_to_cleanup_abs}")
        time.sleep(1)
        try:
            cleanup_staging_subfolder_recursively(str(path_to_cleanup_abs), staging_dir_str, orphan_exts)
        except Exception as e_cleanup:
            logger.error(f"{log_prefix}Erreur lors du nettoyage de {path_to_cleanup_abs}: {e_cleanup}")
    else:
         logger.warning(f"{log_prefix}Dossier à nettoyer '{path_to_cleanup_abs}' (depuis '{original_release_folder_name_in_staging}') non trouvé ou n'est pas un dossier.")

    # Rescan Radarr
    rescan_payload = {"name": "RescanMovie", "movieId": int(movie_id_target)} # movieId doit être un int
    command_url = f"{radarr_url.rstrip('/')}/api/v3/command"
    _, error_rescan = _make_arr_request('POST', command_url, radarr_api_key, json_data=rescan_payload)

    final_message = f"Fichier pour '{movie_title}' déplacé par MMS."
    if error_rescan:
        final_message += f" Échec du Rescan Radarr: {error_rescan}."
        logger.warning(f"{log_prefix}Rescan Radarr échoué: {error_rescan}")
    else:
        final_message += " Rescan Radarr initié."
        logger.info(f"{log_prefix}Rescan Radarr initié pour movie ID {movie_id_target}.")

    if torrent_hash_for_status_update and is_automated_flow:
        torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, "imported_by_mms", final_message)
        if current_app.config.get('AUTO_REMOVE_SUCCESSFUL_FROM_MAP', True):
            if torrent_map_manager.remove_torrent_from_map(torrent_hash_for_status_update):
                logger.info(f"{log_prefix} Association pour hash {torrent_hash_for_status_update} supprimée après import MMS réussi.")

    return {"success": True, "message": final_message, "manual_required": False}

# FIN DES NOUVELLES FONCTIONS HELPER REFACTORISÉES
# ==============================================================================

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
@login_required
def index():
    logger = current_app.logger # Obtenir le logger
    staging_dir = current_app.config.get('STAGING_DIR')
    if not staging_dir or not os.path.isdir(staging_dir):
        flash(f"Le dossier de staging '{staging_dir}' n'est pas configuré ou n'existe pas/n'est pas un dossier.", 'danger')
        # Toujours essayer de charger les items en attente même si le staging est problématique
        # return render_template('seedbox_ui/index.html', items_tree=[]) # Ancien retour

    # --- Items du Staging Local (logique existante) ---
    # Récupérer les associations en attente pour l'affichage DANS l'arbre du staging
    all_torrents_by_hash_for_staging_tree = torrent_map_manager.get_all_torrents_in_map()
    associations_by_release_name_for_staging_tree = {}
    if isinstance(all_torrents_by_hash_for_staging_tree, dict):
        for torrent_hash, assoc_data in all_torrents_by_hash_for_staging_tree.items():
            release_name = assoc_data.get('release_name')
            if release_name:
                # Pour l'arbre, on peut enrichir avec le hash si besoin
                assoc_data_for_tree = assoc_data.copy()
                assoc_data_for_tree['torrent_hash'] = torrent_hash
                associations_by_release_name_for_staging_tree[release_name] = assoc_data_for_tree
    logger.debug(f"Index: Associations (pour arbre staging) par release_name: {associations_by_release_name_for_staging_tree}")

    items_tree_data = []
    if staging_dir and os.path.isdir(staging_dir):
        logger.info(f"Index: Construction de l'arborescence pour le dossier de staging: {staging_dir}")
        items_tree_data = build_file_tree(staging_dir, staging_dir, associations_by_release_name_for_staging_tree)
    # --- Fin Items du Staging Local ---


    # --- NOUVEAU: Items en Attente/Erreur depuis pending_torrents_map.json ---
    all_pending_torrents = torrent_map_manager.get_all_torrents_in_map()
    items_requiring_attention = []
    if isinstance(all_pending_torrents, dict): # S'assurer que c'est un dictionnaire
        for torrent_hash, data in all_pending_torrents.items():
            status = data.get("status", "unknown")
            # Définir les statuts qui nécessitent une attention.
            # 'imported_by_mms' ou 'removed_after_success' (si vous l'implémentez) sont OK.
            # Les autres pourraient nécessiter une attention.
            # Vous pouvez affiner cette condition.
            if not status.startswith("imported_") and not status.startswith("removed_"):
                item_info = data.copy() # Copier pour ne pas modifier l'original en ajoutant le hash
                item_info['torrent_hash'] = torrent_hash # Ajouter le hash pour les actions
                # Vérifier si l'item est physiquement dans le staging (pour l'action "Réessayer")
                if staging_dir and item_info.get('release_name'):
                    item_info['is_in_staging'] = (Path(staging_dir) / item_info['release_name']).exists()
                else:
                    item_info['is_in_staging'] = False
                items_requiring_attention.append(item_info)

    # Trier les items par date de mise à jour (plus récent en premier) ou par statut
    if items_requiring_attention:
        try:
            items_requiring_attention.sort(key=lambda x: x.get('updated_at', x.get('added_at', '')), reverse=True)
        except Exception as e_sort:
             logger.warning(f"Index: Erreur lors du tri des items_requiring_attention: {e_sort}")

    logger.debug(f"Index: Items nécessitant attention: {len(items_requiring_attention)}")
    # --- Fin Items en Attente/Erreur ---

    sonarr_configured = bool(current_app.config.get('SONARR_URL') and current_app.config.get('SONARR_API_KEY'))
    radarr_configured = bool(current_app.config.get('RADARR_URL') and current_app.config.get('RADARR_API_KEY'))

    return render_template('seedbox_ui/index.html',
                           items_tree=items_tree_data,
                           can_scan_sonarr=sonarr_configured,
                           can_scan_radarr=radarr_configured,
                           staging_dir_display=staging_dir,
                           items_requiring_attention=items_requiring_attention) # Passer la nouvelle liste au template

@seedbox_ui_bp.route('/delete/<path:item_name>', methods=['POST'])
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
# ==============================================================================
# ROUTES API POUR RÉCUPÉRER LES CONFIGURATIONS DE SONARR (Root Folders, Profiles)
# ==============================================================================

@seedbox_ui_bp.route('/api/get-sonarr-rootfolders', methods=['GET'])
@login_required
def get_sonarr_rootfolders_api():
    logger = current_app.logger
    logger.info("API: Demande de récupération des dossiers racine Sonarr.")

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')

    if not sonarr_url or not sonarr_api_key:
        logger.error("API Get Sonarr Root Folders: Configuration Sonarr manquante.")
        return jsonify({"error": "Sonarr non configuré dans l'application."}), 500

    api_endpoint = f"{sonarr_url.rstrip('/')}/api/v3/rootfolder"

    rootfolders_data, error_msg = _make_arr_request('GET', api_endpoint, sonarr_api_key)

    if error_msg:
        logger.error(f"API Get Sonarr Root Folders: Erreur lors de l'appel à Sonarr: {error_msg}")
        return jsonify({"error": f"Erreur Sonarr: {error_msg}"}), 502 # Bad Gateway ou erreur de l'API distante

    if rootfolders_data and isinstance(rootfolders_data, list):
        logger.info(f"API Get Sonarr Root Folders: {len(rootfolders_data)} dossier(s) racine trouvé(s).")
        # On ne retourne que les champs utiles pour le frontend : id (non utilisé pour l'ajout) et path
        # L'API Sonarr pour /rootfolder retourne une liste d'objets comme :
        # [ { "id": 1, "path": "/mnt/series", "freeSpace": 123456, ... }, ... ]
        # Pour l'ajout d'une série, Sonarr attend le `rootFolderPath` (le chemin).
        formatted_folders = [{"id": folder.get("id"), "path": folder.get("path")} for folder in rootfolders_data if folder.get("path")]
        return jsonify(formatted_folders), 200
    else:
        logger.warning("API Get Sonarr Root Folders: Aucune donnée ou format inattendu reçu de Sonarr pour les dossiers racine.")
        return jsonify([]), 200 # Retourner une liste vide si rien n'est trouvé ou erreur de format


@seedbox_ui_bp.route('/api/get-sonarr-qualityprofiles', methods=['GET'])
@login_required
def get_sonarr_qualityprofiles_api():
    logger = current_app.logger
    logger.info("API: Demande de récupération des profils de qualité Sonarr.")

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')

    if not sonarr_url or not sonarr_api_key:
        logger.error("API Get Sonarr Quality Profiles: Configuration Sonarr manquante.")
        return jsonify({"error": "Sonarr non configuré dans l'application."}), 500

    api_endpoint = f"{sonarr_url.rstrip('/')}/api/v3/qualityprofile"

    profiles_data, error_msg = _make_arr_request('GET', api_endpoint, sonarr_api_key)

    if error_msg:
        logger.error(f"API Get Sonarr Quality Profiles: Erreur lors de l'appel à Sonarr: {error_msg}")
        return jsonify({"error": f"Erreur Sonarr: {error_msg}"}), 502

    if profiles_data and isinstance(profiles_data, list):
        logger.info(f"API Get Sonarr Quality Profiles: {len(profiles_data)} profil(s) de qualité trouvé(s).")
        # L'API Sonarr /qualityprofile retourne une liste d'objets comme :
        # [ { "id": 1, "name": "Any", ... }, { "id": 2, "name": "HD-1080p", ... } ]
        # On a besoin de 'id' et 'name' pour le select.
        formatted_profiles = [{"id": profile.get("id"), "name": profile.get("name")} for profile in profiles_data if profile.get("id") is not None and profile.get("name")]
        return jsonify(formatted_profiles), 200
    else:
        logger.warning("API Get Sonarr Quality Profiles: Aucune donnée ou format inattendu reçu de Sonarr pour les profils.")
        return jsonify([]), 200
# ==============================================================================
# ROUTES API POUR RÉCUPÉRER LES CONFIGURATIONS DE RADARR (Root Folders, Profiles)
# ==============================================================================

@seedbox_ui_bp.route('/api/get-radarr-rootfolders', methods=['GET'])
@login_required
def get_radarr_rootfolders_api():
    logger = current_app.logger
    logger.info("API: Demande de récupération des dossiers racine Radarr.")

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')

    if not radarr_url or not radarr_api_key:
        logger.error("API Get Radarr Root Folders: Configuration Radarr manquante.")
        return jsonify({"error": "Radarr non configuré dans l'application."}), 500

    api_endpoint = f"{radarr_url.rstrip('/')}/api/v3/rootfolder"

    # Utilisation de votre helper _make_arr_request
    rootfolders_data, error_msg = _make_arr_request('GET', api_endpoint, radarr_api_key)

    if error_msg:
        logger.error(f"API Get Radarr Root Folders: Erreur lors de l'appel à Radarr: {error_msg}")
        return jsonify({"error": f"Erreur Radarr: {error_msg}"}), 502 # Bad Gateway ou erreur de l'API distante

    if rootfolders_data and isinstance(rootfolders_data, list):
        logger.info(f"API Get Radarr Root Folders: {len(rootfolders_data)} dossier(s) racine trouvé(s).")
        # Radarr retourne une liste d'objets avec 'path' et 'id'.
        # Pour l'ajout de film, Radarr attend le 'rootFolderPath' (le chemin).
        formatted_folders = []
        for folder in rootfolders_data:
            if folder.get("path"): # S'assurer que le chemin existe
                # Radarr peut avoir des 'unmappedFolders', on ne les veut pas forcément.
                # Un dossier racine valide a généralement un ID et un chemin.
                # On peut ajouter plus de filtres si nécessaire (ex: folder.get('accessible') is True)
                formatted_folders.append({"id": folder.get("id"), "path": folder.get("path")})
        return jsonify(formatted_folders), 200
    else:
        logger.warning("API Get Radarr Root Folders: Aucune donnée ou format inattendu reçu de Radarr pour les dossiers racine.")
        return jsonify([]), 200


@seedbox_ui_bp.route('/api/get-radarr-qualityprofiles', methods=['GET'])
@login_required
def get_radarr_qualityprofiles_api():
    logger = current_app.logger
    logger.info("API: Demande de récupération des profils de qualité Radarr.")

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')

    if not radarr_url or not radarr_api_key:
        logger.error("API Get Radarr Quality Profiles: Configuration Radarr manquante.")
        return jsonify({"error": "Radarr non configuré dans l'application."}), 500

    api_endpoint = f"{radarr_url.rstrip('/')}/api/v3/qualityprofile" # Endpoint identique à Sonarr pour les profils

    profiles_data, error_msg = _make_arr_request('GET', api_endpoint, radarr_api_key)

    if error_msg:
        logger.error(f"API Get Radarr Quality Profiles: Erreur lors de l'appel à Radarr: {error_msg}")
        return jsonify({"error": f"Erreur Radarr: {error_msg}"}), 502

    if profiles_data and isinstance(profiles_data, list):
        logger.info(f"API Get Radarr Quality Profiles: {len(profiles_data)} profil(s) de qualité trouvé(s).")
        # Radarr retourne une liste d'objets avec 'id' et 'name'.
        formatted_profiles = []
        for profile in profiles_data:
            if profile.get("id") is not None and profile.get("name"):
                formatted_profiles.append({"id": profile.get("id"), "name": profile.get("name")})
        return jsonify(formatted_profiles), 200
    else:
        logger.warning("API Get Radarr Quality Profiles: Aucune donnée ou format inattendu reçu de Radarr pour les profils.")
        return jsonify([]), 200

# ------------------------------------------------------------------------------
# ROUTE POUR AFFICHER LE CONTENU D'UN DOSSIER DISTANT DE LA SEEDBOX
# ------------------------------------------------------------------------------

@seedbox_ui_bp.route('/remote-view/<app_type_target>')
@login_required
def remote_seedbox_view(app_type_target):
    logger.info(f"Demande d'affichage (arbre) du contenu distant seedbox pour: {app_type_target}")

    sftp_host = current_app.config.get('SEEDBOX_SFTP_HOST')
    sftp_port = current_app.config.get('SEEDBOX_SFTP_PORT')
    sftp_user = current_app.config.get('SEEDBOX_SFTP_USER')
    sftp_password = current_app.config.get('SEEDBOX_SFTP_PASSWORD')
    local_staging_dir_str = current_app.config.get('STAGING_DIR')
    local_staging_dir_for_check = Path(local_staging_dir_str) if local_staging_dir_str else None

    remote_path_to_list_root = None
    page_title = "Contenu Seedbox Distant"
    allow_sftp_delete = False
    # 'view_type' pour aider le template à savoir quel type de contenu il affiche (terminé vs travail)
    view_type = "unknown"

    if app_type_target == 'sonarr':
        remote_path_to_list_root = current_app.config.get('SEEDBOX_SONARR_FINISHED_PATH')
        page_title = "Seedbox - Sonarr (Terminés)"
        view_type = "finished"
    elif app_type_target == 'radarr':
        remote_path_to_list_root = current_app.config.get('SEEDBOX_RADARR_FINISHED_PATH')
        page_title = "Seedbox - Radarr (Terminés)"
        view_type = "finished"
    elif app_type_target == 'sonarr_working':
        remote_path_to_list_root = current_app.config.get('SEEDBOX_SONARR_WORKING_PATH')
        page_title = "Seedbox - Sonarr (Dossier de Travail)"
        allow_sftp_delete = True
        view_type = "working"
    elif app_type_target == 'radarr_working':
        remote_path_to_list_root = current_app.config.get('SEEDBOX_RADARR_WORKING_PATH')
        page_title = "Seedbox - Radarr (Dossier de Travail)"
        allow_sftp_delete = True
        view_type = "working"
    else:
        flash(f"Type de vue distante inconnu: {app_type_target}", "danger")
        return redirect(url_for('seedbox_ui.index'))

    if not all([sftp_host, sftp_port, sftp_user, sftp_password, remote_path_to_list_root]):
        error_msg = f"Config SFTP ou chemin distant pour '{app_type_target}' manquante. Vérifiez les logs de démarrage et les variables d'environnement."
        flash(error_msg, "danger")
        logger.error(f"remote_seedbox_view: {error_msg}")
        return render_template('seedbox_ui/remote_seedbox_list.html',
                               items_tree=[], # Doit être items_tree maintenant
                               target_root_folder_path=remote_path_to_list_root or "Chemin non configuré",
                               page_title=page_title,
                               app_type=app_type_target,
                               allow_sftp_delete=allow_sftp_delete,
                               view_type=view_type,
                               error_message=error_msg)

    if not local_staging_dir_for_check or not local_staging_dir_for_check.is_dir():
        error_msg = f"Dossier de staging local ({local_staging_dir_str}) non configuré/valide."
        # ... (même retour d'erreur que ci-dessus) ...
        flash(error_msg, "danger")
        logger.error(f"remote_seedbox_view: {error_msg}")
        return render_template('seedbox_ui/remote_seedbox_list.html', items_tree=[],target_root_folder_path=remote_path_to_list_root, page_title=page_title,app_type=app_type_target,allow_sftp_delete=allow_sftp_delete,view_type=view_type,error_message=error_msg)

    # Connexion SFTP et construction de l'arbre
    sftp_client = None
    transport = None
    remote_items_tree_data = []
    error_message_display_template = None

    try:
        transport = paramiko.Transport((sftp_host, int(sftp_port)))
        transport.set_keepalive(60)
        transport.connect(username=sftp_user, password=sftp_password)
        sftp_client = paramiko.SFTPClient.from_transport(transport)
        logger.info(f"SFTP (remote_seedbox_view): Connecté à {sftp_host}.")

        remote_items_tree_data = sftp_build_remote_file_tree(
            sftp_client,
            Path(remote_path_to_list_root).as_posix(), # Chemin racine de départ pour l'arbre
            local_staging_dir_for_check,
            Path(remote_path_to_list_root).as_posix() # Base pour la vérification is_in_local_staging des items de 1er niveau
        )
        if remote_items_tree_data is None: # sftp_build_remote_file_tree peut retourner None en cas d'erreur majeure
             error_message_display_template = f"Erreur lors de la construction de l'arbre pour '{remote_path_to_list_root}'. Vérifiez les logs."
             remote_items_tree_data = [] # S'assurer que c'est une liste pour le template

    except paramiko.ssh_exception.AuthenticationException as e_auth:
        logger.error(f"SFTP (remote_seedbox_view): Erreur d'authentification: {e_auth}")
        error_message_display_template = "Erreur d'authentification SFTP."
    except Exception as e_conn:
        logger.error(f"SFTP (remote_seedbox_view): Erreur de connexion ou autre: {e_conn}", exc_info=True)
        error_message_display_template = f"Erreur de connexion SFTP: {e_conn}"
    finally:
        if sftp_client: sftp_client.close()
        if transport: transport.close()
        logger.debug("SFTP (remote_seedbox_view): Connexion fermée.")

    if error_message_display_template and not remote_items_tree_data: # Si erreur et pas d'items
        flash(error_message_display_template, "danger")

    return render_template('seedbox_ui/remote_seedbox_list.html',
                           items_tree=remote_items_tree_data, # Nouvelle variable
                           target_root_folder_path=remote_path_to_list_root, # Chemin racine scanné
                           app_type=app_type_target,
                           page_title=page_title,
                           allow_sftp_delete=allow_sftp_delete,
                           view_type=view_type, # Pour savoir si on est en mode "Terminés" ou "Travail"
                           error_message=error_message_display_template)
# ------------------------------------------------------------------------------
# FIN ROUTE POUR AFFICHER LE CONTENU D'UN DOSSIER DISTANT DE LA SEEDBOX
# ------------------------------------------------------------------------------
# ROUTE POUR LE RAPATRIEMENT SFTP MANUEL
#-------------------------------------------------------------------------------
@seedbox_ui_bp.route('/manual-sftp-download', methods=['POST'])
@login_required
def manual_sftp_download_action():
    data = request.get_json()
    remote_path_to_download_posix = data.get('remote_path')
    app_type_target_from_js = data.get('app_type') # Récupérer app_type ici

    logger.info(f"Demande de rapatriement manuel SFTP pour: {remote_path_to_download_posix} (type: {app_type_target_from_js})")

    sftp_host = current_app.config.get('SEEDBOX_SFTP_HOST')
    sftp_port = current_app.config.get('SEEDBOX_SFTP_PORT')
    sftp_user = current_app.config.get('SEEDBOX_SFTP_USER')
    sftp_password = current_app.config.get('SEEDBOX_SFTP_PASSWORD')
    local_staging_dir_pathobj = Path(current_app.config.get('STAGING_DIR'))
    processed_log_file_str = current_app.config.get('PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT') # Récupérer une seule fois

    if not all([remote_path_to_download_posix, app_type_target_from_js, sftp_host, sftp_port, sftp_user, sftp_password, local_staging_dir_pathobj]):
        logger.error("manual_sftp_download_action: Configuration SFTP, chemin distant ou type d'app manquant.")
        return jsonify({"success": False, "error": "Configuration manquante pour le rapatriement."}), 400

    sftp_client = None
    transport = None
    item_basename = Path(remote_path_to_download_posix).name
    local_destination_for_item_pathobj = local_staging_dir_pathobj / item_basename

    try:
        transport = paramiko.Transport((sftp_host, int(sftp_port)))
        transport.set_keepalive(60)
        transport.connect(username=sftp_user, password=sftp_password)
        sftp_client = paramiko.SFTPClient.from_transport(transport)
        logger.info(f"SFTP (manual download): Connecté à {sftp_host}.")

        logger.info(f"SFTP (manual download): Appel de _download_sftp_item_recursive_local pour '{remote_path_to_download_posix}' vers '{local_destination_for_item_pathobj}'")
        success_download = _download_sftp_item_recursive_local(sftp_client, remote_path_to_download_posix, local_destination_for_item_pathobj, logger)

        if success_download:
            logger.info(f"SFTP (manual download): Téléchargement de '{item_basename}' réussi vers le staging local '{local_destination_for_item_pathobj}'.")

            # --- MISE À JOUR DE processed_sftp_items.json ---
            if processed_log_file_str: # Vérifier si la config du chemin du log est présente
                processed_log_file = Path(processed_log_file_str)
                try:
                    path_obj_remote = Path(remote_path_to_download_posix)
                    item_name_on_seedbox = path_obj_remote.name

                    base_scan_folder_name_on_seedbox = None
                    # Utiliser app_type_target_from_js qui est défini au début de la fonction
                    if app_type_target_from_js == 'sonarr':
                        config_path_str = current_app.config.get('SEEDBOX_SONARR_FINISHED_PATH')
                        if config_path_str: base_scan_folder_name_on_seedbox = Path(config_path_str).name
                    elif app_type_target_from_js == 'radarr':
                        config_path_str = current_app.config.get('SEEDBOX_RADARR_FINISHED_PATH')
                        if config_path_str: base_scan_folder_name_on_seedbox = Path(config_path_str).name
                    elif app_type_target_from_js == 'sonarr_working':
                        config_path_str = current_app.config.get('SEEDBOX_SONARR_WORKING_PATH')
                        if config_path_str: base_scan_folder_name_on_seedbox = Path(config_path_str).name
                    elif app_type_target_from_js == 'radarr_working':
                        config_path_str = current_app.config.get('SEEDBOX_RADARR_WORKING_PATH')
                        if config_path_str: base_scan_folder_name_on_seedbox = Path(config_path_str).name

                    if base_scan_folder_name_on_seedbox:
                        processed_item_identifier_for_log = f"{base_scan_folder_name_on_seedbox}/{item_name_on_seedbox}"
                        logger.info(f"Identifiant pour le log des items traités: '{processed_item_identifier_for_log}'")

                        current_processed_set = set()
                        if processed_log_file.exists() and processed_log_file.stat().st_size > 0:
                            try:
                                with open(processed_log_file, 'r', encoding='utf-8') as f_log_read:
                                    data_log = json.load(f_log_read)
                                    if isinstance(data_log, list):
                                        current_processed_set = set(data_log)
                                    else:
                                        logger.warning(f"Le fichier {processed_log_file} ne contient pas une liste. Il sera écrasé.")
                                        current_processed_set = set()
                            except json.JSONDecodeError:
                                logger.error(f"Erreur de décodage JSON dans {processed_log_file}. Le fichier sera écrasé.")
                                current_processed_set = set()
                            except Exception as e_read_log:
                                logger.error(f"Erreur lecture de {processed_log_file} pour mise à jour: {e_read_log}. Tentative d'écrasement.")
                                current_processed_set = set()

                        if processed_item_identifier_for_log not in current_processed_set:
                            current_processed_set.add(processed_item_identifier_for_log)
                            try:
                                processed_log_file.parent.mkdir(parents=True, exist_ok=True)
                                with open(processed_log_file, 'w', encoding='utf-8') as f_log_write:
                                    json.dump(sorted(list(current_processed_set)), f_log_write, indent=4)
                                logger.info(f"'{processed_item_identifier_for_log}' ajouté au fichier des items traités: {processed_log_file}.")
                            except Exception as e_write_log:
                                logger.error(f"Erreur lors de l'écriture dans {processed_log_file} après ajout de '{processed_item_identifier_for_log}': {e_write_log}")
                        else:
                            logger.info(f"'{processed_item_identifier_for_log}' était déjà présent dans {processed_log_file}.")
                    else:
                        logger.warning(f"Impossible de déterminer le nom du dossier de base pour l'identifiant de log (app_type: '{app_type_target_from_js}' non reconnu ou chemin de config manquant). L'item ne sera pas ajouté au log des traités.")
                except Exception as e_proc_log:
                    logger.error(f"Erreur lors de la gestion du log des items traités ({processed_log_file_str}): {e_proc_log}", exc_info=True)
            else:
                logger.warning("Chemin vers PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT non configuré. Le log des items traités ne sera pas mis à jour.")
            # --- FIN DE LA MISE À JOUR ---

            msg = f"'{item_basename}' a été rapatrié avec succès vers votre dossier de staging local ({local_destination_for_item_pathobj}). Vous pouvez maintenant le gérer depuis la vue du Staging Local."
            # flash(msg, "success") # Le JavaScript affiche déjà un message. Le flash est redondant pour les appels AJAX.
            return jsonify({"success": True, "message": msg})
        else:
            logger.error(f"SFTP (manual download): Échec du téléchargement SFTP de '{remote_path_to_download_posix}'.")
            if local_destination_for_item_pathobj.exists():
                is_empty_dir = local_destination_for_item_pathobj.is_dir() and not any(local_destination_for_item_pathobj.iterdir())
                is_empty_file = local_destination_for_item_pathobj.is_file() and local_destination_for_item_pathobj.stat().st_size == 0
                if is_empty_dir or is_empty_file:
                    try:
                        if is_empty_dir: shutil.rmtree(local_destination_for_item_pathobj)
                        elif is_empty_file: local_destination_for_item_pathobj.unlink()
                        logger.info(f"Nettoyage de la destination partielle {local_destination_for_item_pathobj} effectué après échec DL.")
                    except Exception as e_clean_fail:
                        logger.warning(f"Nettoyage de la destination partielle {local_destination_for_item_pathobj} a échoué: {e_clean_fail}")
            return jsonify({"success": False, "error": f"Échec du téléchargement SFTP de '{item_basename}'."}), 500

    except paramiko.ssh_exception.AuthenticationException as e_auth:
        logger.error(f"SFTP (manual download): Erreur d'authentification: {e_auth}")
        return jsonify({"success": False, "error": "Erreur d'authentification SFTP. Vérifiez vos identifiants."}), 401
    except Exception as e_sftp:
        logger.error(f"SFTP (manual download): Erreur générale SFTP: {e_sftp}", exc_info=True)
        return jsonify({"success": False, "error": f"Erreur SFTP: {type(e_sftp).__name__} - {e_sftp}"}), 500
    finally:
        if sftp_client: sftp_client.close()
        if transport: transport.close()
        logger.debug("SFTP (manual download): Connexion fermée.")

# FIN DE LA FONCTION manual_sftp_download_action
# ------------------------------------------------------------------------------
# NOUVELLE ROUTE POUR "RAPATRIER & TRAITER" (PLACÉE ICI)
# ------------------------------------------------------------------------------
@seedbox_ui_bp.route('/sftp-retrieve-and-process', methods=['POST'])
@login_required
def sftp_retrieve_and_process_action():
    data = request.get_json()
    remote_path_posix = data.get('remote_path')
    # app_type_of_remote_folder is the type of folder on seedbox (sonarr/radarr finished)
    # This helps determine which _handle function to call if no specific target_id is found
    # from pre-association but is provided in the direct POST data.
    app_type_of_remote_folder = data.get('app_type_of_remote_folder')

    # These are IDs provided if user selected a target *during* the "Rapatrier & Mapper" action,
    # not from a pre-existing association made during torrent addition.
    direct_target_series_id = data.get('target_series_id')
    direct_target_movie_id = data.get('target_movie_id')
    user_forced_season = data.get('target_season') # For Sonarr season mismatch resolution

    current_app.logger.info(
        f"SFTP Retrieve & Process: Remote='{remote_path_posix}', "
        f"AppTypeRemoteFolder='{app_type_of_remote_folder}', "
        f"DirectSeriesID='{direct_target_series_id}', DirectMovieID='{direct_target_movie_id}', "
        f"ForcedSeason='{user_forced_season}'"
    )

    # --- Configuration Checks (SFTP, Staging Dir, etc.) ---
    sftp_host = current_app.config.get('SEEDBOX_SFTP_HOST')
    sftp_port = current_app.config.get('SEEDBOX_SFTP_PORT')
    sftp_user = current_app.config.get('SEEDBOX_SFTP_USER')
    sftp_password = current_app.config.get('SEEDBOX_SFTP_PASSWORD')
    local_staging_dir_pathobj = Path(current_app.config.get('STAGING_DIR'))
    # processed_log_file_str = current_app.config.get('PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT') # For marking items for external script

    if not all([sftp_host, sftp_port, sftp_user, sftp_password, local_staging_dir_pathobj]):
        current_app.logger.error("sftp_retrieve_and_process_action: Configuration SFTP or staging_dir manquante.")
        return jsonify({"success": False, "error": "Configuration serveur incomplète pour cette action."}), 500

    if not remote_path_posix or not app_type_of_remote_folder:
        return jsonify({"success": False, "error": "Données POST manquantes (chemin distant ou type d'app du dossier distant)."}), 400

    # If neither direct IDs nor a remote path (for pre-association lookup) is present, it's an issue.
    # However, remote_path_posix is checked above. The logic will try pre-association first.

    item_basename_on_seedbox = Path(remote_path_posix).name
    local_staged_item_path_obj = local_staging_dir_pathobj / item_basename_on_seedbox

    # --- Étape 1: Rapatriement SFTP (unchanged from existing logic) ---
    sftp_client = None; transport = None; success_download = False
    try:
        current_app.logger.debug(f"SFTP R&P: Connexion à {sftp_host}:{sftp_port} avec utilisateur {sftp_user}")
        transport = paramiko.Transport((sftp_host, int(sftp_port)))
        transport.set_keepalive(60)
        transport.connect(username=sftp_user, password=sftp_password)
        sftp_client = paramiko.SFTPClient.from_transport(transport)
        current_app.logger.info(f"SFTP R&P: Connecté à {sftp_host}. Téléchargement de '{remote_path_posix}'.")

        success_download = _download_sftp_item_recursive_local(sftp_client, remote_path_posix, local_staged_item_path_obj, current_app.logger) # Pass logger

        if success_download:
            current_app.logger.info(f"SFTP R&P: Download de '{item_basename_on_seedbox}' réussi vers '{local_staged_item_path_obj}'.")
            # Update processed_sftp_items.json (logic copied & adapted from manual_sftp_download_action)
            processed_log_file_str = current_app.config.get('PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT')
            if processed_log_file_str:
                try:
                    # Determine base_scan_folder_name_on_seedbox based on app_type_of_remote_folder
                    # This assumes app_type_of_remote_folder correctly reflects the *source* folder type (e.g., 'sonarr' for SEEDBOX_SONARR_FINISHED_PATH)
                    path_config_key_map = {
                        'sonarr': 'SEEDBOX_SONARR_FINISHED_PATH',
                        'radarr': 'SEEDBOX_RADARR_FINISHED_PATH',
                        'sonarr_working': 'SEEDBOX_SONARR_WORKING_PATH', # Though R&P usually from finished
                        'radarr_working': 'SEEDBOX_RADARR_WORKING_PATH'  # Though R&P usually from finished
                    }
                    base_folder_config_key = path_config_key_map.get(app_type_of_remote_folder)
                    base_scan_folder_name_on_seedbox = None
                    if base_folder_config_key:
                        config_path_str = current_app.config.get(base_folder_config_key)
                        if config_path_str:
                            base_scan_folder_name_on_seedbox = Path(config_path_str).name

                    if base_scan_folder_name_on_seedbox:
                        processed_item_identifier_for_log = f"{base_scan_folder_name_on_seedbox}/{item_basename_on_seedbox}"
                        # (The rest of the JSON update logic from manual_sftp_download_action)
                        # For brevity, this part is assumed to be correctly implemented here.
                        # It involves reading the JSON, adding the new item, and writing back.
                        current_app.logger.info(f"SFTP R&P: Item '{processed_item_identifier_for_log}' will be marked in processed log.")
                        # Actual log update logic should be here
                        processed_log_file = Path(processed_log_file_str)
                        current_processed_set = set()
                        if processed_log_file.exists() and processed_log_file.stat().st_size > 0:
                            try:
                                with open(processed_log_file, 'r', encoding='utf-8') as f_log_read:
                                    data_log = json.load(f_log_read)
                                    if isinstance(data_log, list):
                                        current_processed_set = set(data_log)
                                    else:
                                        current_app.logger.warning(f"Le fichier {processed_log_file} ne contient pas une liste. Il sera écrasé.")
                            except json.JSONDecodeError:
                                current_app.logger.error(f"Erreur de décodage JSON dans {processed_log_file}. Le fichier sera écrasé.")
                            except Exception as e_read_log:
                                current_app.logger.error(f"Erreur lecture de {processed_log_file} pour mise à jour: {e_read_log}. Tentative d'écrasement.")

                        if processed_item_identifier_for_log not in current_processed_set:
                            current_processed_set.add(processed_item_identifier_for_log)
                            try:
                                processed_log_file.parent.mkdir(parents=True, exist_ok=True)
                                with open(processed_log_file, 'w', encoding='utf-8') as f_log_write:
                                    json.dump(sorted(list(current_processed_set)), f_log_write, indent=4)
                                current_app.logger.info(f"'{processed_item_identifier_for_log}' ajouté au fichier des items traités: {processed_log_file}.")
                            except Exception as e_write_log:
                                current_app.logger.error(f"Erreur lors de l'écriture dans {processed_log_file} après ajout de '{processed_item_identifier_for_log}': {e_write_log}")
                        else:
                            current_app.logger.info(f"'{processed_item_identifier_for_log}' était déjà présent dans {processed_log_file}.")
                    else:
                        current_app.logger.warning(f"SFTP R&P: Could not determine base folder for processed log for app_type '{app_type_of_remote_folder}'.")
                except Exception as e_proc_log:
                    current_app.logger.error(f"SFTP R&P: Error managing processed items log: {e_proc_log}", exc_info=True)
        else:
            current_app.logger.error(f"SFTP R&P: Échec du téléchargement de '{remote_path_posix}'.")
            # Clean up partially downloaded file/folder if empty
            if local_staged_item_path_obj.exists():
                if local_staged_item_path_obj.is_dir() and not any(local_staged_item_path_obj.iterdir()):
                    shutil.rmtree(local_staged_item_path_obj)
                elif local_staged_item_path_obj.is_file() and local_staged_item_path_obj.stat().st_size == 0:
                    local_staged_item_path_obj.unlink()
            return jsonify({"success": False, "error": f"Échec du téléchargement SFTP de '{item_basename_on_seedbox}'."}), 500
    except paramiko.ssh_exception.AuthenticationException as e_auth:
        # ... (error handling as before) ...
        current_app.logger.error(f"SFTP R&P: Erreur d'authentification SFTP: {e_auth}")
        return jsonify({"success": False, "error": "Erreur d'authentification SFTP."}), 401
    except Exception as e_sftp_outer:
        # ... (error handling as before) ...
        current_app.logger.error(f"SFTP R&P: Erreur SFTP ('{remote_path_posix}'): {e_sftp_outer}", exc_info=True)
        return jsonify({"success": False, "error": f"Erreur SFTP lors du téléchargement: {e_sftp_outer}"}), 500
    finally:
        if sftp_client: sftp_client.close()
        if transport: transport.close()
        current_app.logger.debug("SFTP R&P: Connexion SFTP fermée.")

    # --- Étape 2: Traitement de l'item téléchargé ---
    if success_download:
        current_app.logger.info(f"SFTP R&P: Rapatriement terminé. Traitement de '{item_basename_on_seedbox}'...")

        final_result_dict = None
        path_to_cleanup_after_success_abs = str(local_staged_item_path_obj)

        # **NEW: Check for pre-association**
        # get_association_by_release_name returns (torrent_hash, association_data) or (None, None)
        torrent_hash_of_assoc, pending_assoc_data = torrent_map_manager.find_torrent_by_release_name(item_basename_on_seedbox)

        target_app_type_for_handler = None
        target_id_for_handler = None
        association_source = "None" # For logging

        if pending_assoc_data: # Check if pending_assoc_data is not None
            current_app.logger.info(f"SFTP R&P: Association trouvée by release name '{item_basename_on_seedbox}' (Hash: {torrent_hash_of_assoc}): {pending_assoc_data}")
            target_app_type_for_handler = pending_assoc_data.get('app_type')
            target_id_for_handler = pending_assoc_data.get('target_id')
            association_source = f"Pre-association (Hash: {torrent_hash_of_assoc})"
        elif direct_target_series_id and app_type_of_remote_folder == 'sonarr': # Check app_type_of_remote_folder for sanity
            target_app_type_for_handler = 'sonarr'
            target_id_for_handler = direct_target_series_id
            association_source = "Direct POST data (Sonarr)"
        elif direct_target_movie_id and app_type_of_remote_folder == 'radarr': # Check app_type_of_remote_folder for sanity
            target_app_type_for_handler = 'radarr'
            target_id_for_handler = direct_target_movie_id
            association_source = "Direct POST data (Radarr)"
        else:
            # This case should ideally not be hit if the frontend ensures target_id is sent
            # for "Rapatrier & Mapper" when no pre-association is intended to be used.
            # Or, if this route is *only* for pre-associated items, then this is an error.
            # Given the existing functionality, we assume direct IDs might be provided.
             current_app.logger.warning(f"SFTP R&P: Aucune pré-association trouvée pour '{item_basename_on_seedbox}' et aucun ID cible direct fourni dans la requête pour le type de dossier '{app_type_of_remote_folder}'.")
             return jsonify({"success": False, "error": f"Aucune pré-association trouvée pour '{item_basename_on_seedbox}' et aucun ID cible direct fourni pour mapper."}), 400


        current_app.logger.info(f"SFTP R&P: Handler Target: App='{target_app_type_for_handler}', ID='{target_id_for_handler}', Source='{association_source}'")

        if target_app_type_for_handler == 'sonarr' and target_id_for_handler:
            final_result_dict = _handle_staged_sonarr_item(
                item_name_in_staging=item_basename_on_seedbox, # Name of the item in local staging
                series_id_target=target_id_for_handler,
                path_to_cleanup_in_staging_after_success=path_to_cleanup_after_success_abs,
                user_chosen_season=user_forced_season
            )
        elif target_app_type_for_handler == 'radarr' and target_id_for_handler:
            final_result_dict = _handle_staged_radarr_item(
                item_name_in_staging=item_basename_on_seedbox,
                movie_id_target=target_id_for_handler,
                path_to_cleanup_in_staging_after_success=path_to_cleanup_after_success_abs
            )
        else:
            error_msg_handler = f"Type d'application ('{target_app_type_for_handler}') ou ID cible ('{target_id_for_handler}') invalide pour le traitement final après rapatriement de '{item_basename_on_seedbox}'."
            current_app.logger.error(f"SFTP R&P: {error_msg_handler}")
            return jsonify({"success": False, "error": error_msg_handler}), 400

        # --- Gérer la réponse du handler ---
        if final_result_dict: # Ensure dict is not None
            if final_result_dict.get("action_required") == "resolve_season_episode_mismatch":
                current_app.logger.info(f"SFTP R&P: Discordance S/E détectée par handler Sonarr pour '{item_basename_on_seedbox}', retour au frontend.")
                # Note: If this was from a pre-association, the frontend might not expect this.
                # This specific action_required is usually for interactive mapping.
                # For now, we pass it through. The JS for R&P doesn't handle this currently.
                return jsonify(final_result_dict), 200 # Or a more specific status code
            elif final_result_dict.get("success"):
                flash_msg = final_result_dict.get("message", f"'{item_basename_on_seedbox}' traité avec succès.")
                current_app.logger.info(f"SFTP R&P: Traitement réussi pour '{item_basename_on_seedbox}'. Message: {flash_msg}")
                flash(flash_msg, "success")
                # If processing was successful and it came from a pre-association (torrent_hash_of_assoc is not None)
                if torrent_hash_of_assoc: # Implies it was found by get_association_by_release_name
                    if torrent_map_manager.remove_torrent_from_map(torrent_hash_of_assoc):
                        current_app.logger.info(f"SFTP R&P: Association pour hash '{torrent_hash_of_assoc}' (Release: {item_basename_on_seedbox}) supprimée.")
                    else:
                        current_app.logger.warning(f"SFTP R&P: Échec de la suppression de l'association pour hash '{torrent_hash_of_assoc}'.")
                return jsonify(final_result_dict), final_result_dict.get("status_code_override", 200)
            else: # Echec du handler
                error_msg_handler_fail = final_result_dict.get("error", f"Erreur lors du traitement final de '{item_basename_on_seedbox}'.")
                current_app.logger.error(f"SFTP R&P: Échec du handler pour '{item_basename_on_seedbox}'. Erreur: {error_msg_handler_fail}")
                flash(error_msg_handler_fail, "danger")
                return jsonify(final_result_dict), final_result_dict.get("status_code_override", 500)
        else: # Should not happen if previous logic is correct
            current_app.logger.error(f"SFTP R&P: final_result_dict was None for {item_basename_on_seedbox}, indicates logic error.")
            return jsonify({"success": False, "error": "Erreur interne du serveur lors du traitement post-rapatriement."}), 500
    else: # success_download is False (already handled and returned)
        # This part of the code should not be reached if download failed, as returns are made earlier.
        return jsonify({"success": False, "error": "Échec du téléchargement SFTP, donc pas de traitement."}), 500

# FIN de sftp_retrieve_and_process_action
# ------------------------------------------------------------------------------
# FIN DE LA NOUVELLE ROUTE SFTP_RETRIEVE_AND_PROCESS_ACTION
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# NOUVELLE ROUTE POUR LA SUPPRESSION SFTP D'ITEMS SÉLECTIONNÉS
# (Implémentation de la suppression réelle à faire ensuite)
# ------------------------------------------------------------------------------
@seedbox_ui_bp.route('/sftp-delete-items', methods=['POST'])
@login_required
def sftp_delete_items_action():
    selected_paths_to_delete = request.form.getlist('selected_items_paths') # Ce sont des chemins POSIX complets
    app_type_source_page = request.form.get('app_type_source', 'sonarr_working') # Pour la redirection

    logger.info(f"Demande de suppression SFTP pour les items : {selected_paths_to_delete}")

    if not selected_paths_to_delete:
        flash("Aucun item sélectionné pour la suppression.", "warning")
        return redirect(url_for('seedbox_ui.remote_seedbox_view', app_type_target=app_type_source_page))

    sftp_host = current_app.config.get('SEEDBOX_SFTP_HOST')
    sftp_port = current_app.config.get('SEEDBOX_SFTP_PORT')
    sftp_user = current_app.config.get('SEEDBOX_SFTP_USER')
    sftp_password = current_app.config.get('SEEDBOX_SFTP_PASSWORD')

    if not all([sftp_host, sftp_port, sftp_user, sftp_password]):
        flash("Configuration SFTP manquante.", "danger")
        logger.error("sftp_delete_items_action: Configuration SFTP manquante.")
        return redirect(url_for('seedbox_ui.remote_seedbox_view', app_type_target=app_type_source_page))

    sftp_client = None
    transport = None
    success_count = 0
    failure_count = 0
    failed_items = []

    try:
        transport = paramiko.Transport((sftp_host, int(sftp_port)))
        transport.set_keepalive(60)
        transport.connect(username=sftp_user, password=sftp_password)
        sftp_client = paramiko.SFTPClient.from_transport(transport)
        logger.info(f"SFTP (delete items): Connecté à {sftp_host}.")

        for remote_path_posix in selected_paths_to_delete:
            # Sécurité: Assurer que le chemin est bien dans un des dossiers autorisés (Termines ou Travail)
            # Cette vérification est importante pour éviter de supprimer n'importe quoi.
            # Pour l'instant, on fait confiance aux chemins venant du formulaire,
            # mais une validation plus poussée serait bien (ex: vérifier que ça commence par un des SEEDBOX_..._PATH)

            if sftp_delete_recursive(sftp_client, remote_path_posix, logger):
                success_count += 1
            else:
                failure_count += 1
                failed_items.append(Path(remote_path_posix).name)

        if failure_count > 0:
            flash(f"Suppression SFTP terminée avec {failure_count} échec(s) sur {len(selected_paths_to_delete)} item(s). Items échoués: {', '.join(failed_items)}", "warning")
        else:
            flash(f"{success_count} item(s) supprimé(s) avec succès de la seedbox.", "success")

    except paramiko.ssh_exception.AuthenticationException as e_auth:
        logger.error(f"SFTP (delete items): Erreur d'authentification: {e_auth}")
        flash("Erreur d'authentification SFTP. Vérifiez vos identifiants.", "danger")
    except Exception as e_sftp:
        logger.error(f"SFTP (delete items): Erreur générale SFTP: {e_sftp}", exc_info=True)
        flash(f"Erreur SFTP lors de la suppression: {e_sftp}", "danger")
    finally:
        if sftp_client: sftp_client.close()
        if transport: transport.close()
        logger.debug("SFTP (delete items): Connexion fermée.")

    return redirect(url_for('seedbox_ui.remote_seedbox_view', app_type_target=app_type_source_page))
# ------------------------------------------------------------------------------
# FONCTION trigger_sonarr_import
# ------------------------------------------------------------------------------

@seedbox_ui_bp.route('/trigger-sonarr-import', methods=['POST'])
@login_required
def trigger_sonarr_import():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name') # Nom de l'item UI (dossier ou fichier dans le staging, peut être un chemin relatif)
    series_id_from_frontend = data.get('series_id')

    logger.info(f"TRIGGER_SONARR_IMPORT: Début pour item '{item_name_from_frontend}', série ID {series_id_from_frontend}")

    # Récupérer les configs
    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not all([item_name_from_frontend, series_id_from_frontend, sonarr_url, sonarr_api_key, staging_dir]):
        logger.error("trigger_sonarr_import: Données POST manquantes ou config Sonarr/staging incomplète.")
        return jsonify({"success": False, "error": "Données manquantes ou Sonarr/staging non configuré."}), 400

    # path_of_item_in_staging_abs est le chemin complet de ce sur quoi l'utilisateur a cliqué dans l'UI du staging local.
    # item_name_from_frontend est le chemin relatif par rapport à staging_dir.
    path_of_item_in_staging_abs = (Path(staging_dir) / item_name_from_frontend).resolve()

    if not path_of_item_in_staging_abs.exists():
        logger.error(f"trigger_sonarr_import: Item UI '{item_name_from_frontend}' (résolu en {path_of_item_in_staging_abs}) non trouvé.")
        return jsonify({"success": False, "error": f"Item '{item_name_from_frontend}' non trouvé dans le staging."}), 404

    # --- Déterminer le chemin à scanner pour le GET manualimport initial (pour la validation S/E) ---
    # Ce scan est fait sur le dossier contenant le fichier vidéo principal, ou le dossier lui-même.
    path_to_scan_for_validation_get = ""
    if path_of_item_in_staging_abs.is_file():
        path_to_scan_for_validation_get = str(path_of_item_in_staging_abs.parent).replace('/', '\\')
        main_video_filename_for_validation = path_of_item_in_staging_abs.name
    elif path_of_item_in_staging_abs.is_dir():
        path_to_scan_for_validation_get = str(path_of_item_in_staging_abs).replace('/', '\\')
        # Essayer de trouver un nom de fichier vidéo à l'intérieur pour la validation S/E
        main_video_filename_for_validation = None
        for f_name in os.listdir(path_of_item_in_staging_abs):
            if any(f_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi']):
                main_video_filename_for_validation = f_name
                break
        if not main_video_filename_for_validation:
            logger.warning(f"trigger_sonarr_import: Aucun fichier vidéo trouvé dans le dossier '{item_name_from_frontend}' pour la validation S/E. L'import sera tenté en se fiant à Sonarr.")
            # Si aucun fichier vidéo, la validation S/E sera skipped, et on appelle directement _handle_staged_sonarr_item
            result_dict = _handle_staged_sonarr_item(item_name_from_frontend, series_id_from_frontend, str(path_of_item_in_staging_abs))
            return jsonify(result_dict), result_dict.get("status_code_override", 200 if result_dict.get("success") else 500)
    else:
        return jsonify({"success": False, "error": "Item de staging non valide."}), 400


    # --- Appel GET manualimport pour la validation S/E ---
    manual_import_get_url = f"{sonarr_url.rstrip('/')}/api/v3/manualimport"
    get_params = {'folder': path_to_scan_for_validation_get, 'filterExistingFiles': 'false'}
    logger.debug(f"TRIGGER_SONARR_IMPORT (Validation S/E): GET Sonarr ManualImport: URL={manual_import_get_url}, Params={get_params}")
    manual_import_candidates, error_msg_get = _make_arr_request('GET', manual_import_get_url, sonarr_api_key, params=get_params)

    if error_msg_get or not isinstance(manual_import_candidates, list): # Peut être une liste vide, c'est ok
        logger.error(f"TRIGGER_SONARR_IMPORT (Validation S/E): Erreur Sonarr GET manualimport: {error_msg_get or 'Réponse non-liste'}")
        # On tente quand même l'import, _handle_staged_sonarr_item refera un GET et gèrera l'erreur si elle persiste.
        result_dict = _handle_staged_sonarr_item(item_name_from_frontend, series_id_from_frontend, str(path_of_item_in_staging_abs))
        return jsonify(result_dict), result_dict.get("status_code_override", 200 if result_dict.get("success") else 500)

    # Trouver le candidat qui correspond à notre main_video_filename_for_validation
    sonarr_season_num_for_validation = None
    sonarr_episode_num_for_validation = None

    for candidate in manual_import_candidates:
        candidate_file_path_from_api = candidate.get('path') # Path relatif au 'folder' scanné
        if not candidate_file_path_from_api: continue

        # Le nom de fichier retourné par Sonarr peut être différent (ex: normalisé)
        # On compare avec le nom de fichier qu'on a identifié comme principal
        if Path(candidate_file_path_from_api).name.lower() == main_video_filename_for_validation.lower():
            candidate_episodes_info = candidate.get('episodes', [])
            if candidate_episodes_info:
                sonarr_season_num_for_validation = candidate_episodes_info[0].get('seasonNumber')
                sonarr_episode_num_for_validation = candidate_episodes_info[0].get('episodeNumber')
                break

    # --- Logique de validation S/E ---
    if sonarr_season_num_for_validation is not None and main_video_filename_for_validation:
        filename_season_num, filename_episode_num = None, None
        s_e_match = re.search(r'[._\s\[\(-]S(\d{1,3})[E._\s-]?(\d{1,3})', main_video_filename_for_validation, re.IGNORECASE)
        if s_e_match:
            try:
                filename_season_num = int(s_e_match.group(1))
                filename_episode_num = int(s_e_match.group(2))
                logger.info(f"TRIGGER_SONARR_IMPORT (Validation S/E): Pour '{main_video_filename_for_validation}': Fichier S{filename_season_num}E{filename_episode_num}. Sonarr S{sonarr_season_num_for_validation}E{sonarr_episode_num_for_validation}.")
                if filename_season_num != sonarr_season_num_for_validation:
                    logger.warning(f"TRIGGER_SONARR_IMPORT: DISCORDANCE SAISON DÉTECTÉE.")
                    return jsonify({
                        "success": False, "action_required": "resolve_season_episode_mismatch",
                        "message": f"Discordance Saison/Épisode détectée pour '{main_video_filename_for_validation}'.",
                        "details": {
                            "filename_season": filename_season_num, "filename_episode": filename_episode_num,
                            "sonarr_season": sonarr_season_num_for_validation, "sonarr_episode": sonarr_episode_num_for_validation,
                            "staging_item_name": item_name_from_frontend,
                            "series_id": series_id_from_frontend,
                            "source_video_file_path_in_staging": str(path_of_item_in_staging_abs / main_video_filename_for_validation if path_of_item_in_staging_abs.is_dir() else path_of_item_in_staging_abs)
                        }
                    }), 200
            except ValueError: logger.warning(f"TRIGGER_SONARR_IMPORT (Validation S/E): Erreur conversion S/E pour '{main_video_filename_for_validation}'.")
        else: logger.warning(f"TRIGGER_SONARR_IMPORT (Validation S/E): Impossible d'extraire SxxExx de '{main_video_filename_for_validation}'.")
    else:
        logger.info(f"TRIGGER_SONARR_IMPORT: Pas de validation S/E effectuée (Sonarr n'a pas identifié l'épisode pour '{main_video_filename_for_validation}' ou pas de fichier vidéo principal trouvé).")

    # Si pas de discordance bloquante, appeler le handler _execute_mms_sonarr_import.
    # original_release_folder_name_in_staging est item_name_from_frontend car pour un item du staging,
    # le "dossier de release" est l'item lui-même (s'il est un dossier) ou son parent (s'il est un fichier,
    # mais item_name_from_frontend est typiquement le nom du dossier de release).
    # Pour la logique de nettoyage, _execute_mms_sonarr_import s'attend au nom du dossier de premier niveau.
    result_dict = _execute_mms_sonarr_import(
        item_name_in_staging=item_name_from_frontend,
        series_id_target=series_id_from_frontend,
        original_release_folder_name_in_staging=item_name_from_frontend, # L'item lui-même est le dossier de release
        user_forced_season=None, # Pas de saison forcée dans ce flux normal
        torrent_hash_for_status_update=problem_torrent_hash if 'problem_torrent_hash' in data else None,
        is_automated_flow=False # Action manuelle depuis l'UI
    )

    if result_dict.get("success"): # Pas besoin de vérifier action_required ici, _execute_mms gère le retour final
        return jsonify(result_dict), 200
    else:
        return jsonify(result_dict), 500 # Ou un code d'erreur plus spécifique si _execute_mms le fournit

# FIN de trigger_sonarr_import (MODIFIÉE)
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# ROUTE POUR L'IMPORT FORCÉ SONARR (MODIFIÉE POUR UTILISER _execute_mms_sonarr_import)
# ------------------------------------------------------------------------------
@seedbox_ui_bp.route('/force-sonarr-import-action', methods=['POST'])
@login_required
def force_sonarr_import_action():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name')
    series_id_from_frontend = data.get('series_id')
    target_season_for_move = data.get('target_season')
    problem_torrent_hash = data.get('problem_torrent_hash') # Peut être présent

    logger.info(f"Force Sonarr Import Action pour item: '{item_name_from_frontend}', Série ID: {series_id_from_frontend}, Saison Cible: {target_season_for_move}, Hash: {problem_torrent_hash}")

    if not all([item_name_from_frontend, series_id_from_frontend, target_season_for_move is not None]):
        return jsonify({"success": False, "error": "Données manquantes pour l'import forcé."}), 400

    try:
        series_id_int = int(series_id_from_frontend)
        target_season_int = int(target_season_for_move)
    except ValueError:
        return jsonify({"success": False, "error": "ID Série ou Saison Cible invalide (doit être numérique)."}), 400

    # original_release_folder_name_in_staging est item_name_from_frontend
    result_dict = _execute_mms_sonarr_import(
        item_name_in_staging=item_name_from_frontend,
        series_id_target=series_id_int,
        original_release_folder_name_in_staging=item_name_from_frontend,
        user_forced_season=target_season_int, # La saison que l'utilisateur a choisie
        torrent_hash_for_status_update=problem_torrent_hash,
        is_automated_flow=False # Action manuelle
    )

    if result_dict.get("success"):
        flash(result_dict.get("message"), "success")
        return jsonify(result_dict), 200
    else:
        flash(result_dict.get("message", "Erreur lors de l'import forcé."), "danger")
        return jsonify(result_dict), 500

# FIN DE force_sonarr_import_action (MODIFIÉE)
# ------------------------------------------------------------------------------
# trigger_radarr_import (MODIFIÉE POUR UTILISER _execute_mms_radarr_import)
# ------------------------------------------------------------------------------

@seedbox_ui_bp.route('/trigger-radarr-import', methods=['POST'])
@login_required
def trigger_radarr_import():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name')
    movie_id_from_frontend = data.get('movie_id')
    problem_torrent_hash = data.get('problem_torrent_hash')

    logger = current_app.logger
    log_prefix_trigger = f"TRIGGER_RADARR_IMPORT (ProblemHash: {problem_torrent_hash}): "
    logger.info(f"{log_prefix_trigger}Début pour item '{item_name_from_frontend}', Movie ID {movie_id_from_frontend}")

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not all([item_name_from_frontend, movie_id_from_frontend is not None, radarr_url, radarr_api_key, staging_dir]):
        logger.error(f"{log_prefix_trigger}Données POST manquantes ou config Radarr/staging incomplète.")
        return jsonify({"success": False, "error": "Données manquantes ou Radarr/staging non configuré."}), 400

    try:
        movie_id_int = int(movie_id_from_frontend)
    except ValueError:
        logger.error(f"{log_prefix_trigger}Movie ID invalide: '{movie_id_from_frontend}'. Doit être un entier.")
        return jsonify({"success": False, "error": "Format de Movie ID invalide."}), 400

    path_of_item_in_staging_abs = (Path(staging_dir) / item_name_from_frontend).resolve()
    if not path_of_item_in_staging_abs.exists():
        logger.error(f"{log_prefix_trigger}Item UI '{item_name_from_frontend}' (résolu en {path_of_item_in_staging_abs}) non trouvé.")
        return jsonify({"success": False, "error": f"Item '{item_name_from_frontend}' non trouvé dans le staging."}), 404

    # --- Validation optionnelle de MovieID (peut être conservée ou simplifiée) ---
    # La logique de validation existante peut rester si jugée utile avant l'appel à _execute_mms_radarr_import.
    # Pour la refactorisation, on se concentre sur l'appel à la nouvelle fonction helper.
    # Si la validation échoue, on retourne une erreur avant d'appeler _execute_mms_radarr_import.
    # (Logique de validation optionnelle omise ici pour la concision du diff, mais peut être gardée)
    # ... (votre logique de validation existante ici, si elle retourne une erreur, faites-le avant l'appel ci-dessous)

    # Appeler le helper _execute_mms_radarr_import
    result_dict = _execute_mms_radarr_import(
        item_name_in_staging=item_name_from_frontend,
        movie_id_target=movie_id_int, # movie_id_target est déjà un entier
        original_release_folder_name_in_staging=item_name_from_frontend,
        torrent_hash_for_status_update=problem_torrent_hash,
        is_automated_flow=False # Action manuelle
    )

    if result_dict.get("success"):
        if problem_torrent_hash: # Si c'était un re-mapping
            logger.info(f"{log_prefix_trigger}Re-mapping réussi pour l'item avec hash {problem_torrent_hash}. Suppression de l'ancienne association.")
            if torrent_map_manager.remove_torrent_from_map(problem_torrent_hash):
                logger.info(f"{log_prefix_trigger}Ancienne association pour hash {problem_torrent_hash} supprimée.")
            else:
                logger.warning(f"{log_prefix_trigger}Échec de la suppression de l'ancienne association pour hash {problem_torrent_hash} (peut-être déjà supprimée).")
        return jsonify(result_dict), 200
    else:
        return jsonify(result_dict), 500

# FIN de trigger_radarr_import (MODIFIÉE)


@seedbox_ui_bp.route('/cleanup-staging-item/<path:item_name>', methods=['POST'])
@login_required
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

@seedbox_ui_bp.route('/interaction/rtorrent/add', methods=['POST'])
@login_required
def rtorrent_add_torrent_action():
    logger = current_app.logger
    data = request.get_json()

    if not data:
        logger.error("RTORRENT_ADD_ACTION: Aucune donnée JSON reçue.")
        return jsonify({"success": False, "error": "Aucune donnée JSON reçue."}), 400

    # Récupération des données du payload JS
    magnet_link = data.get('magnet_link')
    torrent_file_b64 = data.get('torrent_file_b64')
    app_type = data.get('app_type')
    original_name_from_js = data.get('original_name')

    is_new_media = data.get('is_new_media', False)
    external_id_str = data.get('external_id') # TVDB ID (Sonarr) ou TMDB ID (Radarr)
    title_for_add = data.get('title_for_add')
    root_folder_path_chosen = data.get('root_folder_path')
    quality_profile_id_chosen_str = data.get('quality_profile_id')
    target_id_existing_str = data.get('target_id') # ID interne si média existant

    logger.info(f"RTORRENT_ADD_ACTION: Payload reçu: app_type='{app_type}', is_new={is_new_media}, "
                f"external_id='{external_id_str}', title_add='{title_for_add}', root='{root_folder_path_chosen}', "
                f"q_profile='{quality_profile_id_chosen_str}', existing_id='{target_id_existing_str}', "
                f"original_name='{original_name_from_js}'")

    # --- Validations initiales ---
    if not (magnet_link or torrent_file_b64):
        return jsonify({"success": False, "error": "Lien magnet ou fichier torrent manquant."}), 400
    if not app_type or not original_name_from_js:
        return jsonify({"success": False, "error": "Type d'application ou nom original manquant."}), 400
    if app_type not in ['sonarr', 'radarr']:
        return jsonify({"success": False, "error": "Type d'application invalide."}), 400

    actual_target_id = None # Deviendra l'ID interne Sonarr/Radarr

    if is_new_media:
        if not external_id_str or not title_for_add or not root_folder_path_chosen or not quality_profile_id_chosen_str:
            logger.error("RTORRENT_ADD_ACTION: Données manquantes pour l'ajout d'un nouveau média.")
            return jsonify({"success": False, "error": "Pour un nouveau média, ID externe, titre, dossier racine et profil de qualité sont requis."}), 400
        try:
            # external_id sera tvdbId pour Sonarr, tmdbId pour Radarr
            external_id = int(external_id_str)
            quality_profile_id_chosen = int(quality_profile_id_chosen_str)
        except ValueError:
            logger.error("RTORRENT_ADD_ACTION: Format ID externe ou profil qualité invalide.")
            return jsonify({"success": False, "error": "Format invalide pour ID externe ou profil de qualité."}), 400
    else: # Média existant
        if target_id_existing_str is None:
            logger.error("RTORRENT_ADD_ACTION: target_id manquant pour un média existant.")
            return jsonify({"success": False, "error": "target_id manquant pour un média existant."}), 400
        try:
            actual_target_id = int(target_id_existing_str)
        except ValueError:
            logger.error(f"RTORRENT_ADD_ACTION: Format de target_id invalide: {target_id_existing_str}")
            return jsonify({"success": False, "error": "Format de target_id invalide pour média existant."}), 400

    # --- Configuration rTorrent et *Arr ---
    if app_type == 'sonarr':
        rtorrent_label = current_app.config.get('RTORRENT_LABEL_SONARR')
        rtorrent_download_dir = current_app.config.get('RTORRENT_DOWNLOAD_DIR_SONARR')
        arr_url = current_app.config.get('SONARR_URL')
        arr_api_key = current_app.config.get('SONARR_API_KEY')
    else: # radarr
        rtorrent_label = current_app.config.get('RTORRENT_LABEL_RADARR')
        rtorrent_download_dir = current_app.config.get('RTORRENT_DOWNLOAD_DIR_RADARR')
        arr_url = current_app.config.get('RADARR_URL')
        arr_api_key = current_app.config.get('RADARR_API_KEY')

    if not rtorrent_label or not rtorrent_download_dir:
        return jsonify({"success": False, "error": f"Configuration rTorrent (label/dir) manquante pour {app_type}."}), 500
    if is_new_media and (not arr_url or not arr_api_key):
         return jsonify({"success": False, "error": f"Configuration API {app_type} manquante pour ajouter un nouveau média."}), 500

    # --- Étape 1 (Optionnelle) : Ajouter le média à Sonarr/Radarr si nouveau ---
    if is_new_media:
        logger.info(f"RTORRENT_ADD_ACTION: Ajout de '{title_for_add}' (ID externe: {external_id}) à {app_type.capitalize()}...")
        add_payload = {}
        api_add_endpoint = ""

        if app_type == 'sonarr':
            # Récupérer le languageProfileId (par défaut 1 si non configurable par l'utilisateur)
            # Vous pourriez avoir une route API pour les lister et les faire choisir.
            language_profile_id = 1 # TODO: Rendre configurable ou récupérer dynamiquement
            add_payload = {
                "tvdbId": external_id,
                "title": title_for_add,
                "qualityProfileId": quality_profile_id_chosen,
                "languageProfileId": language_profile_id,
                "rootFolderPath": root_folder_path_chosen,
                "seasonFolder": True,
                "monitored": True,
                "addOptions": { "searchForMissingEpisodes": False } # Ou True si vous voulez une recherche immédiate
            }
            api_add_endpoint = f"{arr_url.rstrip('/')}/api/v3/series"
        else: # radarr
            add_payload = {
                "tmdbId": external_id,
                "title": title_for_add,
                "qualityProfileId": quality_profile_id_chosen,
                "rootFolderPath": root_folder_path_chosen,
                "monitored": True,
                "addOptions": { "searchForMovie": False } # Ou True
            }
            api_add_endpoint = f"{arr_url.rstrip('/')}/api/v3/movie"

        logger.debug(f"RTORRENT_ADD_ACTION: Payload d'ajout à {app_type.capitalize()}: {add_payload}")
        added_media_data, error_add_media = _make_arr_request('POST', api_add_endpoint, arr_api_key, json_data=add_payload)

        if error_add_media or not added_media_data or not isinstance(added_media_data, dict) or not added_media_data.get("id"):
            err_msg = f"Échec de l'ajout de '{title_for_add}' à {app_type.capitalize()}: {error_add_media or 'Réponse API invalide ou ID manquant.'}"
            logger.error(f"RTORRENT_ADD_ACTION: {err_msg}. Réponse API: {added_media_data}")
            # Vérifier si l'erreur est due à un média déjà existant (conflit)
            if error_add_media and isinstance(error_add_media, str) and ("already been added" in error_add_media.lower() or "exists with a different" in error_add_media.lower()):
                 # Essayer de récupérer l'ID existant si possible (plus complexe, nécessite une recherche par titre/ID externe)
                 # Pour l'instant, on retourne l'erreur.
                 pass # L'utilisateur devra mapper manuellement à l'existant.
            return jsonify({"success": False, "error": err_msg}), 502

        actual_target_id = added_media_data.get("id")
        logger.info(f"RTORRENT_ADD_ACTION: Média '{title_for_add}' ajouté à {app_type.capitalize()} avec ID interne: {actual_target_id}")
    # Si ce n'était pas un nouveau média, actual_target_id a été défini à partir de target_id_existing_str

    if actual_target_id is None: # Sécurité : on doit avoir un ID cible à ce stade
        logger.error("RTORRENT_ADD_ACTION: ID cible final non déterminé. Impossible de continuer.")
        return jsonify({"success": False, "error": "Erreur interne: ID cible non déterminé."}), 500

    # --- Étape 2 : Déterminer le nom de la release pour rTorrent et le map ---
    release_name_for_map = None
    torrent_content_bytes = None
    if torrent_file_b64:
        try:
            torrent_content_bytes = base64.b64decode(torrent_file_b64)
            release_name_for_map = _decode_bencode_name(torrent_content_bytes)
            if not release_name_for_map:
                logger.warning(f"RTORRENT_ADD_ACTION: Impossible d'extraire info['name'] de '{original_name_from_js}'. Fallback sur nom de fichier.")
                temp_name = re.sub(r'^\[[^\]]*\]\s*', '', original_name_from_js)
                release_name_for_map = re.sub(r'\.torrent$', '', temp_name, flags=re.IGNORECASE).strip()
        except Exception as e_decode:
            logger.error(f"RTORRENT_ADD_ACTION: Erreur décodage torrent '{original_name_from_js}' pour release_name: {e_decode}. Fallback.")
            temp_name = re.sub(r'^\[[^\]]*\]\s*', '', original_name_from_js)
            release_name_for_map = re.sub(r'\.torrent$', '', temp_name, flags=re.IGNORECASE).strip()
    elif magnet_link:
        parsed_magnet = urllib.parse.parse_qs(urllib.parse.urlparse(magnet_link).query)
        display_names = parsed_magnet.get('dn')
        if display_names and display_names[0]:
            release_name_for_map = display_names[0].strip()
        else:
            release_name_for_map = original_name_from_js.strip() # Peut nécessiter un nettoyage plus poussé
            logger.warning(f"RTORRENT_ADD_ACTION: 'dn' non trouvé dans magnet. Utilisation de '{release_name_for_map}' (depuis original_name_from_js).")

    if not release_name_for_map:
         return jsonify({"success": False, "error": "Impossible de déterminer le nom de la release pour rTorrent/mapping."}), 500
    logger.info(f"RTORRENT_ADD_ACTION: Nom de release déterminé pour rTorrent/map: '{release_name_for_map}'")

    # --- Étape 3 : Ajouter le torrent à rTorrent ---
    success_add_rtorrent, error_msg_rtorrent = False, "Action rTorrent non initialisée."
    if magnet_link:
        success_add_rtorrent, error_msg_rtorrent = rtorrent_add_magnet_httprpc(magnet_link, rtorrent_label, rtorrent_download_dir)
    elif torrent_content_bytes:
        success_add_rtorrent, error_msg_rtorrent = rtorrent_add_torrent_file_httprpc(torrent_content_bytes, original_name_from_js, rtorrent_label, rtorrent_download_dir)

    if not success_add_rtorrent:
        logger.error(f"RTORRENT_ADD_ACTION: Échec ajout à rTorrent: {error_msg_rtorrent}")
        # Si on avait ajouté un média à *Arr, on pourrait vouloir le supprimer, mais c'est complexe.
        # Pour l'instant, on retourne l'erreur.
        return jsonify({"success": False, "error": f"Erreur rTorrent: {error_msg_rtorrent}"}), 500
    logger.info(f"RTORRENT_ADD_ACTION: Torrent '{original_name_from_js}' envoyé à rTorrent.")

    # --- Étape 4 : Récupérer le Hash et Sauvegarder l'Association ---
    time.sleep(current_app.config.get('RTORRENT_POST_ADD_DELAY_SECONDS', 3))
    actual_hash = rtorrent_get_hash_by_name(release_name_for_map) # Tenter avec le nom de la release (info['name'] ou dn)
    if not actual_hash: # Fallback sur le nom original du fichier .torrent (nettoyé)
        cleaned_original_filename = re.sub(r'\.torrent$', '', original_name_from_js, flags=re.IGNORECASE).strip()
        if cleaned_original_filename != release_name_for_map: # Éviter de chercher deux fois la même chose
            logger.info(f"RTORRENT_ADD_ACTION: Hash non trouvé pour '{release_name_for_map}', tentative avec '{cleaned_original_filename}'.")
            actual_hash = rtorrent_get_hash_by_name(cleaned_original_filename)

    if not actual_hash:
        msg = f"Torrent '{original_name_from_js}' ajouté à rTorrent, mais son hash n'a pas pu être récupéré immédiatement. La pré-association automatique a échoué. L'item devra être mappé manuellement depuis le staging ou la vue rTorrent."
        logger.warning(f"RTORRENT_ADD_ACTION: {msg}")
        return jsonify({"success": True, "message": msg, "warning": "Hash non récupérable pour pré-association."}), 202

    logger.info(f"RTORRENT_ADD_ACTION: Hash rTorrent '{actual_hash}' trouvé pour '{original_name_from_js}'.")

    # Le chemin sur la seedbox sera le rtorrent_download_dir + le nom de la release que rTorrent utilise (release_name_for_map)
    seedbox_full_download_path = str(Path(rtorrent_download_dir) / release_name_for_map).replace('\\', '/')

    if torrent_map_manager.add_or_update_torrent_in_map(
            torrent_hash=actual_hash,
            release_name=release_name_for_map,
            app_type=app_type,
            target_id=actual_target_id, # ID interne Sonarr/Radarr
            label=rtorrent_label,
            seedbox_download_path=seedbox_full_download_path,
            original_torrent_name=original_name_from_js,
            initial_status="transferring_to_seedbox"
        ):
        final_msg = f"Torrent '{release_name_for_map}' (Hash: {actual_hash}) ajouté à rTorrent. "
        if is_new_media:
            final_msg += f"Nouveau média '{title_for_add}' (ID {app_type.capitalize()}: {actual_target_id}) ajouté et pré-associé."
        else:
            final_msg += f"Pré-associé au média existant (ID {app_type.capitalize()}: {actual_target_id})."
        logger.info(f"RTORRENT_ADD_ACTION: {final_msg}")
        return jsonify({"success": True, "message": final_msg, "torrent_hash": actual_hash}), 200
    else:
        logger.error(f"RTORRENT_ADD_ACTION: Torrent {actual_hash} ajouté, mais échec sauvegarde de l'association pour '{release_name_for_map}'.")
        return jsonify({"success": True, "error": "Torrent ajouté, mais échec de la sauvegarde de la pré-association.", "torrent_hash": actual_hash}), 207

@seedbox_ui_bp.route('/rtorrent/list-view')
@login_required
def rtorrent_list_view():
    current_app.logger.info("Accessing rTorrent list view page (using httprpc client).")

    torrents_data, error_msg_rtorrent = rtorrent_list_torrents_api() # This now calls the httprpc version

    if error_msg_rtorrent:
        current_app.logger.error(f"Error fetching torrents from rTorrent (httprpc): {error_msg_rtorrent}")
        flash(f"Impossible de lister les torrents de rTorrent: {error_msg_rtorrent}", "danger")
        return render_template('seedbox_ui/rtorrent_list.html',
                               torrents_with_assoc=[],
                               page_title="Liste des Torrents rTorrent (Erreur)",
                               error_message=error_msg_rtorrent)

    if torrents_data is None: # Should be caught by error_msg_rtorrent
        current_app.logger.warning("rtorrent_list_torrents_api (httprpc) returned None for data without an error message.")
        flash("Aucune donnée reçue de rTorrent.", "warning")
        torrents_data = []

    # pending_associations = get_all_pending_associations() # Removed, direct lookup by hash

    torrents_with_assoc = []
    if isinstance(torrents_data, list):
        for torrent in torrents_data: # Each 'torrent' is a dict from the new list_torrents()
            torrent_hash = torrent.get('hash')
            association_info = None
            if torrent_hash:
                # get_association_by_hash returns the association data dict directly, or None
                association_data = torrent_map_manager.get_torrent_by_hash(torrent_hash)
                if association_data:
                     association_info = association_data
            # else: # No hash for the torrent, cannot look up association
            #    current_app.logger.debug(f"Torrent '{torrent.get('name')}' has no hash, cannot look up association.")

            torrents_with_assoc.append({
                "details": torrent,
                "association": association_info
            })
    else:
        current_app.logger.error(f"rtorrent_list_torrents_api (httprpc) did not return a list. Got: {type(torrents_data)}")
        flash("Format de données inattendu reçu de rTorrent.", "danger")
        # Render with empty list
        return render_template('seedbox_ui/rtorrent_list.html', torrents_with_assoc=[], page_title="Liste des Torrents rTorrent (Erreur Format)", error_message="Format de données rTorrent invalide.")


    current_app.logger.info(f"Affichage de {len(torrents_with_assoc)} torrent(s) avec leurs informations d'association (httprpc).")

    # Pass configured labels to the template
    config_label_sonarr = current_app.config.get('RTORRENT_LABEL_SONARR', 'sonarr')
    config_label_radarr = current_app.config.get('RTORRENT_LABEL_RADARR', 'radarr')

    return render_template('seedbox_ui/rtorrent_list.html',
                           torrents_with_assoc=torrents_with_assoc,
                           page_title="Liste des Torrents rTorrent",
                           error_message=None,
                           config_label_sonarr=config_label_sonarr,
                           config_label_radarr=config_label_radarr)

@seedbox_ui_bp.route('/add-torrent-and-map', methods=['POST'])
@login_required
def add_torrent_and_map():
    """
    Route pour ajouter un torrent à rTorrent/ruTorrent et potentiellement préparer un mapping.
    """
    current_app.logger.info("Début de la route add_torrent_and_map.")

    # 1. Récupérer les données du formulaire
    torrent_url_or_magnet = request.form.get('torrent_url_or_magnet')
    media_type = request.form.get('media_type') # 'series' ou 'movie'
    media_id = request.form.get('media_id') # ID Sonarr/Radarr
    media_name = request.form.get('media_name') # Nom du film ou de la série pour le sous-dossier
    # episode_mapping_info = request.form.get('episode_mapping_info') # Non utilisé pour l'instant
    # season_folder_name = request.form.get('season_folder_name') # Non utilisé pour l'instant
    # episode_number_full = request.form.get('episode_number_full') # Non utilisé pour l'instant

    current_app.logger.debug(f"Données du formulaire reçues: URL/Magnet='{torrent_url_or_magnet}', Type='{media_type}', ID='{media_id}', Nom='{media_name}'")

    if not all([torrent_url_or_magnet, media_type, media_id]):
        flash("Données manquantes (URL/Magnet, type de média ou ID média requis).", 'danger')
        current_app.logger.error("add_torrent_and_map: Données de formulaire manquantes.")
        return redirect(url_for('seedbox_ui.rtorrent_list')) # Rediriger vers une page pertinente

    # 2. Récupérer les configurations de l'application
    rutorrent_api_url = current_app.config.get('RUTORRENT_API_URL')
    rutorrent_user = current_app.config.get('RUTORRENT_USER')
    rutorrent_password = current_app.config.get('RUTORRENT_PASSWORD')
    ssl_verify_str = current_app.config.get('SEEDBOX_SSL_VERIFY', "True") # Default à "True" si non défini

    if not rutorrent_api_url:
        flash("L'URL de l'API ruTorrent n'est pas configurée.", 'danger')
        current_app.logger.error("add_torrent_and_map: RUTORRENT_API_URL non configuré.")
        return redirect(url_for('seedbox_ui.rtorrent_list'))

    # 3. Construire le download_dir
    base_download_dir = ""
    if media_type == 'series':
        base_download_dir = current_app.config.get('RTORRENT_DOWNLOAD_DIR_SONARR')
    elif media_type == 'movie':
        base_download_dir = current_app.config.get('RTORRENT_DOWNLOAD_DIR_RADARR')
    else:
        flash(f"Type de média inconnu: {media_type}.", 'danger')
        current_app.logger.error(f"add_torrent_and_map: Type de média inconnu '{media_type}'.")
        return redirect(url_for('seedbox_ui.rtorrent_list'))

    if not base_download_dir:
        flash(f"Dossier de téléchargement de base pour '{media_type}' non configuré.", 'danger')
        current_app.logger.error(f"add_torrent_and_map: Dossier de téléchargement de base pour '{media_type}' non configuré.")
        return redirect(url_for('seedbox_ui.rtorrent_list'))

    final_download_dir = base_download_dir
    if media_name:
        # Assurer la propreté du nom pour un chemin de dossier et la compatibilité POSIX pour rTorrent
        sane_media_name = "".join(c if c.isalnum() or c in [' ', '.', '-'] else '_' for c in media_name).strip()
        sane_media_name = sane_media_name.replace(' ', '_') # Remplacer les espaces par des underscores
        if sane_media_name: # S'assurer que le nom n'est pas vide après nettoyage
            final_download_dir = os.path.join(base_download_dir, sane_media_name).replace('\\', '/')
            current_app.logger.info(f"Construction du chemin de téléchargement avec sous-dossier: {final_download_dir}")
        else:
            current_app.logger.warning(f"Le nom du média '{media_name}' est devenu vide après nettoyage. Utilisation du dossier de base '{base_download_dir}'.")
    else:
        current_app.logger.info(f"Utilisation du chemin de téléchargement de base: {final_download_dir}")


    # 4. Construire le label
    final_label = ""
    if media_type == 'series':
        final_label = current_app.config.get('RTORRENT_LABEL_SONARR')
    elif media_type == 'movie':
        final_label = current_app.config.get('RTORRENT_LABEL_RADARR')

    if not final_label: # Peut être une chaîne vide intentionnellement, mais on logue si c'est le cas
        current_app.logger.warning(f"Aucun label rTorrent/ruTorrent configuré pour le type de média '{media_type}'. Le torrent sera ajouté sans label spécifique de l'application.")
        final_label = "" # Assurer que c'est une chaîne

    current_app.logger.info(f"Paramètres pour add_torrent_to_rutorrent: URL/Magnet='{torrent_url_or_magnet}', Dir='{final_download_dir}', Label='{final_label}'")

    # 5. Appeler la fonction add_torrent_to_rutorrent
    success, message = add_torrent_to_rutorrent(
        logger=current_app.logger,
        torrent_url_or_magnet=torrent_url_or_magnet,
        download_dir=final_download_dir,
        label=final_label,
        rutorrent_api_url=rutorrent_api_url,
        username=rutorrent_user,
        password=rutorrent_password,
        ssl_verify_str=ssl_verify_str
    )

    # 6. Gérer le résultat
    if success:
        flash(f"Torrent en cours d'ajout à ruTorrent: {message}", 'success')
        current_app.logger.info(f"add_torrent_and_map: Ajout réussi à ruTorrent - {message}")
        # Ici, on pourrait ajouter la logique de pré-association si nécessaire dans le futur.
        # Par exemple, appeler add_pending_association(torrent_hash_ou_nom, media_type, media_id, final_label, media_name_ou_nom_torrent)
        # Pour l'instant, cette partie est omise comme demandé.
    else:
        flash(f"Échec de l'ajout du torrent à ruTorrent: {message}", 'danger')
        current_app.logger.error(f"add_torrent_and_map: Échec de l'ajout à ruTorrent - {message}")

    # 7. Rediriger
    return redirect(url_for('seedbox_ui.rtorrent_list_view')) # Redirection vers la liste des torrents

@seedbox_ui_bp.route('/process-staged-with-association/<path:item_name_in_staging>', methods=['POST'])
@login_required
def process_staged_with_association(item_name_in_staging):
    """
    Traite un item du staging en utilisant une pré-association existante.
    """
    current_app.logger.info(f"Traitement avec association demandé pour : {item_name_in_staging}")

    staging_dir = current_app.config.get('STAGING_DIR')
    if not staging_dir: # Should not happen if app is configured
        flash("Le dossier de staging n'est pas configuré dans l'application.", "danger")
        current_app.logger.error("process_staged_with_association: STAGING_DIR non configuré.")
        return redirect(url_for('seedbox_ui.index'))

    path_of_item_in_staging_abs = (Path(staging_dir) / item_name_in_staging).resolve()

    if not path_of_item_in_staging_abs.exists():
        flash(f"L'item '{item_name_in_staging}' n'a pas été trouvé dans le dossier de staging.", "danger")
        current_app.logger.error(f"Item '{path_of_item_in_staging_abs}' non trouvé lors du traitement avec association.")
        return redirect(url_for('seedbox_ui.index'))

    # get_association_by_release_name returns (torrent_hash, association_data) or (None, None)
    torrent_hash_of_assoc, association_data = torrent_map_manager.find_torrent_by_release_name(item_name_in_staging)

    if association_data is None: # Check if association_data is None
        flash(f"Aucune pré-association trouvée pour '{item_name_in_staging}'. Veuillez le mapper manuellement.", "warning")
        current_app.logger.warning(f"Aucune association trouvée pour release name '{item_name_in_staging}' lors du traitement automatique.")
        return redirect(url_for('seedbox_ui.index'))

    current_app.logger.info(f"Association trouvée by release name '{item_name_in_staging}' (Hash: {torrent_hash_of_assoc}): {association_data}")

    app_type = association_data.get('app_type')
    target_id = association_data.get('target_id') # Ceci est un string ou int, les handlers devraient gérer ça.

    if not app_type or target_id is None: # target_id peut être 0, donc vérifier None explicitement.
        flash(f"Association invalide ou incomplète pour '{item_name_in_staging}'. Type: {app_type}, ID: {target_id}", "danger")
        current_app.logger.error(f"Association invalide pour {item_name_in_staging}: app_type='{app_type}', target_id='{target_id}'")
        # On pourrait supprimer cette association invalide ici si on le souhaitait.
        # remove_pending_association(item_name_in_staging)
        return redirect(url_for('seedbox_ui.index'))

    result_dict = None
    # item_name_in_staging est le nom de base du fichier/dossier, qui est aussi la clé d'association.
    # path_to_cleanup_in_staging_after_success doit être le chemin absolu.
    path_to_cleanup_after_success_str = str(path_of_item_in_staging_abs)

    if app_type == 'sonarr':
        current_app.logger.debug(f"Appel de _handle_staged_sonarr_item pour {item_name_in_staging} (Série ID: {target_id})")
        result_dict = _handle_staged_sonarr_item(
            item_name_in_staging=item_name_in_staging, # Nom relatif au staging_dir
            series_id_target=str(target_id), # Assurer que c'est un string pour l'API Sonarr si besoin
            path_to_cleanup_in_staging_after_success=path_to_cleanup_after_success_str,
            user_chosen_season=None # Pas de saison forcée dans ce flux automatique
        )
    elif app_type == 'radarr':
        current_app.logger.debug(f"Appel de _handle_staged_radarr_item pour {item_name_in_staging} (Movie ID: {target_id})")
        result_dict = _handle_staged_radarr_item(
            item_name_in_staging=item_name_in_staging, # Nom relatif au staging_dir
            movie_id_target=str(target_id), # Assurer que c'est un string pour l'API Radarr si besoin
            path_to_cleanup_in_staging_after_success=path_to_cleanup_after_success_str
        )
    else:
        flash(f"Type d'application inconnu ('{app_type}') dans l'association pour '{item_name_in_staging}'.", "danger")
        current_app.logger.error(f"Type d'application non supporté '{app_type}' dans l'association pour {item_name_in_staging}.")
        return redirect(url_for('seedbox_ui.index'))

    if result_dict:
        current_app.logger.debug(f"Résultat du handler pour '{item_name_in_staging}': {result_dict}")
        if result_dict.get("success"):
            flash(result_dict.get("message", f"'{item_name_in_staging}' traité avec succès via son association."), "success")
            if torrent_hash_of_assoc: # Assure qu'on a un hash pour supprimer
                if torrent_map_manager.remove_torrent_from_map(torrent_hash_of_assoc):
                    current_app.logger.info(f"Association pour hash '{torrent_hash_of_assoc}' (Release: '{item_name_in_staging}') supprimée avec succès.")
                else:
                    current_app.logger.warning(f"Échec de la suppression de l'association pour hash '{torrent_hash_of_assoc}' (Release: '{item_name_in_staging}').")
            else:
                current_app.logger.warning(f"Aucun hash d'association trouvé pour '{item_name_in_staging}' pour suppression (ne devrait pas arriver si trouvée initialement).")
        elif result_dict.get("action_required"):
             flash(result_dict.get("message", f"Action supplémentaire requise pour '{item_name_in_staging}'."), "info")
             current_app.logger.info(f"Action requise retournée par le handler pour {item_name_in_staging}: {result_dict.get('message')}")
        else: # Échec
            flash(result_dict.get("error", f"Échec du traitement de '{item_name_in_staging}' via son association."), "danger")
    else:
        flash(f"Erreur inattendue lors du traitement de '{item_name_in_staging}'. Aucun résultat du handler.", "danger")
        current_app.logger.error(f"Aucun result_dict retourné par le handler pour {item_name_in_staging} avec app_type {app_type}.")

    return redirect(url_for('seedbox_ui.index'))

def _run_automated_processing_cycle():
    current_app.logger.info("Début du cycle de traitement automatisé.")
    processed_items_count = 0
    errors_count = 0

    # 1. Récupérer les configurations nécessaires
    rtorrent_label_sonarr = current_app.config.get('RTORRENT_LABEL_SONARR')
    rtorrent_label_radarr = current_app.config.get('RTORRENT_LABEL_RADARR')
    seedbox_sonarr_finished_path = current_app.config.get('SEEDBOX_SONARR_FINISHED_PATH')
    seedbox_radarr_finished_path = current_app.config.get('SEEDBOX_RADARR_FINISHED_PATH')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not all([rtorrent_label_sonarr, rtorrent_label_radarr, seedbox_sonarr_finished_path, seedbox_radarr_finished_path, staging_dir]):
        current_app.logger.error("Automatisation: Configuration manquante (labels rTorrent, chemins distants finis, ou staging_dir). Cycle annulé.")
        return {"success": False, "message": "Configuration manquante pour l'automatisation."}

    # 2. Lister les torrents depuis rTorrent
    torrents_from_rtorrent, error_msg_rtorrent = rtorrent_list_torrents_api()
    if error_msg_rtorrent:
        current_app.logger.error(f"Automatisation: Erreur rTorrent lors du listage: {error_msg_rtorrent}. Cycle annulé.")
        return {"success": False, "message": f"Erreur rTorrent: {error_msg_rtorrent}"}
    if not torrents_from_rtorrent:
        current_app.logger.info("Automatisation: Aucun torrent trouvé dans rTorrent.")
        return {"success": True, "message": "Aucun torrent dans rTorrent à traiter.", "processed_count": 0, "errors_count": 0}

    current_app.logger.info(f"Automatisation: {len(torrents_from_rtorrent)} torrent(s) récupéré(s) de rTorrent.")

    sftp_config = {
        'host': current_app.config.get('SEEDBOX_SFTP_HOST'),
        'port': int(current_app.config.get('SEEDBOX_SFTP_PORT', 22)),
        'user': current_app.config.get('SEEDBOX_SFTP_USER'),
        'password': current_app.config.get('SEEDBOX_SFTP_PASSWORD'),
    }
    if not sftp_config['host'] or not sftp_config['user'] or not sftp_config['password']: # Vérification plus spécifique
        current_app.logger.error("Automatisation: Configuration SFTP incomplète (hôte, utilisateur ou mot de passe manquant). Cycle annulé.")
        return {"success": False, "message": "Configuration SFTP incomplète."}

    for torrent_info in torrents_from_rtorrent:
        torrent_hash = torrent_info.get('hash')
        torrent_name_rtorrent = torrent_info.get('name')
        torrent_label = torrent_info.get('label')
        is_complete = torrent_info.get('is_complete', False)

        current_app.logger.debug(f"Automatisation: Examen du torrent: {torrent_name_rtorrent} (Hash: {torrent_hash}, Label: {torrent_label}, Complet: {is_complete})")

        if not is_complete:
            current_app.logger.debug(f"Automatisation: Torrent '{torrent_name_rtorrent}' non terminé. Ignoré.")
            continue

        if torrent_label not in [rtorrent_label_sonarr, rtorrent_label_radarr]:
            current_app.logger.debug(f"Automatisation: Torrent '{torrent_name_rtorrent}' n'a pas un label pertinent ('{torrent_label}'). Ignoré.")
            continue

        current_app.logger.info(f"Automatisation: Torrent pertinent trouvé: '{torrent_name_rtorrent}' (Hash: {torrent_hash}, Label: {torrent_label}).")

        association_data = torrent_map_manager.get_torrent_by_hash(torrent_hash)
        if not association_data:
            current_app.logger.warning(f"Automatisation: Aucune association trouvée pour le torrent terminé '{torrent_name_rtorrent}' (Hash: {torrent_hash}). Ignoré.")
            continue

        local_staged_item_name = association_data.get('release_name_expected_on_seedbox')
        if not local_staged_item_name:
            current_app.logger.error(f"Automatisation: 'release_name_expected_on_seedbox' est manquant ou vide dans l'association pour {torrent_hash} ('{torrent_name_rtorrent}'). Association data: {association_data}. Ignoré.")
            errors_count += 1
            continue

        current_app.logger.info(f"Automatisation: Association trouvée pour '{torrent_name_rtorrent}', release attendue: '{local_staged_item_name}'. Data: {association_data}")

        app_type = association_data.get('app_type')
        target_id = association_data.get('target_id')

        remote_base_path = ""
        if app_type == 'sonarr':
            remote_base_path = seedbox_sonarr_finished_path
        elif app_type == 'radarr':
            remote_base_path = seedbox_radarr_finished_path
        else:
            current_app.logger.error(f"Automatisation: Type d'application inconnu '{app_type}' dans l'association pour {torrent_name_rtorrent}. Ignoré.")
            errors_count += 1
            continue

        # Assurer que remote_base_path se termine par un / s'il n'est pas vide, pour la jonction avec Path
        if remote_base_path and not remote_base_path.endswith('/'):
            remote_base_path += '/'

        # remote_full_path_to_download still uses torrent_name_rtorrent, as that's the name on the remote
        remote_full_path_to_download = str(Path(remote_base_path) / torrent_name_rtorrent).replace('\\', '/')
        # local_staged_item_name is now taken from association data (release_name_expected_on_seedbox)
        local_staged_item_path_abs = Path(staging_dir) / local_staged_item_name

        current_app.logger.info(f"Automatisation: Préparation du téléchargement SFTP pour '{torrent_name_rtorrent}' (attendu localement comme '{local_staged_item_name}') depuis '{remote_full_path_to_download}' vers '{local_staged_item_path_abs}'.")

        sftp_client = None
        transport = None
        download_success = False
        try:
            transport = paramiko.Transport((sftp_config['host'], sftp_config['port']))
            transport.set_keepalive(60)
            transport.connect(username=sftp_config['user'], password=sftp_config['password'])
            sftp_client = paramiko.SFTPClient.from_transport(transport)
            current_app.logger.info(f"Automatisation: Connecté à SFTP pour télécharger '{torrent_name_rtorrent}'.")
            download_success = _download_sftp_item_recursive_local(sftp_client, remote_full_path_to_download, local_staged_item_path_abs, current_app.logger)
        except Exception as e_sftp:
            current_app.logger.error(f"Automatisation: Erreur SFTP lors du téléchargement de '{remote_full_path_to_download}': {e_sftp}", exc_info=True)
            errors_count += 1
            if sftp_client: sftp_client.close() # Fermer en cas d'erreur avant le finally
            if transport: transport.close()    # Fermer en cas d'erreur avant le finally
            continue
        finally:
            if sftp_client: sftp_client.close()
            if transport: transport.close()

        if not download_success:
            current_app.logger.error(f"Automatisation: Échec du téléchargement SFTP de '{remote_full_path_to_download}'. Passage au suivant.")
            if local_staged_item_path_abs.exists():
                if local_staged_item_path_abs.is_dir() and not any(local_staged_item_path_abs.iterdir()):
                    try: shutil.rmtree(local_staged_item_path_abs)
                    except Exception as e_rm: current_app.logger.error(f"Automatisation: Erreur nettoyage dossier staging partiel {local_staged_item_path_abs}: {e_rm}")
                elif local_staged_item_path_abs.is_file() and local_staged_item_path_abs.stat().st_size == 0:
                    try: local_staged_item_path_abs.unlink()
                    except Exception as e_rm: current_app.logger.error(f"Automatisation: Erreur nettoyage fichier staging partiel {local_staged_item_path_abs}: {e_rm}")
            errors_count += 1
            continue

        current_app.logger.info(f"Automatisation: Téléchargement de '{local_staged_item_name}' réussi.")

        handler_result = None
        if app_type == 'sonarr':
            handler_result = _handle_staged_sonarr_item(
                item_name_in_staging=local_staged_item_name,
                series_id_target=str(target_id), # Assurer string
                path_to_cleanup_in_staging_after_success=str(local_staged_item_path_abs),
                user_chosen_season=None
            )
        elif app_type == 'radarr':
            handler_result = _handle_staged_radarr_item(
                item_name_in_staging=local_staged_item_name,
                movie_id_target=str(target_id), # Assurer string
                path_to_cleanup_in_staging_after_success=str(local_staged_item_path_abs)
            )

        if handler_result and handler_result.get("success"):
            current_app.logger.info(f"Automatisation: Traitement de '{local_staged_item_name}' réussi: {handler_result.get('message')}")
            processed_items_count += 1
            if torrent_map_manager.remove_torrent_from_map(torrent_hash):
                current_app.logger.info(f"Automatisation: Association pour {torrent_hash} ('{torrent_name_rtorrent}') supprimée.")
            else:
                current_app.logger.warning(f"Automatisation: Échec de la suppression de l'association pour {torrent_hash} ('{torrent_name_rtorrent}').")
            # Optionnel: Suppression de rTorrent
            # from app.utils.rtorrent_client import delete_torrent as rtorrent_delete_torrent
            # success_delete_rt, msg_delete_rt = rtorrent_delete_torrent(torrent_hash, True) # True pour supprimer les données
            # if success_delete_rt:
            #    current_app.logger.info(f"Automatisation: Torrent '{torrent_name_rtorrent}' (Hash: {torrent_hash}) supprimé de rTorrent.")
            # else:
            #    current_app.logger.error(f"Automatisation: Échec de la suppression du torrent '{torrent_name_rtorrent}' de rTorrent: {msg_delete_rt}")
        else:
            error_detail = (handler_result.get('error', 'Erreur inconnue du handler') if handler_result else 'Pas de résultat du handler')
            current_app.logger.error(f"Automatisation: Échec du traitement de '{local_staged_item_name}'. Raison: {error_detail}")
            errors_count += 1

    current_app.logger.info(f"Cycle de traitement automatisé terminé. Items traités: {processed_items_count}, Erreurs: {errors_count}.")
    return {"success": True, "message": "Cycle de traitement automatisé terminé.", "processed_count": processed_items_count, "errors_count": errors_count}

@seedbox_ui_bp.route('/trigger-automatic-processing', methods=['POST'])
@login_required
def trigger_automatic_processing_route():
    # Pourrait ajouter une authentification/sécurité ici si nécessaire
    current_app.logger.info("Déclenchement du cycle de traitement automatisé via la route /trigger-automatic-processing.")
    result = _run_automated_processing_cycle()
    return jsonify(result)

@seedbox_ui_bp.route('/api/v1/process-staged-item', methods=['POST'])
@login_required
def api_process_staged_item():
    current_app.logger.info("Requête reçue sur /api/v1/process-staged-item")

    data = request.get_json()
    if not data:
        current_app.logger.error("API Process Staged: Aucune donnée JSON reçue ou malformée.")
        return jsonify({"success": False, "error": "Aucune donnée JSON reçue ou corps de requête malformé."}), 400

    item_name = data.get('item_name')
    if not item_name or not isinstance(item_name, str):
        current_app.logger.error(f"API Process Staged: 'item_name' manquant ou invalide dans JSON. Données: {data}")
        return jsonify({"success": False, "error": "Requête invalide. Le champ 'item_name' est manquant ou malformé."}), 400

    current_app.logger.info(f"API Process Staged: Traitement demandé pour l'item: '{item_name}'")

    staging_dir = current_app.config.get('STAGING_DIR')
    if not staging_dir:
        current_app.logger.error("API Process Staged: STAGING_DIR n'est pas configuré dans l'application.")
        # Cette erreur est côté serveur, donc 500 est plus approprié.
        return jsonify({"success": False, "error": "Configuration serveur incomplète (STAGING_DIR)."}), 500

    # Utiliser Path pour construire le chemin et normaliser
    # item_name pourrait contenir des sous-chemins ex: "dossier/fichier.mkv"
    # Path.resolve() n'est pas idéal ici car il peut échouer si une partie du chemin n'existe pas.
    # On veut joindre et normaliser pour la comparaison et la vérification d'existence.
    item_path = (Path(staging_dir) / item_name).resolve() # resolve() pour obtenir le chemin absolu canonique

    # Sécurité: Vérifier que le chemin résolu est bien DANS le staging_dir
    # Cela empêche les traversées de répertoire comme item_name = "../../../../etc/passwd"
    if not item_path.is_relative_to(Path(staging_dir).resolve()):
        current_app.logger.error(f"API Process Staged: Tentative d'accès hors du STAGING_DIR détectée pour '{item_name}'. Chemin résolu: {item_path}")
        return jsonify({"success": False, "error": "Chemin d'accès invalide."}), 400

    if not item_path.exists():
        current_app.logger.warning(f"API Process Staged: Item '{item_name}' (chemin: {item_path}) non trouvé dans le répertoire de staging.")
        return jsonify({"success": False, "error": f"Item '{item_name}' non trouvé dans le répertoire de staging."}), 404

    # --- Logique de traitement de l'item ---
    current_app.logger.info(f"API Process Staged: Recherche d'association pour '{item_name}'.")
    torrent_hash, association_data = torrent_map_manager.find_torrent_by_release_name(item_name)

    if association_data:
        current_app.logger.info(f"API Process Staged: Association trouvée pour '{item_name}'. Hash: {torrent_hash}, Data: {association_data}")
        app_type = association_data.get('app_type')
        target_id = association_data.get('target_id')

        # path_to_cleanup_in_staging_after_success est le chemin absolu de l'item dans le staging.
        path_to_cleanup_in_staging_after_success = str(item_path)

        if not app_type or target_id is None: # target_id peut être 0 pour certaines applications, donc None est la bonne vérification
            current_app.logger.error(f"API Process Staged: Association corrompue pour '{item_name}'. app_type='{app_type}', target_id='{target_id}'.")
            return jsonify({"success": False, "error": f"Association de données corrompue ou incomplète trouvée pour '{item_name}'. Traitement annulé."}), 200 # 200 avec success:false

        result_dict = None
        if app_type == 'sonarr':
            current_app.logger.info(f"API Process Staged: Appel du handler Sonarr pour '{item_name}', target_id: {target_id}")
            result_dict = _handle_staged_sonarr_item(
                item_name_in_staging=item_name, # item_name est le nom de base/relatif au staging dir
                series_id_target=str(target_id),
                path_to_cleanup_in_staging_after_success=path_to_cleanup_in_staging_after_success,
                user_chosen_season=None
            )
        elif app_type == 'radarr':
            current_app.logger.info(f"API Process Staged: Appel du handler Radarr pour '{item_name}', target_id: {target_id}")
            result_dict = _handle_staged_radarr_item(
                item_name_in_staging=item_name, # item_name est le nom de base/relatif au staging dir
                movie_id_target=str(target_id),
                path_to_cleanup_in_staging_after_success=path_to_cleanup_in_staging_after_success
            )
        else:
            current_app.logger.error(f"API Process Staged: Type d'application inconnu '{app_type}' dans l'association pour '{item_name}'.")
            return jsonify({"success": False, "error": f"Type d'application inconnu '{app_type}' dans l'association pour '{item_name}'."}), 200 # 200 avec success:false

        if result_dict:
            if result_dict.get("success"):
                current_app.logger.info(f"API Process Staged: Handler pour '{item_name}' (type: {app_type}) réussi. Message: {result_dict.get('message')}")
                if torrent_hash: # Seulement si un hash existait pour cette association par nom
                    if torrent_map_manager.remove_torrent_from_map(torrent_hash):
                        current_app.logger.info(f"API Process Staged: Association pour hash '{torrent_hash}' (item: '{item_name}') supprimée avec succès.")
                    else:
                        current_app.logger.warning(f"API Process Staged: Échec de la suppression de l'association pour hash '{torrent_hash}' (item: '{item_name}').")
                else: # Si get_association_by_release_name ne retourne pas de hash (ce qui serait inhabituel)
                    current_app.logger.warning(f"API Process Staged: Aucun torrent_hash retourné par get_association_by_release_name pour '{item_name}', donc suppression de l'association par hash non tentée.")

                return jsonify({
                    "success": True,
                    "message": result_dict.get("message", f"Item '{item_name}' traité et déplacé avec succès via l'API."),
                    "details": result_dict
                }), 200
            else: # Échec du handler
                current_app.logger.error(f"API Process Staged: Handler pour '{item_name}' (type: {app_type}) a échoué. Erreur: {result_dict.get('error')}")
                return jsonify({
                    "success": False,
                    "error": result_dict.get("error", f"Échec du traitement de l'item '{item_name}' par le handler."),
                    "details": result_dict
                }), 200 # 200 avec success:false pour que le client traite la réponse
        else: # result_dict est None
            current_app.logger.error(f"API Process Staged: Erreur interne critique. Le handler pour '{app_type}' n'a pas retourné de dictionnaire de résultat pour '{item_name}'.")
            return jsonify({"success": False, "error": "Erreur interne du serveur : le handler approprié n'a pas retourné de résultat."}), 500
    else:
        current_app.logger.info(f"API Process Staged: Aucune pré-association trouvée pour '{item_name}'. L'item est prêt pour un mappage manuel si nécessaire.")
        return jsonify({
            "success": True, # La requête API elle-même a réussi
            "status": "pending_manual_import",
            "message": f"Item '{item_name}' validé par l'API. Aucune pré-association trouvée. Traitement manuel ou via une autre interface requis.",
            "item_path_validated": str(item_path)
        }), 202 # HTTP 202 Accepted - indique que la requête est valide mais nécessite une action ultérieure
# ==============================================================================
# ROUTE POUR LE MAPPING GROUPÉ VERS UNE SÉRIE SONARR
# ==============================================================================
@seedbox_ui_bp.route('/batch-map-to-sonarr-series', methods=['POST']) # Nom de fonction cohérent avec l'endpoint
@login_required
def batch_map_to_sonarr_series_action():
    logger = current_app.logger
    data = request.get_json()

    if not data:
        logger.error("Batch Map Sonarr: Aucune donnée JSON reçue.")
        return jsonify({"success": False, "error": "Aucune donnée JSON reçue."}), 400

    item_names_in_staging = data.get('item_names') # Liste de noms d'items (path_for_actions)
    series_id_target_str = data.get('series_id')

    if not isinstance(item_names_in_staging, list) or not item_names_in_staging:
        logger.error(f"Batch Map Sonarr: 'item_names' manquants ou n'est pas une liste. Reçu: {item_names_in_staging}")
        return jsonify({"success": False, "error": "'item_names' est requis et doit être une liste non vide."}), 400

    if not series_id_target_str:
        logger.error("Batch Map Sonarr: 'series_id' manquant.")
        return jsonify({"success": False, "error": "'series_id' est requis."}), 400

    try:
        series_id_target = int(series_id_target_str)
    except ValueError:
        logger.error(f"Batch Map Sonarr: 'series_id' invalide: {series_id_target_str}. Doit être un entier.")
        return jsonify({"success": False, "error": "Format de series_id invalide."}), 400

    logger.info(f"Batch Map Sonarr: Traitement de {len(item_names_in_staging)} items pour la série ID {series_id_target}.")

    staging_dir = current_app.config.get('STAGING_DIR')
    if not staging_dir:
        logger.error("Batch Map Sonarr: STAGING_DIR non configuré.")
        return jsonify({"success": False, "error": "Configuration serveur incomplète (STAGING_DIR)."}), 500

    successful_imports = 0
    failed_imports_details = [] # Pour stocker les détails des échecs

    for item_name in item_names_in_staging:
        logger.info(f"Batch Map Sonarr: Traitement de l'item '{item_name}' pour la série {series_id_target}.")

        full_staging_path_str = str((Path(staging_dir) / item_name).resolve())
        if not os.path.exists(full_staging_path_str):
            logger.warning(f"Batch Map Sonarr: Item '{item_name}' non trouvé dans le staging à '{full_staging_path_str}'. Ignoré.")
            failed_imports_details.append({"item": item_name, "reason": "Non trouvé dans le staging"})
            continue

        # Vérifier s'il y a une pré-association existante pour cet item et la traiter/supprimer
        # find_torrent_by_release_name utilise le nom de la release (qui est item_name ici)
        torrent_hash_existing, existing_assoc = torrent_map_manager.find_torrent_by_release_name(item_name)

        if existing_assoc:
            logger.info(f"Batch Map Sonarr: L'item '{item_name}' a une pré-association existante (Hash: {torrent_hash_existing}). Elle sera utilisée/remplacée.")
            # Le _handle_staged_sonarr_item, s'il reçoit ce torrent_hash_existing,
            # mettra à jour le statut à "imported_by_mms" ou supprimera l'entrée si configuré.
        else:
            torrent_hash_existing = None # Pas d'association à nettoyer spécifiquement par hash plus tard

        # Appeler le helper _handle_staged_sonarr_item
        # automated_import=False car c'est une action manuelle, mais on ne veut pas d'interaction pour la saison ici.
        # Le helper doit essayer de parser la saison. Si on voulait plus de contrôle, il faudrait une UI pour chaque item.
        # Pour le batch, on se fie au parsing automatique ou à Sonarr.
        result_dict = _handle_staged_sonarr_item(
            item_name_in_staging=item_name,
            series_id_target=series_id_target, # Déjà un entier
            path_to_cleanup_in_staging_after_success=full_staging_path_str,
            user_chosen_season=None, # Pas de saison forcée pour le batch pour l'instant
            automated_import=False, # Action manuelle, mais le helper gère le retour JSON
            torrent_hash_for_status_update=torrent_hash_existing # Pour nettoyer l'ancienne association
        )

        if result_dict.get("success"):
            successful_imports += 1
            logger.info(f"Batch Map Sonarr: Succès pour '{item_name}'. Message: {result_dict.get('message')}")
            # Si une association existait et que le nettoyage du map est activé dans le helper (ou que le statut est mis à imported), c'est géré.
            # Si vous voulez explicitement supprimer l'association ici après un succès de _handle_staged_sonarr_item:
            if torrent_hash_existing:
                 if torrent_map_manager.remove_torrent_from_map(torrent_hash_existing):
                     logger.info(f"Batch Map Sonarr: Association pour '{item_name}' (Hash: {torrent_hash_existing}) supprimée après import réussi.")
                 else: # Peut arriver si _handle_staged_sonarr_item l'a déjà supprimée via son propre remove_torrent_from_map
                     logger.info(f"Batch Map Sonarr: Association pour '{item_name}' (Hash: {torrent_hash_existing}) non trouvée pour suppression (peut-être déjà traitée).")
        else:
            logger.error(f"Batch Map Sonarr: Échec pour '{item_name}'. Raison: {result_dict.get('message', 'Erreur inconnue du handler')}")
            failed_imports_details.append({"item": item_name, "reason": result_dict.get('message', 'Erreur inconnue')})

    total_items = len(item_names_in_staging)
    final_message = f"Traitement groupé terminé. {successful_imports}/{total_items} items importés avec succès."
    if failed_imports_details:
        final_message += f" {len(failed_imports_details)} items ont échoué ou nécessité une attention."
        # Vous pourriez inclure failed_imports_details dans la réponse si le JS peut l'afficher.

    logger.info(final_message)
    return jsonify({
        "success": True, # La route elle-même a fonctionné, même s'il y a des échecs partiels
        "message": final_message,
        "processed_count": successful_imports,
        "errors_count": len(failed_imports_details),
        "error_details": failed_imports_details # Pour un logging JS plus détaillé si besoin
    }), 200

# ==============================================================================
# ROUTES POUR LA GESTION DES ITEMS PROBLÉMATIQUES DU PENDING_TORRENTS_MAP
# ==============================================================================

@seedbox_ui_bp.route('/problematic-import/retry/<string:torrent_hash>', methods=['POST'])
@login_required
def retry_problematic_import_action(torrent_hash):
    logger = current_app.logger
    logger.info(f"Tentative de relance de l'import pour le torrent hash: {torrent_hash}")

    association_data = torrent_map_manager.get_torrent_by_hash(torrent_hash)
    if not association_data:
        flash(f"Association non trouvée pour le hash {torrent_hash}.", "danger")
        return redirect(url_for('seedbox_ui.index'))

    item_name_in_staging = association_data.get('release_name')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not item_name_in_staging or not staging_dir or not (Path(staging_dir) / item_name_in_staging).exists():
        flash(f"L'item '{item_name_in_staging or 'Inconnu'}' n'est plus dans le staging ou informations manquantes. Impossible de réessayer.", "warning")
        if torrent_hash: # S'assurer qu'on a un hash pour mettre à jour le statut
            torrent_map_manager.update_torrent_status_in_map(torrent_hash, "error_retry_failed_item_not_in_staging", "Item non trouvé dans le staging pour la relance.")
        return redirect(url_for('seedbox_ui.index'))

    logger.info(f"Relance du traitement pour : '{item_name_in_staging}', Hash: {torrent_hash}")
    # Mise à jour du statut avant de tenter le traitement
    torrent_map_manager.update_torrent_status_in_map(torrent_hash, "processing_by_mms_retry", f"Relance manuelle pour {item_name_in_staging}")

    full_staging_path_str = str((Path(staging_dir) / item_name_in_staging).resolve())
    result_from_handler = {}
    app_type = association_data.get('app_type')
    target_id = association_data.get('target_id')

    if app_type == 'sonarr':
        result_from_handler = _handle_staged_sonarr_item(
            item_name_in_staging=item_name_in_staging,
            series_id_target=target_id,
            path_to_cleanup_in_staging_after_success=full_staging_path_str,
            automated_import=True,
            torrent_hash_for_status_update=torrent_hash
        )
    elif app_type == 'radarr':
        result_from_handler = _handle_staged_radarr_item(
            item_name_in_staging=item_name_in_staging,
            movie_id_target=target_id,
            path_to_cleanup_in_staging_after_success=full_staging_path_str,
            automated_import=True,
            torrent_hash_for_status_update=torrent_hash
        )
    else:
        flash(f"Type d'application inconnu '{app_type}' pour la relance.", "danger")
        if torrent_hash: # S'assurer qu'on a un hash
            torrent_map_manager.update_torrent_status_in_map(torrent_hash, "error_unknown_association_type", "Type d'app inconnu lors de la relance.")
        return redirect(url_for('seedbox_ui.index'))

    if result_from_handler.get("success"):
        flash(f"Relance pour '{item_name_in_staging}' réussie: {result_from_handler.get('message')}", "success")
        # Le helper aura mis à jour/supprimé l'entrée du map si le nettoyage du map est activé après succès.
        # S'il ne supprime pas, le statut "imported_by_mms" sera mis, donc il n'apparaîtra plus dans la liste "attention".
    elif result_from_handler.get("manual_required"):
        flash(f"Relance pour '{item_name_in_staging}' nécessite une attention manuelle: {result_from_handler.get('message')}", "warning")
    else:
        flash(f"Échec de la relance pour '{item_name_in_staging}': {result_from_handler.get('message', 'Erreur inconnue')}", "danger")

    return redirect(url_for('seedbox_ui.index'))


@seedbox_ui_bp.route('/problematic-association/delete/<string:torrent_hash>', methods=['POST'])
@login_required
def delete_problematic_association_action(torrent_hash):
    logger = current_app.logger
    logger.info(f"Demande de suppression de l'association pour le torrent hash: {torrent_hash}")

    association_data = torrent_map_manager.get_torrent_by_hash(torrent_hash)
    release_name_for_flash = association_data.get('release_name', 'Hash Inconnu') if association_data else f"Hash: {torrent_hash}"

    if torrent_map_manager.remove_torrent_from_map(torrent_hash):
        flash(f"L'association pour '{release_name_for_flash}' a été supprimée.", "success")
        logger.info(f"Association pour hash {torrent_hash} ('{release_name_for_flash}') supprimée avec succès.")
    else:
        # Si get_torrent_by_hash a retourné None, remove_torrent_from_map retournera False car le hash n'est pas trouvé.
        flash(f"Impossible de trouver ou de supprimer l'association pour '{release_name_for_flash}'.", "danger")
        logger.warning(f"Tentative de suppression d'une association inexistante ou échec pour hash {torrent_hash} ('{release_name_for_flash}').")

    return redirect(url_for('seedbox_ui.index'))
if __name__ == '__main__':
    app = create_app() # Ou comment vous créez votre instance d'app

    print("\n" + "="*30 + " Routes Enregistrées " + "="*30)
    for rule in app.url_map.iter_rules():
        print(f"Endpoint: {rule.endpoint:<30} Methods: {str(list(rule.methods)):<30} URL: {str(rule)}")
    print("="*80 + "\n")

    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False) # Mettez use_reloader=False pour ce test pour être sûr
# ==============================================================================
# ROUTE POUR LE RAPATRIEMENT SFTP GROUPÉ DEPUIS LA SEEDBOX
# ==============================================================================
@seedbox_ui_bp.route('/sftp-batch-download', methods=['POST'])
@login_required
def sftp_batch_download_action():
    logger = current_app.logger
    data = request.get_json()

    if not data:
        logger.error("SFTP Batch Download: Aucune donnée JSON reçue.")
        return jsonify({"success": False, "error": "Aucune donnée JSON reçue."}), 400

    remote_paths_to_download = data.get('remote_paths') # Liste de chemins POSIX complets
    app_type_context = data.get('app_type_context') # 'sonarr', 'radarr', etc. (optionnel, pour info/log)

    if not isinstance(remote_paths_to_download, list) or not remote_paths_to_download:
        logger.error(f"SFTP Batch Download: 'remote_paths' manquants ou n'est pas une liste. Reçu: {remote_paths_to_download}")
        return jsonify({"success": False, "error": "'remote_paths' est requis et doit être une liste non vide."}), 400

    logger.info(f"SFTP Batch Download: Rapatriement demandé pour {len(remote_paths_to_download)} items. Contexte: {app_type_context}")

    sftp_host = current_app.config.get('SEEDBOX_SFTP_HOST')
    sftp_port_str = current_app.config.get('SEEDBOX_SFTP_PORT') # Peut être None ou string
    sftp_user = current_app.config.get('SEEDBOX_SFTP_USER')
    sftp_password = current_app.config.get('SEEDBOX_SFTP_PASSWORD')
    local_staging_dir_str = current_app.config.get('STAGING_DIR')

    if not all([sftp_host, sftp_port_str, sftp_user, sftp_password, local_staging_dir_str]):
        logger.error("SFTP Batch Download: Configuration SFTP ou staging_dir manquante.")
        return jsonify({"success": False, "error": "Configuration serveur incomplète."}), 500

    try:
        sftp_port = int(sftp_port_str)
    except (ValueError, TypeError):
        logger.error(f"SFTP Batch Download: Port SFTP invalide '{sftp_port_str}'. Doit être un nombre.")
        return jsonify({"success": False, "error": "Configuration du port SFTP invalide."}), 500

    local_staging_dir_pathobj = Path(local_staging_dir_str)

    sftp_client = None
    transport = None
    successful_downloads_count = 0
    failed_downloads_count = 0
    downloaded_item_names_for_mms_processing = [] # Pour appeler l'API MMS après

    try:
        logger.debug(f"SFTP Batch Download: Connexion à {sftp_host}:{sftp_port}")
        transport = paramiko.Transport((sftp_host, sftp_port))
        transport.set_keepalive(60)
        transport.connect(username=sftp_user, password=sftp_password)
        sftp_client = paramiko.SFTPClient.from_transport(transport)
        logger.info(f"SFTP Batch Download: Connecté à {sftp_host}.")

        for remote_path_posix in remote_paths_to_download:
            item_basename_on_seedbox = Path(remote_path_posix).name
            local_destination_for_item_pathobj = local_staging_dir_pathobj / item_basename_on_seedbox

            logger.info(f"SFTP Batch Download: Tentative de téléchargement de '{remote_path_posix}' vers '{local_destination_for_item_pathobj}'")

            # Réutiliser votre helper de téléchargement SFTP
            # _download_sftp_item_recursive_local(sftp_client, remote_path_posix, local_destination_for_item_pathobj, logger_instance)
            # Assurez-vous que _download_sftp_item_recursive_local est défini ou importé correctement.
            # Si elle est définie dans le même fichier, pas besoin d'import.
            if _download_sftp_item_recursive_local(sftp_client, remote_path_posix, local_destination_for_item_pathobj, logger):
                logger.info(f"SFTP Batch Download: Succès du téléchargement de '{item_basename_on_seedbox}'.")
                successful_downloads_count += 1
                downloaded_item_names_for_mms_processing.append(item_basename_on_seedbox)
            else:
                logger.error(f"SFTP Batch Download: Échec du téléchargement de '{item_basename_on_seedbox}' depuis '{remote_path_posix}'.")
                failed_downloads_count += 1
                # Nettoyer un téléchargement partiel si nécessaire (votre helper le fait peut-être déjà)
                if local_destination_for_item_pathobj.exists():
                    if local_destination_for_item_pathobj.is_dir() and not any(local_destination_for_item_pathobj.iterdir()):
                        try: shutil.rmtree(local_destination_for_item_pathobj)
                        except Exception as e_rm: logger.warning(f"SFTP Batch Download: Échec nettoyage partiel dossier {local_destination_for_item_pathobj}: {e_rm}")
                    elif local_destination_for_item_pathobj.is_file() and local_destination_for_item_pathobj.stat().st_size == 0:
                        try: local_destination_for_item_pathobj.unlink()
                        except Exception as e_rm: logger.warning(f"SFTP Batch Download: Échec nettoyage partiel fichier {local_destination_for_item_pathobj}: {e_rm}")

    except paramiko.ssh_exception.AuthenticationException as e_auth:
        logger.error(f"SFTP Batch Download: Erreur d'authentification SFTP: {e_auth}")
        return jsonify({"success": False, "error": "Erreur d'authentification SFTP."}), 401 # Unauthorized
    except Exception as e_sftp_connect:
        logger.error(f"SFTP Batch Download: Erreur de connexion SFTP ou autre: {e_sftp_connect}", exc_info=True)
        return jsonify({"success": False, "error": f"Erreur SFTP: {str(e_sftp_connect)}"}), 500
    finally:
        if sftp_client: sftp_client.close()
        if transport: transport.close()
        logger.debug("SFTP Batch Download: Connexion SFTP fermée.")

    # --- APRÈS LA BOUCLE DE TÉLÉCHARGEMENT, NOTIFIER MMS POUR CHAQUE ITEM TÉLÉCHARGÉ ---
    mms_notifications_sent = 0
    mms_notifications_failed = 0
    if downloaded_item_names_for_mms_processing:
        logger.info(f"SFTP Batch Download: {len(downloaded_item_names_for_mms_processing)} items téléchargés. Notification à MMS pour traitement...")
        mms_api_url = current_app.config.get('MMS_API_PROCESS_STAGING_URL') # URL de votre API MMS
        if not mms_api_url:
            logger.error("SFTP Batch Download: MMS_API_PROCESS_STAGING_URL non configurée. Impossible de notifier MMS.")
            # Les items sont téléchargés mais MMS ne sera pas notifié.
        else:
            for item_name_to_process in downloaded_item_names_for_mms_processing:
                logger.debug(f"SFTP Batch Download: Notification à MMS pour '{item_name_to_process}'...")
                try:
                    payload_mms = {"item_name_in_staging": item_name_to_process}
                    headers_mms = {"Content-Type": "application/json"}
                    # Ajoutez un token d'auth si votre API MMS le requiert
                    # mms_api_token = current_app.config.get('SFTPSCRIPT_API_TOKEN')
                    # if mms_api_token: headers_mms['Authorization'] = f"Bearer {mms_api_token}"

                    response_mms = requests.post(mms_api_url, json=payload_mms, headers=headers_mms, timeout=60)
                    response_mms.raise_for_status() # Vérifier les erreurs HTTP
                    logger.info(f"SFTP Batch Download: Notification à MMS pour '{item_name_to_process}' réussie. Réponse MMS: {response_mms.status_code} - {response_mms.json()}")
                    mms_notifications_sent +=1
                except Exception as e_mms_notify:
                    logger.error(f"SFTP Batch Download: Échec de la notification à MMS pour '{item_name_to_process}': {e_mms_notify}")
                    mms_notifications_failed +=1

    final_message = f"Rapatriement groupé : {successful_downloads_count} téléchargé(s) avec succès, {failed_downloads_count} échec(s) de téléchargement."
    if mms_notifications_sent > 0 or mms_notifications_failed > 0:
        final_message += f" Notifications MMS : {mms_notifications_sent} envoyée(s), {mms_notifications_failed} échec(s)."

    logger.info(f"SFTP Batch Download: Fin. {final_message}")
    return jsonify({
        "success": True, # La route elle-même a terminé son travail
        "message": final_message,
        "successful_downloads": successful_downloads_count,
        "failed_downloads": failed_downloads_count,
        "mms_notifications_sent": mms_notifications_sent,
        "mms_notifications_failed": mms_notifications_failed
    }), 200


# ==============================================================================
# --- ROUTES POUR LA GESTION DES FILES D'ATTENTE SONARR/RADARR ---
# ==============================================================================

@seedbox_ui_bp.route('/queue-manager')
@login_required
def queue_manager_view():
    logger.info("Accès à la page de gestion des files d'attente Sonarr/Radarr.")
    sonarr_queue_data = None
    radarr_queue_data = None
    sonarr_error = None
    radarr_error = None

    # Récupération file d'attente Sonarr
    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    if sonarr_url and sonarr_api_key:
        sonarr_api_endpoint = f"{sonarr_url.rstrip('/')}/api/v3/queue"
        # Le endpoint /api/v3/queue de Sonarr peut prendre des paramètres comme page, pageSize, includeUnknownSeriesItems, includeSeries, includeEpisode
        # Par défaut, il retourne une page. Pour tout avoir, il faudrait paginer ou augmenter pageSize.
        # Sonarr V3 retourne un objet avec une clé "records" qui est la liste.
        # Ex: {'page': 1, 'pageSize': 10, 'sortKey': 'timeleft', 'sortDirection': 'ascending', 'totalRecords': 5, 'records': [...]}
        # On va essayer de récupérer plus d'items par défaut.
        params_sonarr = {'pageSize': 200, 'includeSeries': 'true', 'includeEpisode': 'true'} # Augmenter pageSize
        data, error = _make_arr_request('GET', sonarr_api_endpoint, sonarr_api_key, params=params_sonarr)
        if error:
            sonarr_error = f"Erreur Sonarr: {error}"
            logger.error(f"QueueManager: {sonarr_error}")
        elif data and isinstance(data, dict) and 'records' in data:
            sonarr_queue_data = data # On passe tout l'objet, le template accédera à .records
            logger.info(f"QueueManager: {len(sonarr_queue_data.get('records', []))} items récupérés de la file d'attente Sonarr.")
        else:
            sonarr_error = "Réponse inattendue de l'API Sonarr (pas de clé 'records' ou format incorrect)."
            logger.error(f"QueueManager: {sonarr_error} - Données reçues: {data}")
    else:
        sonarr_error = "Sonarr n'est pas configuré."
        logger.warning(f"QueueManager: {sonarr_error}")

    # Récupération file d'attente Radarr
    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    if radarr_url and radarr_api_key:
        radarr_api_endpoint = f"{radarr_url.rstrip('/')}/api/v3/queue"
        # Similaire à Sonarr, Radarr V3 retourne aussi un objet avec "records".
        params_radarr = {'pageSize': 200, 'includeMovie': 'true', 'includeUnknownMovieItems': 'true'}
        data, error = _make_arr_request('GET', radarr_api_endpoint, radarr_api_key, params=params_radarr)
        if error:
            radarr_error = f"Erreur Radarr: {error}"
            logger.error(f"QueueManager: {radarr_error}")
        elif data and isinstance(data, dict) and 'records' in data:
            radarr_queue_data = data
            logger.info(f"QueueManager: {len(radarr_queue_data.get('records', []))} items récupérés de la file d'attente Radarr.")
        else:
            radarr_error = "Réponse inattendue de l'API Radarr (pas de clé 'records' ou format incorrect)."
            logger.error(f"QueueManager: {radarr_error} - Données reçues: {data}")
    else:
        radarr_error = "Radarr n'est pas configuré."
        logger.warning(f"QueueManager: {radarr_error}")

    return render_template('seedbox_ui/queue_manager.html',
                           sonarr_queue_data=sonarr_queue_data,
                           radarr_queue_data=radarr_queue_data,
                           sonarr_error=sonarr_error,
                           radarr_error=radarr_error)

@seedbox_ui_bp.route('/queue/sonarr/delete', methods=['POST'])
@login_required
def delete_sonarr_queue_items():
    logger.info("Demande de suppression d'items de la file d'attente Sonarr.")
    selected_ids = request.form.getlist('selected_item_ids')
    # Récupérer l'état de la case à cocher. Si elle n'est pas cochée, la clé ne sera pas dans request.form.
    remove_from_client_flag_str = request.form.get('removeFromClientSonarr', 'false') # défaut à 'false' string si non présent
    remove_from_client = remove_from_client_flag_str.lower() == 'true'

    logger.info(f"Suppression items Sonarr. IDs: {selected_ids}, removeFromClient: {remove_from_client}")

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')

    if not sonarr_url or not sonarr_api_key:
        flash("Sonarr n'est pas configuré.", 'danger')
        return redirect(url_for('seedbox_ui.queue_manager_view', _anchor='sonarr-tab'))

    if not selected_ids:
        flash("Aucun item Sonarr sélectionné pour la suppression.", 'warning')
        return redirect(url_for('seedbox_ui.queue_manager_view', _anchor='sonarr-tab'))

    success_count = 0
    error_count = 0

    for item_id in selected_ids:
        api_endpoint = f"{sonarr_url.rstrip('/')}/api/v3/queue/{item_id}"
        # Convertir le booléen Python en chaîne 'true'/'false' pour l'API
        params = {
            'removeFromClient': str(remove_from_client).lower(),
            'blocklist': 'false'
        }
        logger.debug(f"Appel DELETE Sonarr: {api_endpoint} avec params: {params}")
        response_status, error_msg = _make_arr_request('DELETE', api_endpoint, sonarr_api_key, params=params)

        if error_msg: # S'il y a une erreur de communication ou une réponse 4xx/5xx gérée par _make_arr_request
            logger.error(f"Erreur suppression item Sonarr ID {item_id}: {error_msg}")
            error_count += 1
        elif response_status is True or (isinstance(response_status, dict) and response_status.get('status') == 'success'): # Succès
            # Sonarr DELETE /queue/{id} retourne 200 OK avec un corps vide en cas de succès.
            # _make_arr_request retourne True dans ce cas.
            logger.info(f"Item Sonarr ID {item_id} supprimé de la file d'attente avec succès.")
            success_count += 1
        else: # Cas inattendu où response_status n'est ni True ni une erreur gérée
            logger.error(f"Réponse inattendue lors de la suppression de l'item Sonarr ID {item_id}. Statut/Réponse: {response_status}")
            error_count += 1

    if success_count > 0:
        flash(f"{success_count} item(s) supprimé(s) de la file d'attente Sonarr.", 'success')
    if error_count > 0:
        flash(f"Échec de la suppression de {error_count} item(s) de la file d'attente Sonarr. Consultez les logs.", 'danger')

    return redirect(url_for('seedbox_ui.queue_manager_view', _anchor='sonarr-tab'))


@seedbox_ui_bp.route('/queue/radarr/delete', methods=['POST'])
@login_required
def delete_radarr_queue_items():
    logger.info("Demande de suppression d'items de la file d'attente Radarr.")
    selected_ids = request.form.getlist('selected_item_ids')
    remove_from_client_flag_str = request.form.get('removeFromClientRadarr', 'false')
    remove_from_client = remove_from_client_flag_str.lower() == 'true'

    logger.info(f"Suppression items Radarr. IDs: {selected_ids}, removeFromClient: {remove_from_client}")

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')

    if not radarr_url or not radarr_api_key:
        flash("Radarr n'est pas configuré.", 'danger')
        return redirect(url_for('seedbox_ui.queue_manager_view', _anchor='radarr-tab'))

    if not selected_ids:
        flash("Aucun item Radarr sélectionné pour la suppression.", 'warning')
        return redirect(url_for('seedbox_ui.queue_manager_view', _anchor='radarr-tab'))

    success_count = 0
    error_count = 0

    for item_id in selected_ids:
        api_endpoint = f"{radarr_url.rstrip('/')}/api/v3/queue/{item_id}"
        params = {
            'removeFromClient': str(remove_from_client).lower(),
            'blacklist': 'false'  # Radarr utilise 'blacklist' et non 'blocklist'
        }
        logger.debug(f"Appel DELETE Radarr: {api_endpoint} avec params: {params}")
        response_status, error_msg = _make_arr_request('DELETE', api_endpoint, radarr_api_key, params=params)

        if error_msg:
            logger.error(f"Erreur suppression item Radarr ID {item_id}: {error_msg}")
            error_count += 1
        elif response_status is True or (isinstance(response_status, dict) and response_status.get('status') == 'success'): # Succès
            # Radarr DELETE /queue/{id} retourne 200 OK avec un corps vide.
            logger.info(f"Item Radarr ID {item_id} supprimé de la file d'attente avec succès.")
            success_count += 1
        else:
            logger.error(f"Réponse inattendue lors de la suppression de l'item Radarr ID {item_id}. Statut/Réponse: {response_status}")
            error_count += 1

    if success_count > 0:
        flash(f"{success_count} item(s) supprimé(s) de la file d'attente Radarr.", 'success')
    if error_count > 0:
        flash(f"Échec de la suppression de {error_count} item(s) de la file d'attente Radarr. Consultez les logs.", 'danger')

    return redirect(url_for('seedbox_ui.queue_manager_view', _anchor='radarr-tab'))