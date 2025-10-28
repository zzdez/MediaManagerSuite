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
from threading import Thread
# --- Imports spécifiques à l'application MediaManagerSuite ---
from app.auth import internal_api_required
from app.utils import staging_processor, sftp_scanner
from app.utils.arr_client import search_sonarr_by_title, search_radarr_by_title
from app.utils.tvdb_client import CustomTVDBClient
from app.utils.tmdb_client import TheMovieDBClient

# Client rTorrent
from app.utils.rtorrent_client import (
    _decode_bencode_name,  # <--- AJOUTEZ CETTE LIGNE
    list_torrents as rtorrent_list_torrents_api,
    add_magnet as rtorrent_add_magnet_httprpc,
    add_torrent_file as rtorrent_add_torrent_file_httprpc,
    get_torrent_hash_by_name as rtorrent_get_hash_by_name,
    delete_torrent as rtorrent_delete_torrent_api,
    get_torrent_files as rtorrent_get_files_api,
)

# Clients Sonarr/Radarr (pour l'ajout de nouveaux médias)
from app.utils.arr_client import add_new_series_to_sonarr, add_new_movie_to_radarr

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

def _translate_rtorrent_path_to_sftp_path(rtorrent_path, app_type):
    """
    Traduit un chemin rTorrent pour un item TERMINÉ en chemin SFTP.
    """
    logger = current_app.logger
    if not rtorrent_path:
        logger.warning("Le chemin rTorrent en entrée est None. Impossible de traduire.")
        return None

    logger.debug(f"Traduction du chemin rTorrent '{rtorrent_path}' pour le type '{app_type}'")

    # On utilise le mapping global pour la partie racine du chemin
    path_mapping_str = current_app.config.get('SEEDBOX_SFTP_REMOTE_PATH_MAPPING')
    if path_mapping_str:
        parts = path_mapping_str.split(',')
        if len(parts) == 2:
            to_remove = parts[0].strip()
            to_add = parts[1].strip()
            if rtorrent_path.startswith(to_remove):
                translated_path = rtorrent_path.replace(to_remove, to_add, 1)
                translated_path = Path(translated_path).as_posix()
                logger.info(f"Chemin rTorrent '{rtorrent_path}' traduit en chemin SFTP '{translated_path}'")
                return translated_path

    # Fallback si le mapping n'est pas défini ou ne correspond pas
    logger.warning(f"Impossible de traduire le chemin rTorrent '{rtorrent_path}' via le mapping global. Vérifiez SEEDBOX_SFTP_REMOTE_PATH_MAPPING.")
    return None

# Minimal bencode parser function (copied from previous attempt)


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
def _make_arr_request(method, api_endpoint, api_key, params=None, json_data=None):
    headers = {'X-Api-Key': api_key}
    try:
        logger.debug(f"Envoi de la requête *Arr : {method} {api_endpoint}")
        if params:
            logger.debug(f"Avec les paramètres : {params}")
        if json_data:
            logger.debug(f"Avec le corps JSON : {json_data}")

        response = requests.request(method, api_endpoint, headers=headers, params=params, json=json_data, timeout=30)

        # --- CHANGEMENT 1 : LOGGING DÉTAILLÉ DE LA RÉPONSE BRUTE ---
        # C'est la ligne la plus importante. Elle nous montrera la vérité.
        logger.debug(f"Réponse brute de l'API *Arr - Statut: {response.status_code}, Contenu: {response.text}")
        # --- FIN DU CHANGEMENT 1 ---

        # --- CHANGEMENT 2 : GESTION PLUS STRICTE DES ERREURS ---
        # Si le statut est une erreur client ou serveur, on la traite immédiatement.
        if not response.ok: # .ok est True pour les statuts 200-299
            error_message = f"Erreur API {response.status_code}."
            try:
                # Essaye de récupérer un message d'erreur plus précis du JSON
                error_details = response.json()
                error_message += f" Détails: {error_details}"
            except ValueError: # Si la réponse n'est pas un JSON
                error_message += f" Réponse brute: {response.text}"

            logger.error(error_message)
            return None, error_message # Retourne l'erreur clairement

        # --- CHANGEMENT 3 : GESTION SPÉCIFIQUE DU SUCCÈS POUR DELETE ---
        # Pour une suppression, un statut 200 (OK) ou 204 (No Content) est un succès.
        if method.upper() == 'DELETE' and response.status_code in [200, 204]:
            logger.info("Requête DELETE réussie avec le statut {response.status_code}.")
            return True, None # Succès clair

        # Pour les autres requêtes, on retourne le JSON
        return response.json(), None

    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de communication avec l'API *Arr : {e}", exc_info=True)
        return None, str(e)
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

    full_staging_path_str = str((Path(current_app.config['LOCAL_STAGING_PATH']) / item_name_in_staging).resolve())

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
    path_to_cleanup = item_name_in_staging # Le nom du dossier/fichier principal dans LOCAL_STAGING_PATH

    if app_type == 'sonarr':
        # Pour l'import automatique, on ne force pas de saison.
        # _handle_staged_sonarr_item essaiera de la parser ou de se fier à Sonarr.
        # Si une saison spécifique était stockée dans mapping_data, on pourrait la passer.
        # Exemple: user_chosen_season_from_map = mapping_data.get('season_number')
        result_from_handler = _handle_staged_sonarr_item(
            item_name_in_staging=item_name_in_staging, # Le nom du dossier/fichier dans LOCAL_STAGING_PATH
            series_id_target=target_id,
            path_to_cleanup_in_staging_after_success=full_staging_path_str, # Chemin absolu de l'item à nettoyer
            user_chosen_season=None, # Laisser le helper déterminer ou se fier à Sonarr
            automated_import=True,
            torrent_hash_for_status_update=torrent_hash
        )
    elif app_type == 'radarr':
        result_from_handler = _handle_staged_radarr_item(
            item_name_in_staging=item_name_in_staging, # Le nom du dossier/fichier dans LOCAL_STAGING_PATH
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
    local_staging_path_str = current_app.config.get('LOCAL_STAGING_PATH')
    orphan_exts = current_app.config.get('ORPHAN_CLEANER_EXTENSIONS', []) # Variable renommée

    # path_to_process_abs est le dossier de la release (ou le fichier unique) dans le staging
    path_to_process_abs = (Path(local_staging_path_str) / item_name_in_staging).resolve()

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
            cleanup_staging_subfolder_recursively(str(actual_folder_to_cleanup), local_staging_path_str, orphan_exts)
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
        current_status_update = "completed_manual" if not failed_moves_details else "error_partial_import"
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
    local_staging_path_str = current_app.config.get('LOCAL_STAGING_PATH')
    orphan_exts = current_app.config.get('ORPHAN_CLEANER_EXTENSIONS', []) # Variable renommée

    path_of_item_in_staging_abs = (Path(local_staging_path_str) / item_name_in_staging).resolve()
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
            cleanup_staging_subfolder_recursively(str(actual_folder_to_cleanup), local_staging_path_str, orphan_exts)
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

    if torrent_hash_for_status_update:
        final_status = 'completed_auto' if automated_import else 'processed_manual'
        status_message = final_message if automated_import else 'Traité manuellement depuis le staging.'
        torrent_map_manager.update_torrent_status_in_map(torrent_hash_for_status_update, final_status, status_message)
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
def _execute_mms_sonarr_import(item_name_in_staging, series_id_target, original_release_folder_name_in_staging, user_forced_season=None, torrent_hash_for_status_update=None, is_automated_flow=False, force_multi_part=False):
    logger = current_app.logger
    log_prefix = f"EXEC_MMS_SONARR (Item:'{item_name_in_staging}', SeriesID:{series_id_target}): "
    logger.info(f"{log_prefix}Début de l'import MMS. Force Multi-Part: {force_multi_part}")

    # --- Configuration ---
    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir_str = current_app.config.get('LOCAL_STAGING_PATH')
    orphan_exts = current_app.config.get('ORPHAN_CLEANER_EXTENSIONS', [])

    path_of_item_in_staging_abs = (Path(staging_dir_str) / item_name_in_staging).resolve()
    if not path_of_item_in_staging_abs.exists():
        return {"success": False, "message": f"Item '{item_name_in_staging}' non trouvé."}

    # --- Récupération des détails de la série ---
    series_details_url = f"{sonarr_url.rstrip('/')}/api/v3/series/{series_id_target}"
    series_data, error_msg = _make_arr_request('GET', series_details_url, sonarr_api_key)
    if error_msg or not series_data:
        return {"success": False, "message": f"Erreur Sonarr API: {error_msg}"}

    series_root_folder = series_data.get('path')
    series_title = series_data.get('title', 'Série Inconnue')
    if not series_root_folder:
        return {"success": False, "message": f"Chemin de destination manquant dans Sonarr pour '{series_title}'."}

    # --- Logique de traitement de tous les fichiers vidéo ---
    video_files_to_process = []
    if path_of_item_in_staging_abs.is_file():
        if any(str(path_of_item_in_staging_abs).lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
            video_files_to_process.append(path_of_item_in_staging_abs)
    elif path_of_item_in_staging_abs.is_dir():
        for root, _, files in os.walk(path_of_item_in_staging_abs):
            for file_name in files:
                if any(file_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
                    video_files_to_process.append(Path(root) / file_name)

    if not video_files_to_process:
        return {"success": False, "message": f"Aucun fichier vidéo trouvé dans '{item_name_in_staging}'."}

    logger.info(f"{log_prefix}{len(video_files_to_process)} fichier(s) vidéo à traiter pour '{series_title}'.")

    successful_moves = 0
    failed_moves_details = []

    # --- NOUVELLE LOGIQUE POUR GÉRER LE MULTI-PARTIES ---
    if force_multi_part and len(video_files_to_process) > 0:
        logger.info(f"{log_prefix}Traitement en mode forcé multi-parties.")
        video_files_to_process.sort(key=lambda p: p.name) # Trier pour un ordre cohérent (part1, part2, ...)

        # La saison doit être la même pour toutes les parties. On la détermine une seule fois.
        season_num = user_forced_season
        if season_num is None:
            # Essayer de parser depuis le premier fichier
            s_match = re.search(r'[._\s\[\(-]S(\d{1,3})', video_files_to_process[0].name, re.IGNORECASE)
            if s_match:
                season_num = int(s_match.group(1))

        if season_num is None:
            return {"success": False, "message": f"Impossible de déterminer la saison pour le pack multi-parties '{video_files_to_process[0].name}'. L'import a échoué."}

        dest_season_folder = Path(series_root_folder) / f"Season {str(season_num).zfill(2)}"
        dest_season_folder.mkdir(parents=True, exist_ok=True)

        for i, video_file_path in enumerate(video_files_to_process):
            base_name, ext = os.path.splitext(video_file_path.name)
            new_filename = f"{base_name} - part{i+1}{ext}"
            dest_file_path = dest_season_folder / new_filename

            try:
                logger.info(f"{log_prefix}Déplacement (multi-part): '{video_file_path}' -> '{dest_file_path}'")
                shutil.move(str(video_file_path), str(dest_file_path))
                successful_moves += 1
            except Exception as e:
                logger.error(f"{log_prefix}Échec du déplacement de '{video_file_path.name}': {e}")
                failed_moves_details.append(f"{video_file_path.name} ({e})")

    else: # --- LOGIQUE EXISTANTE (NON-MULTI-PART) ---
        for video_file_path in video_files_to_process:
            season_num = user_forced_season
            if season_num is None:
                # Tenter de parser depuis le nom de fichier
                s_match = re.search(r'[._\s\[\(-]S(\d{1,3})', video_file_path.name, re.IGNORECASE)
                if s_match:
                    season_num = int(s_match.group(1))

            if season_num is None:
                failed_moves_details.append(f"{video_file_path.name} (saison introuvable)")
                logger.error(f"{log_prefix}Impossible de déterminer la saison pour '{video_file_path.name}'.")
                continue

            dest_season_folder = Path(series_root_folder) / f"Season {str(season_num).zfill(2)}"
            dest_file_path = dest_season_folder / video_file_path.name

            try:
                dest_season_folder.mkdir(parents=True, exist_ok=True)
                logger.info(f"{log_prefix}Déplacement: '{video_file_path}' -> '{dest_file_path}'")
                shutil.move(str(video_file_path), str(dest_file_path))
                successful_moves += 1
            except Exception as e:
                logger.error(f"{log_prefix}Échec du déplacement de '{video_file_path.name}': {e}")
                failed_moves_details.append(f"{video_file_path.name} ({e})")

    if successful_moves == 0 and video_files_to_process:
        return {"success": False, "message": "Aucun fichier n'a pu être déplacé. Raison: " + (failed_moves_details[0] if failed_moves_details else "inconnue")}

    # --- Nettoyage ---
    path_to_cleanup_abs = (Path(staging_dir_str) / original_release_folder_name_in_staging).resolve()
    logger.info(f"{log_prefix}Déplacement terminé. Nettoyage de '{path_to_cleanup_abs}'")
    if path_to_cleanup_abs.exists():
        if path_to_cleanup_abs.is_dir():
            cleanup_staging_subfolder_recursively(str(path_to_cleanup_abs), staging_dir_str, orphan_exts)
        else:
            logger.info(f"{log_prefix}L'item était un fichier unique, déjà déplacé. Pas de nettoyage de dossier.")
    else:
        logger.warning(f"{log_prefix}Le dossier de cleanup '{path_to_cleanup_abs}' n'existe plus.")

    # --- Rescan Sonarr ---
    rescan_payload = {"name": "RescanSeries", "seriesId": int(series_id_target)}
    _, error_rescan = _make_arr_request('POST', f"{sonarr_url.rstrip('/')}/api/v3/command", sonarr_api_key, json_data=rescan_payload)

    final_message = f"{successful_moves} fichier(s) pour '{series_title}' déplacé(s). Échecs: {len(failed_moves_details)}. "
    final_message += "Rescan Sonarr initié." if not error_rescan else f"Échec Rescan Sonarr: {error_rescan}"

    # Bug Fix: Update status for manual imports
    if successful_moves > 0 and not is_automated_flow and torrent_hash_for_status_update:
        logger.info(f"{log_prefix}Manual import successful. Updating status to 'processed_manual'.")
        torrent_map_manager.update_torrent_status_in_map(
            torrent_hash_for_status_update,
            'processed_manual',
            'Traité manuellement depuis le staging.'
        )

    return {"success": True, "message": final_message}


def _execute_mms_radarr_import(item_name_in_staging, movie_id_target, original_release_folder_name_in_staging, torrent_hash_for_status_update=None, is_automated_flow=False):
    logger = current_app.logger
    log_prefix = f"EXEC_MMS_RADARR (Item:'{item_name_in_staging}', MovieID:{movie_id_target}): "
    logger.info(f"{log_prefix}Début de l'import MMS.")

    # --- Configuration ---
    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir_str = current_app.config.get('LOCAL_STAGING_PATH')
    orphan_exts = current_app.config.get('ORPHAN_CLEANER_EXTENSIONS', [])

    path_of_item_in_staging_abs = (Path(staging_dir_str) / item_name_in_staging).resolve()
    if not path_of_item_in_staging_abs.exists():
        return {"success": False, "message": f"Item '{item_name_in_staging}' non trouvé."}

    # --- Récupération des détails du film (pour le chemin de destination) ---
    movie_details_url = f"{radarr_url.rstrip('/')}/api/v3/movie/{movie_id_target}"
    movie_data, error_msg = _make_arr_request('GET', movie_details_url, radarr_api_key)
    if error_msg or not movie_data:
        return {"success": False, "message": f"Erreur Radarr API: {error_msg}"}

    movie_folder_path = movie_data.get('path')
    movie_title = movie_data.get('title', 'Film Inconnu')
    if not movie_folder_path:
        return {"success": False, "message": f"Chemin de destination manquant dans Radarr pour '{movie_title}'."}

    destination_folder_abs = Path(movie_folder_path)

    # --- Logique de traitement de tous les fichiers vidéo ---
    video_files_to_process = []
    if path_of_item_in_staging_abs.is_file():
        if any(str(path_of_item_in_staging_abs).lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
            video_files_to_process.append(path_of_item_in_staging_abs)
    elif path_of_item_in_staging_abs.is_dir():
        for root, _, files in os.walk(path_of_item_in_staging_abs):
            for file_name in files:
                if any(file_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
                    video_files_to_process.append(Path(root) / file_name)

    if not video_files_to_process:
        return {"success": False, "message": f"Aucun fichier vidéo trouvé dans '{item_name_in_staging}'."}

    logger.info(f"{log_prefix}{len(video_files_to_process)} fichier(s) vidéo à déplacer vers '{destination_folder_abs}'.")

    successful_moves = 0
    for video_file_path in video_files_to_process:
        try:
            destination_file_path = destination_folder_abs / video_file_path.name
            destination_folder_abs.mkdir(parents=True, exist_ok=True)
            logger.info(f"{log_prefix}Déplacement: '{video_file_path}' -> '{destination_file_path}'")
            shutil.move(str(video_file_path), str(destination_file_path))
            successful_moves += 1
        except Exception as e:
            logger.error(f"{log_prefix}Échec du déplacement de '{video_file_path.name}': {e}")

    if successful_moves == 0:
        return {"success": False, "message": "Aucun fichier n'a pu être déplacé."}

    # --- Nettoyage ---
    # Le dossier à nettoyer est toujours le dossier de premier niveau dans le staging
    path_to_cleanup_abs = (Path(staging_dir_str) / original_release_folder_name_in_staging).resolve()
    logger.info(f"{log_prefix}Déplacement terminé. Nettoyage de '{path_to_cleanup_abs}'")
    if path_to_cleanup_abs.exists():
        if path_to_cleanup_abs.is_dir():
             cleanup_staging_subfolder_recursively(str(path_to_cleanup_abs), staging_dir_str, orphan_exts)
        else: # Si c'était un fichier seul, il a déjà été déplacé, donc il n'existe plus.
             logger.info(f"{log_prefix}L'item était un fichier unique, déjà déplacé. Pas de nettoyage de dossier.")
    else:
        logger.warning(f"{log_prefix}Le dossier de cleanup '{path_to_cleanup_abs}' n'existe plus (probablement un fichier seul qui a été déplacé).")


    # --- Rescan Radarr ---
    rescan_payload = {"name": "RescanMovie", "movieId": int(movie_id_target)}
    _, error_rescan = _make_arr_request('POST', f"{radarr_url.rstrip('/')}/api/v3/command", radarr_api_key, json_data=rescan_payload)

    final_message = f"{successful_moves} fichier(s) pour '{movie_title}' déplacé(s). "
    final_message += "Rescan Radarr initié." if not error_rescan else f"Échec Rescan Radarr: {error_rescan}"

    return {"success": True, "message": final_message}

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
    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')
    if not local_staging_path or not os.path.isdir(local_staging_path):
        flash(f"Le dossier de staging '{local_staging_path}' n'est pas configuré ou n'existe pas/n'est pas un dossier.", 'danger')
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
    if local_staging_path and os.path.isdir(local_staging_path):
        logger.info(f"Index: Construction de l'arborescence pour le dossier de staging: {local_staging_path}")
        items_tree_data = build_file_tree(local_staging_path, local_staging_path, associations_by_release_name_for_staging_tree)
    # --- Fin Items du Staging Local ---


    # --- Fin Items du Staging Local ---


    # --- Fin Items du Staging Local ---

    sonarr_configured = bool(current_app.config.get('SONARR_URL') and current_app.config.get('SONARR_API_KEY'))
    radarr_configured = bool(current_app.config.get('RADARR_URL') and current_app.config.get('RADARR_API_KEY'))

    return render_template('seedbox_ui/index.html',
                           items_tree=items_tree_data,
                           can_scan_sonarr=sonarr_configured,
                           can_scan_radarr=radarr_configured,
                           staging_dir_display=local_staging_path)

@seedbox_ui_bp.route('/trigger-sftp-scan', methods=['POST'])
@login_required
def trigger_sftp_scanner_route():
    """
    Manually triggers the SFTP scanner in a background thread.
    """
    logger = current_app.logger
    lock_file = Path(current_app.instance_path) / 'sftp_scanner.lock'

    if lock_file.exists():
        flash("Un scan est déjà en cours. Veuillez patienter.", 'warning')
        logger.warning("Manual SFTP scan trigger failed: Scan already in progress (lock file exists).")
        return redirect(url_for('seedbox_ui.index'))

    def run_scan_in_thread(app):
        with app.app_context():
            logger.info("Background SFTP scan thread started.")
            sftp_scanner.scan_and_map_torrents()
            logger.info("Background SFTP scan thread finished.")

    app = current_app._get_current_object()
    thread = Thread(target=run_scan_in_thread, args=[app])
    thread.start()

    flash("Le scan des torrents terminés a été démarré en arrière-plan.", 'info')
    logger.info("Manual SFTP scan triggered successfully in a background thread.")
    return redirect(url_for('seedbox_ui.index'))

@seedbox_ui_bp.route('/delete/<path:item_name>', methods=['POST'])
@login_required
def delete_item(item_name):
    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')
    item_path = os.path.join(local_staging_path, item_name) # item_name peut contenir des sous-dossiers, d'où <path:>

    # Sécurité : Vérifier que item_path est bien dans local_staging_path
    if not os.path.abspath(item_path).startswith(os.path.abspath(local_staging_path)):
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
    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')

    if not sonarr_url or not sonarr_api_key:
        flash("Sonarr n'est pas configuré.", 'danger')
        return redirect(url_for('seedbox_ui.index'))

    item_path = os.path.join(local_staging_path, item_name)
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
    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')

    if not radarr_url or not radarr_api_key:
        flash("Radarr n'est pas configuré.", 'danger')
        return redirect(url_for('seedbox_ui.index'))

    item_path = os.path.join(local_staging_path, item_name)
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


from app.utils.tvdb_client import CustomTVDBClient

@seedbox_ui_bp.route('/api/tvdb/enrich', methods=['GET'])
@login_required
def enrich_tvdb_series_details():
    """
    Takes a TVDB ID and returns enriched series details in French.
    """
    logger = current_app.logger
    tvdb_id = request.args.get('tvdb_id')
    if not tvdb_id:
        return jsonify({"error": "TVDB ID manquant"}), 400

    try:
        tvdb_client = CustomTVDBClient()
        logger.info(f"Enriching details for TVDB ID: {tvdb_id}")
        details = tvdb_client.get_series_details_by_id(tvdb_id, lang='fra')

        if not details:
            return jsonify({"error": "Details not found on TVDB"}), 404

        # The client already provides translated 'seriesName' and 'overview'
        return jsonify(details)

    except Exception as e:
        logger.error(f"Error in enrich_tvdb_series_details for ID '{tvdb_id}': {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during enrichment."}), 500

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

@seedbox_ui_bp.route('/search-tvdb-enriched')
@login_required
def search_tvdb_enriched():
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "Terme de recherche manquant"}), 400

    try:
        initial_results = search_sonarr_by_title(query)
        if not initial_results:
            return jsonify([])

        # Limit enrichment to the first 5 results for performance
        results_to_enrich = initial_results[:5]
        enriched_results = []

        tvdb_client = CustomTVDBClient()
        for series in results_to_enrich:
            tvdb_id = series.get('tvdbId')
            if tvdb_id:
                try:
                    details = tvdb_client.get_series_details_by_id(tvdb_id, lang='fra')
                    if details:
                        series['overview'] = details.get('overview')
                        series['remotePoster'] = details.get('image')
                        series['seriesName'] = details.get('seriesName')
                except Exception as e_enrich:
                    logger.warning(f"Could not enrich TVDB ID {tvdb_id} for '{series.get('title')}': {e_enrich}")
            enriched_results.append(series)

        # Add the rest of the non-enriched results
        enriched_results.extend(initial_results[5:])

        return jsonify(enriched_results)

    except Exception as e:
        logger.error(f"Error in search_tvdb_enriched for query '{query}': {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during enriched search."}), 500


@seedbox_ui_bp.route('/search-tmdb-enriched')
@login_required
def search_tmdb_enriched():
    query = request.args.get('query')
    if not query:
        return jsonify({"error": "Terme de recherche manquant"}), 400

    try:
        initial_results = search_radarr_by_title(query)
        if not initial_results:
            return jsonify([])

        # Limit enrichment to the first 5 results for performance
        results_to_enrich = initial_results[:5]
        enriched_results = []

        tmdb_client = TheMovieDBClient()
        for movie in results_to_enrich:
            tmdb_id = movie.get('tmdbId')
            if tmdb_id:
                try:
                    details = tmdb_client.get_movie_details(tmdb_id, lang='fr-FR')
                    if details:
                        movie['overview'] = details.get('overview')
                        movie['remotePoster'] = details.get('poster_path')
                except Exception as e_enrich:
                    logger.warning(f"Could not enrich TMDB ID {tmdb_id} for '{movie.get('title')}': {e_enrich}")
            enriched_results.append(movie)

        # Add the rest of the non-enriched results
        enriched_results.extend(initial_results[5:])

        return jsonify(enriched_results)

    except Exception as e:
        logger.error(f"Error in search_tmdb_enriched for query '{query}': {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during enriched search."}), 500
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

@seedbox_ui_bp.route('/api/get-sonarr-language-profiles', methods=['GET'])
@login_required
def get_sonarr_language_profiles_api():
    """Récupère les profils de langue depuis l'API Sonarr."""
    logger = current_app.logger
    logger.info("API: Demande de récupération des profils de langue Sonarr.")

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')

    if not sonarr_url or not sonarr_api_key:
        return jsonify({"error": "Sonarr non configuré."}), 500

    api_endpoint = f"{sonarr_url.rstrip('/')}/api/v3/languageprofile"
    profiles_data, error_msg = _make_arr_request('GET', api_endpoint, sonarr_api_key)

    if error_msg:
        return jsonify({"error": f"Erreur Sonarr: {error_msg}"}), 502

    if profiles_data and isinstance(profiles_data, list):
        formatted_profiles = [{"id": profile.get("id"), "name": profile.get("name")} for profile in profiles_data if profile.get("id") is not None and profile.get("name")]
        return jsonify(formatted_profiles), 200
    else:
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

# ==============================================================================
# --- ROUTE API POUR AJOUTER UN ITEM À *ARR ET RÉCUPÉRER SON ID ---
# ==============================================================================
@seedbox_ui_bp.route('/api/add-arr-item-and-get-id', methods=['POST'])
@login_required
def add_arr_item_and_get_id():
    logger = current_app.logger
    data = request.get_json()

    if not data:
        logger.error("API Add *Arr Item: Aucune donnée JSON reçue.")
        return jsonify({"success": False, "error": "Aucune donnée JSON reçue."}), 400

    app_type = data.get('app_type') # 'sonarr' ou 'radarr'
    external_id = data.get('external_id') # tvdbId pour Sonarr, tmdbId pour Radarr
    title = data.get('title')
    # year = data.get('year', 0) # L'année n'est pas toujours directement utilisée par les fonctions add_new_*
                                # car elles la récupèrent souvent via l'ID externe.
                                # Mais elle pourrait être utile pour des logs ou validations futures.
    root_folder_path = data.get('root_folder_path')
    quality_profile_id_str = data.get('quality_profile_id')
    monitored = data.get('monitored', True) # booléen

    logger.info(f"API Add *Arr Item: Tentative d'ajout pour '{title}' (ID externe: {external_id}) à {app_type}. Options: Root='{root_folder_path}', QP ID='{quality_profile_id_str}', Monitored='{monitored}'")

    if not all([app_type, external_id is not None, title, root_folder_path, quality_profile_id_str]):
        missing_fields = [
            f for f, v in {
                "app_type": app_type, "external_id": external_id, "title": title,
                "root_folder_path": root_folder_path, "quality_profile_id": quality_profile_id_str
            }.items() if not v and v is not None # external_id peut être 0, donc vérifier "is not None"
        ]
        logger.error(f"API Add *Arr Item: Données POST manquantes. Requis: app_type, external_id, title, root_folder_path, quality_profile_id. Manquant(s): {missing_fields}")
        return jsonify({"success": False, "error": f"Données POST manquantes: {', '.join(missing_fields)}"}), 400

    try:
        external_id = int(external_id)
        quality_profile_id = int(quality_profile_id_str)
    except ValueError:
        logger.error(f"API Add *Arr Item: external_id ('{external_id}') ou quality_profile_id ('{quality_profile_id_str}') n'est pas un entier valide.")
        return jsonify({"success": False, "error": "ID externe ou ID de profil de qualité invalide (doit être numérique)."}), 400

    newly_added_media_obj = None
    error_message = None

    if app_type == 'sonarr':
        # Paramètres spécifiques à Sonarr depuis le payload JS
        language_profile_id = int(data.get('language_profile_id', 1)) # Default à 1 si non fourni
        season_folder = data.get('use_season_folder', True) # Default
        search_for_missing_episodes = False # ON FORCE À FALSE

        logger.debug(f"API Add *Arr Item (Sonarr): LangID={language_profile_id}, SeasonFolder={season_folder}, SearchMissing={search_for_missing_episodes}")

        newly_added_media_obj = add_new_series_to_sonarr(
            tvdb_id=external_id,
            title=title,
            quality_profile_id=quality_profile_id,
            language_profile_id=language_profile_id,
            root_folder_path=root_folder_path,
            season_folder=season_folder,
            monitored=monitored,
            search_for_missing_episodes=search_for_missing_episodes
        )
        if not newly_added_media_obj: # add_new_series_to_sonarr retourne None en cas d'échec
             # Essayer de construire un message d'erreur plus précis si possible, sinon un générique
             error_message = f"Échec de l'ajout de la série '{title}' à Sonarr. Vérifiez les logs de Sonarr et de MediaManagerSuite."


    elif app_type == 'radarr':
        # Paramètres spécifiques à Radarr
        minimum_availability = data.get('minimum_availability', 'announced') # Default
        search_for_movie = False # ON FORCE À FALSE

        logger.debug(f"API Add *Arr Item (Radarr): MinAvail={minimum_availability}, SearchMovie={search_for_movie}")

        newly_added_media_obj = add_new_movie_to_radarr(
            tmdb_id=external_id,
            title=title,
            quality_profile_id=quality_profile_id,
            root_folder_path=root_folder_path,
            minimum_availability=minimum_availability,
            monitored=monitored,
            search_for_movie=search_for_movie
        )
        if not newly_added_media_obj:
            error_message = f"Échec de l'ajout du film '{title}' à Radarr. Vérifiez les logs de Radarr et de MediaManagerSuite."

    else:
        logger.error(f"API Add *Arr Item: Type d'application '{app_type}' non supporté.")
        return jsonify({"success": False, "error": f"Type d'application '{app_type}' non supporté."}), 400

    if newly_added_media_obj and newly_added_media_obj.get('id'):
        new_media_internal_id = newly_added_media_obj.get('id')
        # Le titre peut être différent après ajout (ex: Sonarr/Radarr le corrige via TVDB/TMDB)
        new_media_title_from_arr = newly_added_media_obj.get('title', title)
        logger.info(f"API Add *Arr Item: Média '{new_media_title_from_arr}' ajouté à {app_type.upper()} avec ID interne: {new_media_internal_id}")
        return jsonify({
            "success": True,
            "new_media_id": new_media_internal_id,
            "new_media_title": new_media_title_from_arr,
            "message": f"'{new_media_title_from_arr}' ajouté avec succès à {app_type.capitalize()}."
        }), 201 # 201 Created
    else:
        # Si error_message a été défini par les blocs Sonarr/Radarr, l'utiliser.
        # Sinon, c'est que newly_added_media_obj était None ou n'avait pas d'ID.
        final_error = error_message if error_message else f"Échec de l'ajout de '{title}' à {app_type.capitalize()}. Réponse API invalide ou ID manquant."
        logger.error(f"API Add *Arr Item: {final_error}. Réponse brute de la fonction add_new_*: {newly_added_media_obj}")
        # Il est possible que l'item existe déjà. La fonction add_new_* pourrait le détecter et retourner l'existant.
        # Si c'est le cas, newly_added_media_obj pourrait contenir l'item existant.
        # Pour l'instant, on considère l'absence d'un nouvel ID comme un échec de cette route spécifique.
        return jsonify({"success": False, "error": final_error}), 502 # Bad Gateway, car l'erreur vient de l'API *Arr

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
    local_staging_dir_str = current_app.config.get('LOCAL_STAGING_PATH')
    local_staging_dir_for_check = Path(local_staging_dir_str) if local_staging_dir_str else None

    remote_path_to_list_root = None
    page_title = "Contenu Seedbox Distant"
    allow_sftp_delete = False
    # 'view_type' pour aider le template à savoir quel type de contenu il affiche (terminé vs travail)
    view_type = "unknown"

    if app_type_target == 'sonarr':
        remote_path_to_list_root = current_app.config.get('SEEDBOX_SCANNER_TARGET_SONARR_PATH')
        page_title = "Seedbox - Sonarr (Terminés)"
        view_type = "finished"
    elif app_type_target == 'radarr':
        remote_path_to_list_root = current_app.config.get('SEEDBOX_SCANNER_TARGET_RADARR_PATH')
        page_title = "Seedbox - Radarr (Terminés)"
        view_type = "finished"
    elif app_type_target == 'sonarr_working':
        remote_path_to_list_root = current_app.config.get('SEEDBOX_SCANNER_WORKING_SONARR_PATH')
        page_title = "Seedbox - Sonarr (Dossier de Travail)"
        allow_sftp_delete = True
        view_type = "working"
    elif app_type_target == 'radarr_working':
        remote_path_to_list_root = current_app.config.get('SEEDBOX_SCANNER_WORKING_RADARR_PATH')
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
    local_staging_dir_pathobj = Path(current_app.config.get('LOCAL_STAGING_PATH'))
    processed_log_file_str = current_app.config.get('LOCAL_PROCESSED_LOG_PATH') # Variable renommée

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
                        config_path_str = current_app.config.get('SEEDBOX_SCANNER_TARGET_SONARR_PATH')
                        if config_path_str: base_scan_folder_name_on_seedbox = Path(config_path_str).name
                    elif app_type_target_from_js == 'radarr':
                        config_path_str = current_app.config.get('SEEDBOX_SCANNER_TARGET_RADARR_PATH')
                        if config_path_str: base_scan_folder_name_on_seedbox = Path(config_path_str).name
                    elif app_type_target_from_js == 'sonarr_working':
                        config_path_str = current_app.config.get('SEEDBOX_SCANNER_WORKING_SONARR_PATH')
                        if config_path_str: base_scan_folder_name_on_seedbox = Path(config_path_str).name
                    elif app_type_target_from_js == 'radarr_working':
                        config_path_str = current_app.config.get('SEEDBOX_SCANNER_WORKING_RADARR_PATH')
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
    local_staging_dir_pathobj = Path(current_app.config.get('LOCAL_STAGING_PATH'))
    # processed_log_file_str = current_app.config.get('LOCAL_PROCESSED_LOG_PATH') # For marking items for external script

    if not all([sftp_host, sftp_port, sftp_user, sftp_password, local_staging_dir_pathobj]):
        current_app.logger.error("sftp_retrieve_and_process_action: Configuration SFTP or local_staging_path manquante.")
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
            processed_log_file_str = current_app.config.get('LOCAL_PROCESSED_LOG_PATH')
            if processed_log_file_str:
                try:
                    # Determine base_scan_folder_name_on_seedbox based on app_type_of_remote_folder
                    # This assumes app_type_of_remote_folder correctly reflects the *source* folder type (e.g., 'sonarr' for SEEDBOX_SCANNER_TARGET_SONARR_PATH)
                    path_config_key_map = {
                        'sonarr': 'SEEDBOX_SCANNER_TARGET_SONARR_PATH',
                        'radarr': 'SEEDBOX_SCANNER_TARGET_RADARR_PATH',
                        'sonarr_working': 'SEEDBOX_SCANNER_WORKING_SONARR_PATH', # Though R&P usually from finished
                        'radarr_working': 'SEEDBOX_SCANNER_WORKING_RADARR_PATH'  # Though R&P usually from finished
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
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "Requête invalide, pas de corps JSON."}), 400

    items_to_delete = data.get('items', []) # Liste de dicts {'path': '...', 'type': '...'}
    app_type_source = data.get('app_type_source') # Pour le logging/contexte

    selected_paths_to_delete = [item['path'] for item in items_to_delete if 'path' in item]

    logger.info(f"Demande de suppression SFTP (JSON) pour les items : {selected_paths_to_delete}. Contexte: {app_type_source}")

    if not selected_paths_to_delete:
        return jsonify({"success": False, "error": "Aucun item sélectionné pour la suppression."}), 400

    sftp_host = current_app.config.get('SEEDBOX_SFTP_HOST')
    sftp_port = current_app.config.get('SEEDBOX_SFTP_PORT')
    sftp_user = current_app.config.get('SEEDBOX_SFTP_USER')
    sftp_password = current_app.config.get('SEEDBOX_SFTP_PASSWORD')

    if not all([sftp_host, sftp_port, sftp_user, sftp_password]):
        logger.error("sftp_delete_items_action: Configuration SFTP manquante.")
        return jsonify({"success": False, "error": "Configuration SFTP du serveur incomplète."}), 500

    sftp_client = None
    transport = None
    success_count = 0
    failure_count = 0
    failed_items_details = []

    try:
        transport = paramiko.Transport((sftp_host, int(sftp_port)))
        transport.set_keepalive(60)
        transport.connect(username=sftp_user, password=sftp_password)
        sftp_client = paramiko.SFTPClient.from_transport(transport)
        logger.info(f"SFTP (delete items): Connecté à {sftp_host}.")

        for remote_path_posix in selected_paths_to_delete:
            if sftp_delete_recursive(sftp_client, remote_path_posix, logger):
                success_count += 1
            else:
                failure_count += 1
                failed_items_details.append({"path": remote_path_posix, "name": Path(remote_path_posix).name})

        message = f"{success_count} item(s) supprimé(s) avec succès de la seedbox."
        if failure_count > 0:
            message = f"Suppression SFTP terminée avec {failure_count} échec(s) sur {len(selected_paths_to_delete)} item(s)."
            logger.warning(f"{message} Items échoués: {[item['name'] for item in failed_items_details]}")
            return jsonify({
                "success": False, # Succès partiel est un échec pour l'alerte JS
                "error": message,
                "details": {
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "failed_items": failed_items_details
                }
            }), 207 # Multi-Status

        return jsonify({"success": True, "message": message})

    except paramiko.ssh_exception.AuthenticationException as e_auth:
        logger.error(f"SFTP (delete items): Erreur d'authentification: {e_auth}")
        return jsonify({"success": False, "error": "Erreur d'authentification SFTP. Vérifiez vos identifiants."}), 401
    except Exception as e_sftp:
        logger.error(f"SFTP (delete items): Erreur générale SFTP: {e_sftp}", exc_info=True)
        return jsonify({"success": False, "error": f"Erreur SFTP lors de la suppression: {e_sftp}"}), 500
    finally:
        if sftp_client: sftp_client.close()
        if transport: transport.close()
        logger.debug("SFTP (delete items): Connexion fermée.")
# ------------------------------------------------------------------------------
# FONCTION trigger_sonarr_import
# ------------------------------------------------------------------------------

@seedbox_ui_bp.route('/trigger-sonarr-import', methods=['POST'])
@login_required
def trigger_sonarr_import():
    data = request.get_json()
    item_name = data.get('item_name')
    series_id = data.get('series_id')
    problem_torrent_hash = data.get('problem_torrent_hash')

    logger.info(f"STAGING_ASSOCIATE: Tentative d'association pour item '{item_name}', série ID {series_id}")

    if not item_name or not series_id:
        return jsonify({"success": False, "error": "Données manquantes."}), 400

    torrent_hash_to_update = problem_torrent_hash
    if not torrent_hash_to_update:
        torrent_hash_to_update, _ = torrent_map_manager.find_torrent_by_release_name(item_name)

    if not torrent_hash_to_update:
        return jsonify({'success': False, 'error': f"Aucun torrent correspondant à '{item_name}' trouvé dans le map."}), 404

    existing_entry = torrent_map_manager.get_torrent_by_hash(torrent_hash_to_update)
    if not existing_entry:
        return jsonify({'success': False, 'error': f"Incohérence: Hash '{torrent_hash_to_update}' non trouvé."}), 404

    # On met à jour l'entrée avec les nouvelles informations
    torrent_map_manager.add_or_update_torrent_in_map(
        release_name=existing_entry.get('release_name', item_name),
        torrent_hash=torrent_hash_to_update,
        status='in_staging',  # <-- LA CORRECTION CLÉ EST ICI
        seedbox_download_path=existing_entry.get('seedbox_download_path'),
        folder_name=existing_entry.get('folder_name', item_name),
        app_type='sonarr',
        target_id=series_id,
        label=current_app.config.get('RTORRENT_LABEL_SONARR', 'sonarr'),
        original_torrent_name=existing_entry.get('original_torrent_name')
    )

    return jsonify({'success': True, 'message': f"'{item_name}' a été associé à la série ID {series_id}. Le traitement va commencer."})

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
# Import stat module for checking file types from SFTP attributes
import stat

@seedbox_ui_bp.route('/trigger-radarr-import', methods=['POST'])
@login_required
def trigger_radarr_import():
    data = request.get_json()
    item_name = data.get('item_name')
    movie_id = data.get('movie_id')
    problem_torrent_hash = data.get('problem_torrent_hash')

    logger.info(f"STAGING_ASSOCIATE: Tentative d'association pour item '{item_name}', film ID {movie_id}")

    if not item_name or not movie_id:
        return jsonify({"success": False, "error": "Données manquantes."}), 400

    torrent_hash_to_update = problem_torrent_hash
    if not torrent_hash_to_update:
        torrent_hash_to_update, _ = torrent_map_manager.find_torrent_by_release_name(item_name)

    if not torrent_hash_to_update:
        return jsonify({'success': False, 'error': f"Aucun torrent correspondant à '{item_name}' trouvé dans le map."}), 404

    existing_entry = torrent_map_manager.get_torrent_by_hash(torrent_hash_to_update)
    if not existing_entry:
        return jsonify({'success': False, 'error': f"Incohérence: Hash '{torrent_hash_to_update}' non trouvé."}), 404

    torrent_map_manager.add_or_update_torrent_in_map(
        release_name=existing_entry.get('release_name', item_name),
        torrent_hash=torrent_hash_to_update,
        status='in_staging',  # <-- LA CORRECTION CLÉ EST ICI
        seedbox_download_path=existing_entry.get('seedbox_download_path'),
        folder_name=existing_entry.get('folder_name', item_name),
        app_type='radarr',
        target_id=movie_id,
        label=current_app.config.get('RTORRENT_LABEL_RADARR', 'radarr'),
        original_torrent_name=existing_entry.get('original_torrent_name')
    )

    return jsonify({'success': True, 'message': f"'{item_name}' a été associé au film ID {movie_id}. Le traitement va commencer."})

# FIN de trigger_radarr_import (MODIFIÉE)


@seedbox_ui_bp.route('/cleanup-staging-item/<path:item_name>', methods=['POST'])
@login_required
def cleanup_staging_item_action(item_name):
    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')
    orphan_exts = current_app.config.get('ORPHAN_CLEANER_EXTENSIONS', []) # Variable renommée

    # item_name est le nom de l'item tel qu'affiché dans l'UI (peut être un dossier ou un fichier à la racine du staging)
    item_to_cleanup_path = os.path.join(local_staging_path, item_name)
    item_to_cleanup_path = os.path.normpath(os.path.abspath(item_to_cleanup_path)) # Sécurisation

    logger.info(f"Action de nettoyage manuel demandée pour l'item de staging: {item_to_cleanup_path}")

    # Sécurité : Vérifier que item_to_cleanup_path est bien dans local_staging_path
    if not item_to_cleanup_path.startswith(os.path.normpath(os.path.abspath(local_staging_path))):
        flash("Tentative de nettoyage d'un chemin invalide.", 'danger')
        logger.warning(f"Tentative de nettoyage de chemin invalide : {item_to_cleanup_path}")
        return redirect(url_for('seedbox_ui.index'))

    # On ne nettoie que les dossiers avec cette action pour l'instant
    if not os.path.isdir(item_to_cleanup_path):
        flash(f"L'action de nettoyage ne s'applique qu'aux dossiers. '{item_name}' n'est pas un dossier.", 'warning')
        logger.warning(f"Tentative de nettoyage sur un non-dossier : {item_to_cleanup_path}")
        return redirect(url_for('seedbox_ui.index'))

    # Si le dossier est le local_staging_path lui-même, on ne fait rien (la fonction de cleanup a aussi ce garde-fou)
    if item_to_cleanup_path == os.path.normpath(os.path.abspath(local_staging_path)):
        flash("Impossible de nettoyer le dossier de staging racine directement.", "danger")
        logger.warning("Tentative de nettoyage du dossier de staging racine via l'UI.")
        return redirect(url_for('seedbox_ui.index'))

    if os.path.exists(item_to_cleanup_path):
        # Le is_top_level_call=True est important ici car c'est le dossier de base qu'on veut nettoyer.
        # La fonction récursive passera False pour ses appels internes.
        success = cleanup_staging_subfolder_recursively(item_to_cleanup_path, local_staging_path, orphan_exts, is_top_level_call=True)
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
        rtorrent_download_dir = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_SONARR_PATH') # Variable renommée
        arr_url = current_app.config.get('SONARR_URL')
        arr_api_key = current_app.config.get('SONARR_API_KEY')
    else: # radarr
        rtorrent_label = current_app.config.get('RTORRENT_LABEL_RADARR')
        rtorrent_download_dir = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_RADARR_PATH') # Variable renommée
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

    # Le chemin sur la seedbox sera déterminé par le scanner une fois le téléchargement terminé.

    if torrent_map_manager.add_or_update_torrent_in_map(
            release_name_for_map,
            actual_hash,
            "pending_download",
            None, # C'est la correction cruciale: création d'une promesse
            folder_name=release_name_for_map,
            app_type=app_type,
            target_id=actual_target_id,
            label=rtorrent_label,
            original_torrent_name=original_name_from_js
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

    torrents_data, error_msg_rtorrent = rtorrent_list_torrents_api()

    if error_msg_rtorrent:
        current_app.logger.error(f"Error fetching torrents from rTorrent (httprpc): {error_msg_rtorrent}")
        flash(f"Impossible de lister les torrents de rTorrent: {error_msg_rtorrent}", "danger")
        return render_template('seedbox_ui/rtorrent_list.html',
                               torrents_with_assoc=[],
                               page_title="Liste des Torrents rTorrent (Erreur)",
                               error_message=error_msg_rtorrent)

    if torrents_data is None:
        current_app.logger.warning("rtorrent_list_torrents_api (httprpc) returned None for data without an error message.")
        flash("Aucune donnée reçue de rTorrent.", "warning")
        torrents_data = []

    all_mms_associations = torrent_map_manager.get_all_torrents_in_map()
    if not isinstance(all_mms_associations, dict):
        current_app.logger.error("torrent_map_manager.get_all_torrents_in_map() did not return a dict.")
        all_mms_associations = {}

    torrents_with_assoc = []
    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')

    if isinstance(torrents_data, list):
        for torrent in torrents_data:
            torrent_hash = torrent.get('hash')
            mms_status = 'unknown'
            mms_file_exists = False

            # Format load date from rTorrent
            load_timestamp = torrent.get('load_date', 0)
            if load_timestamp > 0:
                torrent['load_date_str'] = datetime.fromtimestamp(load_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            else:
                torrent['load_date_str'] = 'N/A'

            association_data = all_mms_associations.get(torrent_hash)
            if association_data:
                torrent['target_id'] = association_data.get('target_id')
                mms_status = association_data.get('status', 'unknown')

                if mms_status in ['in_staging', 'pending_staging', 'error_staging_path_missing', 'error_mms_all_files_failed_move', 'error_sonarr_season_undefined_for_file', 'error_mms_file_move']:
                    release_name = association_data.get('release_name')
                    if release_name and local_staging_path:
                        full_path = Path(local_staging_path) / release_name
                        mms_file_exists = full_path.exists()
                elif mms_status == 'completed_manual' or mms_status == 'completed_auto':
                    mms_file_exists = True

            torrent['mms_status'] = mms_status
            torrent['mms_file_exists'] = mms_file_exists

            torrents_with_assoc.append({
                "details": torrent,
                "association": association_data
            })
    else:
        current_app.logger.error(f"rtorrent_list_torrents_api (httprpc) did not return a list. Got: {type(torrents_data)}")
        flash("Format de données inattendu reçu de rTorrent.", "danger")
        return render_template('seedbox_ui/rtorrent_list.html', torrents_with_assoc=[], page_title="Liste des Torrents rTorrent (Erreur Format)", error_message="Format de données rTorrent invalide.")

    torrents_with_assoc.sort(key=lambda x: x['details'].get('load_date', 0), reverse=True)

    current_app.logger.info(f"Affichage de {len(torrents_with_assoc)} torrent(s) avec leurs informations d'association (httprpc).")

    config_label_sonarr = current_app.config.get('RTORRENT_LABEL_SONARR', 'sonarr')
    config_label_radarr = current_app.config.get('RTORRENT_LABEL_RADARR', 'radarr')

    return render_template('seedbox_ui/rtorrent_list.html',
                           torrents_with_assoc=torrents_with_assoc,
                           page_title="Liste des Torrents rTorrent",
                           error_message=None,
                           config_label_sonarr=config_label_sonarr,
                           config_label_radarr=config_label_radarr)

@seedbox_ui_bp.route('/rtorrent/delete', methods=['POST'])
@login_required
def delete_rtorrent_torrent():
    data = request.get_json()
    torrent_hash = data.get('hash')
    delete_data = data.get('delete_data', False)

    if not torrent_hash:
        return jsonify({'status': 'error', 'message': 'Hash du torrent manquant.'}), 400

    try:
        # Suppose que rtorrent_client a une méthode delete_torrent
        # qui prend le hash et un booléen pour la suppression des données.
        success, message = rtorrent_delete_torrent_api(torrent_hash, delete_data)
        if success:
            return jsonify({'status': 'success', 'message': 'Torrent supprimé avec succès de rTorrent.'})
        else:
            return jsonify({'status': 'error', 'message': message}), 500
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du torrent {torrent_hash}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@seedbox_ui_bp.route('/api/rtorrent/torrent/<string:torrent_hash>/files')
@login_required
def get_rtorrent_torrent_files(torrent_hash):
    """
    API endpoint to get the file list for a specific torrent.
    """
    logger = current_app.logger
    logger.info(f"API request for files of torrent hash: {torrent_hash}")

    files, error = rtorrent_get_files_api(torrent_hash)

    if error:
        logger.error(f"Error getting files for torrent {torrent_hash}: {error}")
        return jsonify({"success": False, "error": error}), 500

    return jsonify({"success": True, "files": files})


@seedbox_ui_bp.route('/rtorrent/batch-action', methods=['POST'])
@login_required
def rtorrent_batch_action():
    data = request.get_json()
    hashes = data.get('hashes', [])
    action = data.get('action')
    options = data.get('options', {})

    if not hashes or not action:
        return jsonify({'status': 'error', 'message': 'Hashes ou action manquants.'}), 400

    success_count = 0
    fail_count = 0

    # --- Action de Suppression ---
    if action == 'delete':
        delete_data = options.get('delete_data', False)
        for h in hashes:
            try:
                success, _ = rtorrent_delete_torrent_api(h, delete_data)
                if success: success_count += 1
                else: fail_count += 1
            except Exception as e:
                logger.error(f"Erreur lors de la suppression du torrent {h}: {e}", exc_info=True)
                fail_count += 1
    # --- Action "Marquer comme traité" ---
    elif action == 'mark_processed':
        for h in hashes:
            if torrent_map_manager.update_torrent_status_in_map(h, 'processed_manual', 'Marqué comme traité manuellement via action groupée.'):
                success_count += 1
            else:
                fail_count += 1
    # --- Action "Oublier l'association" ---
    elif action == 'forget':
        for h in hashes:
            if torrent_map_manager.remove_torrent_from_map(h):
                success_count += 1
            else:
                fail_count += 1
    # --- Action "Ignorer définitivement" ---
    elif action == 'ignore':
        for h in hashes:
            if torrent_map_manager.add_hash_to_ignored_list(h):
                torrent_map_manager.remove_torrent_from_map(h) # On le retire aussi de la liste des suivis
                success_count += 1
            else:
                fail_count += 1
    # --- Action "Rapatrier" ---
    elif action == 'repatriate':
        # Cette action est plus complexe et nécessite une connexion SFTP
        sftp, transport = staging_processor._connect_sftp()
        if not sftp:
            return jsonify({'status': 'error', 'message': 'Connexion SFTP échouée.'}), 500
        try:
            for h in hashes:
                item = torrent_map_manager.get_torrent_by_hash(h)
                if item:
                    folder_name = item.get('folder_name', item['release_name'])
                    if staging_processor._rapatriate_item(item, sftp, folder_name):
                        torrent_map_manager.update_torrent_status_in_map(h, 'in_staging', 'Rapatrié manuellement via action groupée.')
                        success_count += 1
                    else:
                        fail_count += 1
                else:
                    fail_count += 1
        finally:
            if transport:
                transport.close()
    # --- Action "Réessayer le rapatriement" ---
    elif action == 'retry_repatriation':
        for h in hashes:
            if torrent_map_manager.update_torrent_status_in_map(h, 'pending_staging'):
                success_count += 1
            else:
                fail_count += 1
    else:
        return jsonify({'status': 'error', 'message': 'Action non supportée.'}), 400

    return jsonify({
        'status': 'success',
        'message': f'Action "{action}" exécutée. Succès: {success_count}, Échecs: {fail_count}.'
    })

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
    rutorrent_api_url = current_app.config.get('RTORRENT_API_URL')
    rutorrent_user = current_app.config.get('RTORRENT_USER')
    rutorrent_password = current_app.config.get('RTORRENT_PASSWORD')
    ssl_verify_str = current_app.config.get('RTORRENT_SSL_VERIFY', "True") # Default à "True" si non défini

    if not rutorrent_api_url:
        flash("L'URL de l'API ruTorrent n'est pas configurée.", 'danger')
        current_app.logger.error("add_torrent_and_map: RTORRENT_API_URL non configuré.")
        return redirect(url_for('seedbox_ui.rtorrent_list'))

    # 3. Construire le download_dir
    base_download_dir = ""
    if media_type == 'series':
        base_download_dir = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_SONARR_PATH') # Variable renommée
    elif media_type == 'movie':
        base_download_dir = current_app.config.get('SEEDBOX_RTORRENT_INCOMING_RADARR_PATH') # Variable renommée
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

    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')
    if not local_staging_path: # Should not happen if app is configured
        flash("Le dossier de staging n'est pas configuré dans l'application.", "danger")
        current_app.logger.error("process_staged_with_association: LOCAL_STAGING_PATH non configuré.")
        return redirect(url_for('seedbox_ui.index'))

    path_of_item_in_staging_abs = (Path(local_staging_path) / item_name_in_staging).resolve()

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
    seedbox_sonarr_finished_path = current_app.config.get('SEEDBOX_SCANNER_TARGET_SONARR_PATH') # Variable renommée
    seedbox_radarr_finished_path = current_app.config.get('SEEDBOX_SCANNER_TARGET_RADARR_PATH') # Variable renommée
    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')

    if not all([rtorrent_label_sonarr, rtorrent_label_radarr, seedbox_sonarr_finished_path, seedbox_radarr_finished_path, local_staging_path]):
        current_app.logger.error("Automatisation: Configuration manquante (labels rTorrent, chemins distants finis, ou local_staging_path). Cycle annulé.")
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
        local_staged_item_path_abs = Path(local_staging_path) / local_staged_item_name

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

    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')
    if not local_staging_path:
        current_app.logger.error("API Process Staged: LOCAL_STAGING_PATH n'est pas configuré dans l'application.")
        # Cette erreur est côté serveur, donc 500 est plus approprié.
        return jsonify({"success": False, "error": "Configuration serveur incomplète (LOCAL_STAGING_PATH)."}), 500

    # Utiliser Path pour construire le chemin et normaliser
    # item_name pourrait contenir des sous-chemins ex: "dossier/fichier.mkv"
    # Path.resolve() n'est pas idéal ici car il peut échouer si une partie du chemin n'existe pas.
    # On veut joindre et normaliser pour la comparaison et la vérification d'existence.
    item_path = (Path(local_staging_path) / item_name).resolve() # resolve() pour obtenir le chemin absolu canonique

    # Sécurité: Vérifier que le chemin résolu est bien DANS le local_staging_path
    # Cela empêche les traversées de répertoire comme item_name = "../../../../etc/passwd"
    if not item_path.is_relative_to(Path(local_staging_path).resolve()):
        current_app.logger.error(f"API Process Staged: Tentative d'accès hors du LOCAL_STAGING_PATH détectée pour '{item_name}'. Chemin résolu: {item_path}")
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

    local_staging_path = current_app.config.get('LOCAL_STAGING_PATH')
    if not local_staging_path:
        logger.error("Batch Map Sonarr: LOCAL_STAGING_PATH non configuré.")
        return jsonify({"success": False, "error": "Configuration serveur incomplète (LOCAL_STAGING_PATH)."}), 500

    successful_imports = 0
    failed_imports_details = [] # Pour stocker les détails des échecs

    for item_name in item_names_in_staging:
        logger.info(f"Batch Map Sonarr: Traitement de l'item '{item_name}' pour la série {series_id_target}.")

        full_staging_path_str = str((Path(local_staging_path) / item_name).resolve())
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
        return jsonify({'status': 'error', 'message': f"Association non trouvée pour le hash {torrent_hash}."}), 404

    item_name_in_staging = association_data.get('release_name')

    # --- CORRECTION 1 : Utiliser la bonne variable pour le chemin de staging ---
    staging_dir = current_app.config.get('LOCAL_STAGING_PATH') # Utilise la variable de config correcte

    if not item_name_in_staging or not staging_dir or not (Path(staging_dir) / item_name_in_staging).exists():
        message = f"L'item '{item_name_in_staging or 'Inconnu'}' n'est plus dans le staging ou informations manquantes. Impossible de réessayer."
        if torrent_hash:
            torrent_map_manager.update_torrent_status_in_map(torrent_hash, "error_retry_failed_item_not_in_staging", "Item non trouvé dans le staging pour la relance.")
        return jsonify({'status': 'error', 'message': message}), 404

    logger.info(f"Relance du traitement pour : '{item_name_in_staging}', Hash: {torrent_hash}")
    torrent_map_manager.update_torrent_status_in_map(torrent_hash, "processing_by_mms_retry", f"Relance manuelle pour {item_name_in_staging}")

    # --- CORRECTION 2 : La NameError est corrigée ici ---
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
        message = f"Type d'application inconnu '{app_type}' pour la relance."
        if torrent_hash:
            torrent_map_manager.update_torrent_status_in_map(torrent_hash, "error_unknown_association_type", "Type d'app inconnu lors de la relance.")
        return jsonify({'status': 'error', 'message': message}), 400

    # --- CORRECTION 3 : Retourner du JSON au lieu d'une redirection ---
    if result_from_handler.get("success"):
        message = f"Relance pour '{item_name_in_staging}' réussie: {result_from_handler.get('message')}"
        return jsonify({'status': 'success', 'message': message})
    elif result_from_handler.get("manual_required"):
        message = f"Relance pour '{item_name_in_staging}' nécessite une attention manuelle: {result_from_handler.get('message')}"
        return jsonify({'status': 'warning', 'message': message}) # On peut utiliser un statut 'warning'
    else:
        message = f"Échec de la relance pour '{item_name_in_staging}': {result_from_handler.get('message', 'Erreur inconnue')}"
        return jsonify({'status': 'error', 'message': message}), 500

@seedbox_ui_bp.route('/rtorrent/map/sonarr', methods=['POST'], endpoint='rtorrent_map_sonarr')
@login_required
def rtorrent_map_sonarr():
    data = request.get_json()
    torrent_name = data.get('torrent_name')
    is_new_media = data.get('is_new_media', False)

    if not torrent_name:
        return jsonify({'success': False, 'error': 'Nom du torrent manquant.'}), 400

    torrents_data, error_msg = rtorrent_list_torrents_api()
    if error_msg:
        return jsonify({'success': False, 'error': f"Erreur rTorrent: {error_msg}"}), 500

    torrent_info = next((t for t in torrents_data if t.get('name') == torrent_name), None)
    if not torrent_info:
        return jsonify({'success': False, 'error': f"Torrent '{torrent_name}' non trouvé dans rTorrent."}), 404

    torrent_hash = torrent_info.get('hash')
    final_series_id = None
    seedbox_dl_path = torrent_info.get('base_path')

    if is_new_media:
        tvdb_id = data.get('tvdb_id')
        title = data.get('title')
        root_folder_path = data.get('root_folder_path')
        quality_profile_id = data.get('quality_profile_id')
        if not all([tvdb_id, title, root_folder_path, quality_profile_id]):
            return jsonify({'success': False, 'error': 'Données manquantes pour ajouter une nouvelle série.'}), 400

        newly_added_series = add_new_series_to_sonarr(
            tvdb_id=tvdb_id,
            title=title,
            quality_profile_id=quality_profile_id,
            language_profile_id=1,  # Default to 1, assuming it's the first/default language profile
            root_folder_path=root_folder_path
        )
        if not newly_added_series or not newly_added_series.get('id'):
            return jsonify({'success': False, 'error': "Échec de l'ajout de la série à Sonarr."}), 500
        final_series_id = newly_added_series.get('id')
    else:
        final_series_id = data.get('series_id')
        if not final_series_id:
            return jsonify({'success': False, 'error': 'ID de la série manquant pour un média existant.'}), 400

    torrent_map_manager.add_or_update_torrent_in_map(
        release_name=torrent_name,
        torrent_hash=torrent_hash,
        status='pending_staging',
        seedbox_download_path=seedbox_dl_path, # Création de la promesse
        folder_name=torrent_name,
        app_type='sonarr',
        target_id=final_series_id,
        label=current_app.config.get('RTORRENT_LABEL_SONARR', 'sonarr'),
        original_torrent_name=torrent_name
    )

    return jsonify({'success': True, 'message': f"Torrent '{torrent_name}' mappé avec succès à la série ID {final_series_id}."})

@seedbox_ui_bp.route('/rtorrent/map/radarr', methods=['POST'], endpoint='rtorrent_map_radarr')
@login_required
def rtorrent_map_radarr():
    data = request.get_json()
    torrent_name = data.get('torrent_name')
    is_new_media = data.get('is_new_media', False)

    if not torrent_name:
        return jsonify({'success': False, 'error': 'Nom du torrent manquant.'}), 400

    torrents_data, error_msg = rtorrent_list_torrents_api()
    if error_msg:
        return jsonify({'success': False, 'error': f"Erreur rTorrent: {error_msg}"}), 500

    torrent_info = next((t for t in torrents_data if t.get('name') == torrent_name), None)
    if not torrent_info:
        return jsonify({'success': False, 'error': f"Torrent '{torrent_name}' non trouvé dans rTorrent."}), 404

    torrent_hash = torrent_info.get('hash')
    final_movie_id = None
    seedbox_dl_path = torrent_info.get('base_path')

    if is_new_media:
        tmdb_id = data.get('tmdb_id')
        title = data.get('title')
        root_folder_path = data.get('root_folder_path')
        quality_profile_id = data.get('quality_profile_id')
        if not all([tmdb_id, title, root_folder_path, quality_profile_id]):
            return jsonify({'success': False, 'error': 'Données manquantes pour ajouter un nouveau film.'}), 400

        newly_added_movie = add_new_movie_to_radarr(
            tmdb_id=tmdb_id,
            title=title,
            quality_profile_id=quality_profile_id,
            root_folder_path=root_folder_path
        )
        if not newly_added_movie or not newly_added_movie.get('id'):
            return jsonify({'success': False, 'error': "Échec de l'ajout du film à Radarr."}), 500
        final_movie_id = newly_added_movie.get('id')
    else:
        final_movie_id = data.get('movie_id')
        if not final_movie_id:
            return jsonify({'success': False, 'error': 'ID du film manquant pour un média existant.'}), 400

    torrent_map_manager.add_or_update_torrent_in_map(
        release_name=torrent_name,
        torrent_hash=torrent_hash,
        status='pending_staging',
        seedbox_download_path=seedbox_dl_path, # Création de la promesse
        folder_name=torrent_name,
        app_type='radarr',
        target_id=final_movie_id,
        label=current_app.config.get('RTORRENT_LABEL_RADARR', 'radarr'),
        original_torrent_name=torrent_name
    )

    return jsonify({'success': True, 'message': f"Torrent '{torrent_name}' mappé avec succès au film ID {final_movie_id}."})

# ==============================================================================
# --- NOUVELLES ROUTES POUR LES ACTIONS MANUELLES DE LA VUE RTORRENT ---
# ==============================================================================

# Assurez-vous que ces imports sont bien en haut de votre fichier routes.py
from app.utils.staging_processor import _connect_sftp, _rapatriate_item

@seedbox_ui_bp.route('/torrent/mark-processed', methods=['POST'])
@login_required
def mark_torrent_processed():
    """
    Marque un torrent comme traité manuellement.
    """
    torrent_hash = request.json.get('torrent_hash')
    if not torrent_hash:
        return jsonify({'status': 'error', 'message': 'HASH manquant.'}), 400

    # Utilise la fonction confirmée
    success = torrent_map_manager.update_torrent_status_in_map(
        torrent_hash,
        'processed_manual',
        'Marqué comme traité manuellement par l_utilisateur.'
    )

    if success:
        return jsonify({'status': 'success', 'message': 'Torrent marqué comme traité.'})
    else:
        return jsonify({'status': 'error', 'message': 'Torrent non trouvé dans la map.'}), 404

@seedbox_ui_bp.route('/staging/repatriate', methods=['POST'])
@login_required
def repatriate_to_staging():
    """
    Déclenche uniquement le rapatriement d'un torrent vers le staging.
    """
    torrent_hash = request.json.get('torrent_hash')
    if not torrent_hash:
        return jsonify({'status': 'error', 'message': 'HASH manquant.'}), 400

    item = torrent_map_manager.get_torrent_by_hash(torrent_hash)

    # **NOUVELLE LOGIQUE : Si l'item est inconnu, on le crée !**
    if not item:
        # On doit récupérer les infos depuis rTorrent
        all_torrents, _ = rtorrent_list_torrents_api()
        torrent_info = next((t for t in all_torrents if t.get('hash') == torrent_hash), None)

        if not torrent_info:
            return jsonify({'status': 'error', 'message': 'Torrent non trouvé dans rTorrent.'}), 404

        # On crée l'entrée dans le mapping manager
        torrent_map_manager.add_or_update_torrent_in_map(
            torrent_info['name'],
            torrent_hash,
            'pending_staging',
            torrent_info['base_path'],
            folder_name=os.path.basename(torrent_info['base_path'])
        )
        # On recharge l'item pour la suite du traitement
        item = torrent_map_manager.get_torrent_by_hash(torrent_hash)

    # Utilise la fonction de connexion confirmée
    sftp, transport = _connect_sftp()
    if not sftp:
        return jsonify({'status': 'error', 'message': 'Connexion SFTP échouée.'}), 500

    try:
        folder_name = item.get('folder_name', item['release_name'])

        # Utilise la fonction de rapatriement confirmée
        success = _rapatriate_item(item, sftp, folder_name) # Note: le paramètre est bien `sftp` ici

        if success:
            # Met à jour le statut
            torrent_map_manager.update_torrent_status_in_map(
                torrent_hash,
                'in_staging',
                'Rapatrié manuellement vers le staging.'
            )
            return jsonify({'status': 'success', 'message': 'Rapatriement vers le staging réussi.'})
        else:
            torrent_map_manager.update_torrent_status_in_map(
                torrent_hash,
                'error_repatriation',
                'Échec du rapatriement manuel.'
            )
            return jsonify({'status': 'error', 'message': 'Échec du rapatriement.'}), 500

    finally:
        if transport:
            transport.close()


@seedbox_ui_bp.route('/problematic-association/delete/<string:torrent_hash>', methods=['POST'])
@login_required
def delete_problematic_association_action(torrent_hash):
    logger = current_app.logger
    logger.info(f"Demande de suppression de l'association pour le torrent hash: {torrent_hash}")

    association_data = torrent_map_manager.get_torrent_by_hash(torrent_hash)
    release_name_for_log = association_data.get('release_name', 'Hash Inconnu') if association_data else f"Hash: {torrent_hash}"

    if torrent_map_manager.remove_torrent_from_map(torrent_hash):
        message = f"L'association pour '{release_name_for_log}' a été supprimée."
        logger.info(f"Association pour hash {torrent_hash} ('{release_name_for_log}') supprimée avec succès.")
        return jsonify({'status': 'success', 'message': message})
    else:
        message = f"Impossible de trouver ou de supprimer l'association pour '{release_name_for_log}'."
        logger.warning(f"Tentative de suppression d'une association inexistante ou échec pour hash {torrent_hash} ('{release_name_for_log}').")
        return jsonify({'status': 'error', 'message': message}), 404 # 404 Not Found est approprié ici
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
    logger.info("Demande de suppression d'items de la file d'attente Sonarr via API.")

    # --- CHANGEMENT 1 : Récupérer les données depuis un corps JSON ---
    # Le JavaScript enverra maintenant un JSON, c'est plus propre que les formulaires.
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Requête invalide.'}), 400

    selected_ids = data.get('ids', [])
    remove_from_client = data.get('removeFromClient', False)

    logger.info(f"Suppression items Sonarr. IDs: {selected_ids}, removeFromClient: {remove_from_client}")

    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')

    # --- CHANGEMENT 2 : Retourner des erreurs JSON au lieu de flash/redirect ---
    if not sonarr_url or not sonarr_api_key:
        return jsonify({'status': 'error', 'message': 'Sonarr n\'est pas configuré.'}), 500

    if not selected_ids:
        return jsonify({'status': 'error', 'message': 'Aucun item Sonarr sélectionné.'}), 400

    success_count = 0
    error_count = 0
    errors = []

    for item_id in selected_ids:
        api_endpoint = f"{sonarr_url.rstrip('/')}/api/v3/queue/{item_id}"
        params = {
            'removeFromClient': str(remove_from_client).lower(),
            'blacklist': 'false'
        }
        logger.debug(f"Appel DELETE Sonarr: {api_endpoint} avec params: {params}")
        response_status, error_msg = _make_arr_request('DELETE', api_endpoint, sonarr_api_key, params=params)

        if error_msg:
            logger.error(f"Erreur suppression item Sonarr ID {item_id}: {error_msg}")
            error_count += 1
            errors.append(f"ID {item_id}: {error_msg}")
        else:
            logger.info(f"Item Sonarr ID {item_id} supprimé de la file d'attente avec succès.")
            success_count += 1

    # --- CHANGEMENT 3 : Construire une réponse JSON finale ---
    if error_count > 0:
        message = f"{success_count} item(s) supprimé(s). Échec pour {error_count} item(s). Erreurs: {'; '.join(errors)}"
        return jsonify({'status': 'error', 'message': message}), 500
    else:
        message = f"{success_count} item(s) supprimé(s) de la file d'attente Sonarr avec succès."
        return jsonify({'status': 'success', 'message': message})


@seedbox_ui_bp.route('/queue/radarr/delete', methods=['POST'])
@login_required
def delete_radarr_queue_items():
    logger.info("Demande de suppression d'items de la file d'attente Radarr via API.")

    # --- CHANGEMENT 1 : Récupérer les données depuis un corps JSON ---
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Requête invalide.'}), 400

    selected_ids = data.get('ids', [])
    remove_from_client = data.get('removeFromClient', False)

    logger.info(f"Suppression items Radarr. IDs: {selected_ids}, removeFromClient: {remove_from_client}")

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')

    # --- CHANGEMENT 2 : Retourner des erreurs JSON au lieu de flash/redirect ---
    if not radarr_url or not radarr_api_key:
        return jsonify({'status': 'error', 'message': 'Radarr n\'est pas configuré.'}), 500

    if not selected_ids:
        return jsonify({'status': 'error', 'message': 'Aucun item Radarr sélectionné.'}), 400

    success_count = 0
    error_count = 0
    errors = []

    for item_id in selected_ids:
        api_endpoint = f"{radarr_url.rstrip('/')}/api/v3/queue/{item_id}"
        params = {
            'removeFromClient': str(remove_from_client).lower(),
            'blacklist': 'false'
        }
        logger.debug(f"Appel DELETE Radarr: {api_endpoint} avec params: {params}")
        response_status, error_msg = _make_arr_request('DELETE', api_endpoint, radarr_api_key, params=params)

        if error_msg:
            logger.error(f"Erreur suppression item Radarr ID {item_id}: {error_msg}")
            error_count += 1
            errors.append(f"ID {item_id}: {error_msg}")
        else:
            logger.info(f"Item Radarr ID {item_id} supprimé de la file d'attente avec succès.")
            success_count += 1

    # --- CHANGEMENT 3 : Construire une réponse JSON finale ---
    if error_count > 0:
        message = f"{success_count} item(s) supprimé(s). Échec pour {error_count} item(s). Erreurs: {'; '.join(errors)}"
        return jsonify({'status': 'error', 'message': message}), 500
    else:
        message = f"{success_count} item(s) supprimé(s) de la file d'attente Radarr avec succès."
        return jsonify({'status': 'success', 'message': message})

# ==============================================================================
# --- ROUTE POUR SFTP -> AJOUT ARR -> RAPATRIEMENT -> IMPORT MMS ---
# ==============================================================================
@seedbox_ui_bp.route('/api/sftp-add-and-import-arr-item', methods=['POST'])
@login_required
def sftp_add_and_import_arr_item_action():
    logger = current_app.logger
    data = request.get_json()

    if not data:
        logger.error("SFTP Add&Import: Aucune donnée JSON reçue.")
        return jsonify({"success": False, "error": "Aucune donnée JSON reçue."}), 400

    sftp_details = data.get('sftp_details')
    media_to_add = data.get('media_to_add') # Contient tvdbId/tmdbId, title, year etc.
    user_choices = data.get('user_choices') # Contient rootFolderPath, qualityProfileId etc.
    arr_type = data.get('arr_type') # 'sonarr' ou 'radarr'

    if not all([sftp_details, media_to_add, user_choices, arr_type]):
        logger.error(f"SFTP Add&Import: Données POST manquantes. Reçu: sftp_details={sftp_details is not None}, media_to_add={media_to_add is not None}, user_choices={user_choices is not None}, arr_type={arr_type is not None}")
        return jsonify({"success": False, "error": "Données POST manquantes pour l'opération."}), 400

    logger.info(f"SFTP Add&Import: Début pour item distant '{sftp_details.get('item_name')}' vers {arr_type.upper()}. Média à ajouter: '{media_to_add.get('title')}'")

    # --- Étape 1: Ajouter le média à Sonarr/Radarr ---
    newly_added_media_obj = None
    if arr_type == 'sonarr':
        if not media_to_add.get('tvdbId'):
            return jsonify({"success": False, "error": "tvdbId manquant pour l'ajout à Sonarr."}), 400

        newly_added_media_obj = add_new_series_to_sonarr(
            tvdb_id=int(media_to_add['tvdbId']),
            title=media_to_add.get('title'),
            quality_profile_id=int(user_choices['qualityProfileId']),
            language_profile_id=int(user_choices.get('languageProfileId', 1)), # Default à 1 si non fourni
            root_folder_path=user_choices['rootFolderPath'],
            season_folder=user_choices.get('seasonFolder', True),
            monitored=user_choices.get('monitored', True),
            search_for_missing_episodes=user_choices.get('addOptions', {}).get('searchForMissingEpisodes', False)
        )
    elif arr_type == 'radarr':
        if not media_to_add.get('tmdbId'):
            return jsonify({"success": False, "error": "tmdbId manquant pour l'ajout à Radarr."}), 400

        newly_added_media_obj = add_new_movie_to_radarr(
            tmdb_id=int(media_to_add['tmdbId']),
            title=media_to_add.get('title'),
            quality_profile_id=int(user_choices['qualityProfileId']),
            root_folder_path=user_choices['rootFolderPath'],
            minimum_availability=user_choices.get('minimumAvailability', 'announced'),
            monitored=user_choices.get('monitored', True),
            search_for_movie=user_choices.get('addOptions', {}).get('searchForMovie', False)
        )
    else:
        return jsonify({"success": False, "error": f"Type d'application '{arr_type}' non supporté."}), 400

    if not newly_added_media_obj or not newly_added_media_obj.get('id'):
        logger.error(f"SFTP Add&Import: Échec de l'ajout de '{media_to_add.get('title')}' à {arr_type.upper()}. Réponse API: {newly_added_media_obj}")
        return jsonify({"success": False, "error": f"Échec de l'ajout du média à {arr_type.upper()}. Vérifiez les logs {arr_type.upper()}."}), 502 # Bad Gateway

    new_internal_id = newly_added_media_obj.get('id')
    logger.info(f"SFTP Add&Import: Média '{media_to_add.get('title')}' ajouté à {arr_type.upper()} avec ID interne: {new_internal_id}")

    # --- Étape 2: Rapatriement SFTP ---
    sftp_host = current_app.config.get('SEEDBOX_SFTP_HOST')
    sftp_port = int(current_app.config.get('SEEDBOX_SFTP_PORT', 22))
    sftp_user = current_app.config.get('SEEDBOX_SFTP_USER')
    sftp_password = current_app.config.get('SEEDBOX_SFTP_PASSWORD')
    local_staging_dir_pathobj = Path(current_app.config.get('LOCAL_STAGING_PATH'))

    if not all([sftp_host, sftp_user, sftp_password, local_staging_dir_pathobj.exists()]):
        logger.error("SFTP Add&Import: Configuration SFTP ou local_staging_path manquante/invalide pour le rapatriement.")
        # On pourrait vouloir supprimer le média ajouté à *Arr ici, mais c'est complexe.
        return jsonify({"success": False, "error": "Configuration serveur incomplète pour le rapatriement SFTP."}), 500

    remote_path_posix = sftp_details.get('remote_path')
    item_basename_on_seedbox = Path(remote_path_posix).name # Nom de l'item sur la seedbox
    local_staged_item_path_obj = local_staging_dir_pathobj / item_basename_on_seedbox

    sftp_client = None
    transport = None
    success_download = False
    try:
        logger.debug(f"SFTP Add&Import: Connexion SFTP à {sftp_host}:{sftp_port} pour '{remote_path_posix}'")
        transport = paramiko.Transport((sftp_host, sftp_port))
        transport.set_keepalive(60)
        transport.connect(username=sftp_user, password=sftp_password)
        sftp_client = paramiko.SFTPClient.from_transport(transport)

        success_download = _download_sftp_item_recursive_local(sftp_client, remote_path_posix, local_staged_item_path_obj, logger)

        if success_download:
            logger.info(f"SFTP Add&Import: Téléchargement de '{item_basename_on_seedbox}' réussi vers '{local_staged_item_path_obj}'.")
            # Mise à jour de processed_sftp_items.json
            processed_log_file_str = current_app.config.get('LOCAL_PROCESSED_LOG_PATH')
            if processed_log_file_str:
                try:
                    base_scan_folder_name_on_seedbox = Path(sftp_details.get('app_type_of_remote_folder', 'unknown_remote_folder')).name # Utiliser le type de dossier distant
                    processed_item_identifier_for_log = f"{base_scan_folder_name_on_seedbox}/{item_basename_on_seedbox}"

                    current_processed_set = set()
                    processed_log_file = Path(processed_log_file_str)
                    if processed_log_file.exists() and processed_log_file.stat().st_size > 0:
                        try:
                            with open(processed_log_file, 'r', encoding='utf-8') as f_log_read:
                                data_log = json.load(f_log_read)
                                if isinstance(data_log, list): current_processed_set = set(data_log)
                        except (json.JSONDecodeError, Exception): logger.error(f"Erreur lecture/décodage de {processed_log_file}. Sera écrasé si ajout.")

                    if processed_item_identifier_for_log not in current_processed_set:
                        current_processed_set.add(processed_item_identifier_for_log)
                        processed_log_file.parent.mkdir(parents=True, exist_ok=True)
                        with open(processed_log_file, 'w', encoding='utf-8') as f_log_write:
                            json.dump(sorted(list(current_processed_set)), f_log_write, indent=4)
                        logger.info(f"SFTP Add&Import: '{processed_item_identifier_for_log}' ajouté à {processed_log_file}.")
                except Exception as e_proc_log:
                    logger.error(f"SFTP Add&Import: Erreur gestion log items traités: {e_proc_log}", exc_info=True)
        else:
            logger.error(f"SFTP Add&Import: Échec du téléchargement SFTP de '{remote_path_posix}'.")
            # Nettoyage partiel si nécessaire
            if local_staged_item_path_obj.exists():
                if local_staged_item_path_obj.is_dir() and not any(local_staged_item_path_obj.iterdir()): shutil.rmtree(local_staged_item_path_obj)
                elif local_staged_item_path_obj.is_file() and local_staged_item_path_obj.stat().st_size == 0: local_staged_item_path_obj.unlink()
            return jsonify({"success": False, "error": f"Échec du téléchargement SFTP de '{item_basename_on_seedbox}'."}), 500

    except Exception as e_sftp:
        logger.error(f"SFTP Add&Import: Erreur SFTP: {e_sftp}", exc_info=True)
        return jsonify({"success": False, "error": f"Erreur SFTP: {e_sftp}"}), 500
    finally:
        if sftp_client: sftp_client.close()
        if transport: transport.close()

    # --- Étape 3: Import MMS ---
    if success_download:
        logger.info(f"SFTP Add&Import: Rapatriement terminé. Import MMS de '{item_basename_on_seedbox}' vers ID {arr_type.upper()} {new_internal_id}.")

        import_result_dict = None
        # original_release_folder_name_in_staging est le nom de l'item tel qu'il a été téléchargé à la racine du staging
        original_folder_to_cleanup = item_basename_on_seedbox

        if arr_type == 'sonarr':
            import_result_dict = _execute_mms_sonarr_import(
                item_name_in_staging=item_basename_on_seedbox,
                series_id_target=new_internal_id,
                original_release_folder_name_in_staging=original_folder_to_cleanup,
                is_automated_flow=True # Considéré comme automatisé après l'ajout initial
            )
        elif arr_type == 'radarr':
            import_result_dict = _execute_mms_radarr_import(
                item_name_in_staging=item_basename_on_seedbox,
                movie_id_target=new_internal_id,
                original_release_folder_name_in_staging=original_folder_to_cleanup,
                is_automated_flow=True
            )

        if import_result_dict and import_result_dict.get("success"):
            final_msg = f"'{media_to_add.get('title')}' ajouté à {arr_type.upper()} (ID: {new_internal_id}), rapatrié et importé avec succès. {import_result_dict.get('message', '')}"
            logger.info(f"SFTP Add&Import: {final_msg}")
            return jsonify({"success": True, "message": final_msg})
        else:
            error_msg_import = f"Échec de l'import MMS après ajout et rapatriement. {import_result_dict.get('message', 'Erreur inconnue du handler MMS.') if import_result_dict else 'Handler MMS non exécuté.'}"
            logger.error(f"SFTP Add&Import: {error_msg_import}")
            # L'item est dans le staging, le média est dans *Arr. L'utilisateur devra peut-être mapper manuellement.
            return jsonify({"success": False, "error": error_msg_import, "details": "L'item est dans le staging, mais l'import final a échoué."}), 500
    else: # Ne devrait pas être atteint si la logique de retour en cas d'échec de DL est correcte
        return jsonify({"success": False, "error": "Échec du téléchargement SFTP, import MMS non tenté."}), 500


@seedbox_ui_bp.route('/api/sftp-add-and-import-arr-item-placeholder', methods=['POST'])
@login_required
def sftp_add_and_import_arr_item_placeholder():
    # Cette route est un placeholder pour éviter les erreurs 404 tant que la vraie n'est pas testée.
    # Elle devrait être remplacée par la vraie logique ou supprimée une fois que
    # '/api/sftp-add-and-import-arr-item' est pleinement fonctionnelle et testée.
    logger.warning("ROUTE PLACEHOLDER '/api/sftp-add-and-import-arr-item-placeholder' APPELÉE. Implémentez la vraie route.")
    time.sleep(2) # Simuler un traitement
    return jsonify({
        "success": False,
        "error": "Fonctionnalité non entièrement implémentée. La route /api/sftp-add-and-import-arr-item doit être finalisée.",
        "message": "Placeholder: L'ajout, le rapatriement et l'import pour un nouvel item SFTP ne sont pas encore complètement fonctionnels."
    }), 501 # 501 Not Implemented

@seedbox_ui_bp.route('/staging/retry_repatriation', methods=['POST'])
@login_required
def retry_repatriation_endpoint():
    data = request.json
    torrent_hash = data.get('torrent_hash')

    if not torrent_hash:
        return jsonify({'status': 'error', 'message': 'HASH du torrent manquant.'}), 400

    try:
        # On change simplement le statut, le processeur fera le reste.
        success = torrent_map_manager.update_torrent_status_in_map(torrent_hash, 'pending_staging')
        if success:
            return jsonify({'status': 'success', 'message': f"L'item {torrent_hash} a été remis dans la file d'attente de staging."})
        else:
            return jsonify({'status': 'error', 'message': 'Torrent non trouvé dans la map.'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@seedbox_ui_bp.route('/torrent/ignore', methods=['POST'])
@login_required
def ignore_torrent_permanently():
    data = request.json
    torrent_hash = data.get('torrent_hash')

    if not torrent_hash:
        return jsonify({'status': 'error', 'message': 'HASH du torrent manquant.'}), 400

    try:
        # Add to the ignored list first
        success_ignore = torrent_map_manager.add_hash_to_ignored_list(torrent_hash)
        if not success_ignore:
            # Logged inside the function, but we can return a specific error
            return jsonify({'status': 'error', 'message': "Échec de l'ajout du torrent à la liste des ignorés."}), 500

        # Then remove from the pending map
        torrent_map_manager.remove_torrent_from_map(torrent_hash)

        return jsonify({'status': 'success', 'message': f"Le torrent {torrent_hash} a été ignoré définitivement et supprimé de la liste de suivi."})

    except Exception as e:
        current_app.logger.error(f"Error in ignore_torrent_permanently for hash {torrent_hash}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@seedbox_ui_bp.route('/run_staging_processor', methods=['POST'])
@internal_api_required
def run_staging_processor_endpoint():
    try:
        staging_processor.process_pending_staging_items()
        return jsonify({'status': 'success', 'message': 'Staging processor job executed.'})
    except Exception as e:
        current_app.logger.error(f"Error running staging processor endpoint: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500