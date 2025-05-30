# app/seedbox_ui/routes.py
import os
import shutil
import logging
import time # Pour le délai
import re
import paramiko
from pathlib import Path
from datetime import datetime
import requests # Pour les appels API
from requests.exceptions import RequestException # Pour gérer les erreurs de connexion
from flask import Blueprint, render_template, current_app, request, flash, redirect, url_for, jsonify
import stat
import json
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
            # Pour les sous-niveaux, cette vérification 'is_in_local_staging' est moins pertinente
            # ou nécessiterait de reconstruire le chemin relatif complet par rapport au staging.
            # Pour l'instant, on ne la fait que pour les items de premier niveau du scan.
            # On pourrait passer le `relative_path_from_root_scan` pour une vérification plus précise.
            is_present_in_local_staging = False
            if Path(remote_current_path_posix).as_posix() == Path(base_remote_path_for_actions).as_posix(): # Seulement pour le niveau racine scanné
                 potential_local_path_root_item = local_staging_dir_pathobj_to_check / attr.filename
                 is_present_in_local_staging = potential_local_path_root_item.exists()


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
# ==============================================================================
# NOUVELLE FONCTION HELPER POUR TRAITER UN ITEM SONARR DÉJÀ DANS LE STAGING
# ==============================================================================

def _handle_staged_sonarr_item(item_name_in_staging, series_id_target, path_to_cleanup_in_staging_after_success, user_chosen_season=None): # user_chosen_episode enlevé pour l'instant
    """
    Gère l'import d'un item Sonarr déjà présent dans le staging local.
    - Tente d'obtenir des infos de Sonarr sur le fichier (qualité, langue).
    - Utilise user_chosen_season si fourni, sinon essaie de parser le nom de fichier, sinon se fie à Sonarr.
    - MediaManagerSuite effectue le déplacement.
    - Déclenche un RescanSeries.
    - Nettoie le dossier de staging.
    """
    logger.info(f"HELPER _handle_staged_sonarr_item: Traitement de '{item_name_in_staging}' pour Série ID {series_id_target}. Saison explicitement choisie: {user_chosen_season}")

    # Récupérer les configs
    sonarr_url = current_app.config.get('SONARR_URL')
    sonarr_api_key = current_app.config.get('SONARR_API_KEY')
    staging_dir_str = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    path_of_item_in_staging_abs = (Path(staging_dir_str) / item_name_in_staging).resolve()
    if not path_of_item_in_staging_abs.exists():
        logger.error(f"_handle_staged_sonarr_item: Item '{item_name_in_staging}' (résolu en {path_of_item_in_staging_abs}) non trouvé.")
        return {"success": False, "error": f"Item '{item_name_in_staging}' non trouvé dans le staging."}

    # Déterminer le chemin à scanner pour l'API manualimport de Sonarr et le fichier principal
    path_to_scan_for_api_get_obj = None
    main_video_file_abs_path_in_staging = None # Chemin absolu du fichier vidéo principal
    original_filename_of_video = None

    if path_of_item_in_staging_abs.is_file():
        if any(str(path_of_item_in_staging_abs).lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi']):
            path_to_scan_for_api_get_obj = path_of_item_in_staging_abs # Scanner le fichier lui-même
            main_video_file_abs_path_in_staging = path_of_item_in_staging_abs
            original_filename_of_video = path_of_item_in_staging_abs.name
        else:
            logger.error(f"_handle_staged_sonarr_item: Item fichier '{item_name_in_staging}' n'est pas une vidéo reconnue.")
            return {"success": False, "error": "Le fichier sélectionné n'est pas un type vidéo reconnu."}
    elif path_of_item_in_staging_abs.is_dir():
        path_to_scan_for_api_get_obj = path_of_item_in_staging_abs # Scanner le dossier
        # Trouver le fichier vidéo principal à l'intérieur
        for root, _, files in os.walk(path_of_item_in_staging_abs):
            for file in files:
                if any(file.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi']):
                    main_video_file_abs_path_in_staging = Path(root) / file
                    original_filename_of_video = file
                    break
            if main_video_file_abs_path_in_staging:
                break
        if not main_video_file_abs_path_in_staging:
            logger.error(f"_handle_staged_sonarr_item: Aucun fichier vidéo trouvé dans le dossier '{item_name_in_staging}'.")
            return {"success": False, "error": "Aucun fichier vidéo trouvé dans le dossier stagé."}
    else:
        return {"success": False, "error": "Item de staging non valide."}, 400

    path_for_api_get_str_win = str(path_to_scan_for_api_get_obj).replace('/', '\\')
    logger.info(f"_handle_staged_sonarr_item: Fichier vidéo principal identifié: {main_video_file_abs_path_in_staging}")
    logger.info(f"_handle_staged_sonarr_item: Dossier/Fichier scanné par Sonarr pour infos: {path_for_api_get_str_win}")

    # --- Tenter d'obtenir des infos (qualité, langue) de Sonarr pour ce fichier ---
    manual_import_get_url = f"{sonarr_url.rstrip('/')}/api/v3/manualimport"
    get_params = {'folder': path_for_api_get_str_win, 'filterExistingFiles': 'false'} # On scanne le fichier ou son dossier direct
    logger.debug(f"_handle_staged_sonarr_item: GET Sonarr ManualImport pour infos: URL={manual_import_get_url}, Params={get_params}")
    manual_import_candidates, error_msg_get = _make_arr_request('GET', manual_import_get_url, sonarr_api_key, params=get_params)

    # Variables pour les infos extraites de Sonarr (ou des valeurs par défaut)
    sonarr_identified_season_num = None
    sonarr_identified_episode_num = None
    # On ne prend plus quality et language de ce call car on ne fait plus de POST ManualImport à Sonarr

    if error_msg_get or not isinstance(manual_import_candidates, list):
        logger.warning(f"_handle_staged_sonarr_item: Erreur ou pas de candidats de Sonarr lors du GET manualimport pour '{original_filename_of_video}': {error_msg_get or 'Pas de candidats'}. On continue avec les infos du nom de fichier.")
    else: # On a des candidats, on essaie de trouver celui qui correspond à notre fichier vidéo principal
        found_candidate_info = False
        for candidate in manual_import_candidates:
            candidate_path_from_api = candidate.get('path')
            if not candidate_path_from_api: continue

            abs_cand_path_in_staging = (path_to_scan_for_api_get_obj / candidate_path_from_api).resolve() if path_to_scan_for_api_get_obj.is_dir() else path_to_scan_for_api_get_obj.resolve()

            if abs_cand_path_in_staging == main_video_file_abs_path_in_staging.resolve():
                # C'est notre fichier ! Récupérer les infos S/E de Sonarr
                candidate_episodes_info = candidate.get('episodes', [])
                if candidate_episodes_info:
                    sonarr_identified_season_num = candidate_episodes_info[0].get('seasonNumber')
                    sonarr_identified_episode_num = candidate_episodes_info[0].get('episodeNumber')
                    logger.info(f"_handle_staged_sonarr_item: Sonarr a identifié '{original_filename_of_video}' comme S{sonarr_identified_season_num}E{sonarr_identified_episode_num}.")
                else:
                    logger.warning(f"_handle_staged_sonarr_item: Sonarr a trouvé le fichier '{original_filename_of_video}' mais sans infos d'épisode.")
                found_candidate_info = True
                break
        if not found_candidate_info:
             logger.warning(f"_handle_staged_sonarr_item: Le fichier '{original_filename_of_video}' n'a pas été spécifiquement retourné par le scan Sonarr, ou sans infos d'épisode.")


    # --- Déterminer la saison à utiliser pour le déplacement ---
    season_to_use_for_move = None
    if user_chosen_season is not None:
        season_to_use_for_move = user_chosen_season
        logger.info(f"_handle_staged_sonarr_item: Utilisation de la saison forcée par l'utilisateur: {season_to_use_for_move}")
    else: # Pas de saison forcée, on essaie de parser le nom du fichier
        filename_s_num_parsed, _ = None, None
        s_e_match = re.search(r'[._\s\[\(-]S(\d{1,3})[E._\s-]?(\d{1,3})', original_filename_of_video, re.IGNORECASE)
        if s_e_match:
            try: filename_s_num_parsed = int(s_e_match.group(1))
            except ValueError: pass

        if filename_s_num_parsed is not None:
            season_to_use_for_move = filename_s_num_parsed
            logger.info(f"_handle_staged_sonarr_item: Utilisation de la saison S{season_to_use_for_move} parsée du nom de fichier '{original_filename_of_video}'.")
            if sonarr_identified_season_num is not None and sonarr_identified_season_num != filename_s_num_parsed:
                logger.warning(f"_handle_staged_sonarr_item: Discordance (info): Nom de fichier S{filename_s_num_parsed} vs Sonarr S{sonarr_identified_season_num}. On utilise S{filename_s_num_parsed}.")
        elif sonarr_identified_season_num is not None:
            season_to_use_for_move = sonarr_identified_season_num
            logger.info(f"_handle_staged_sonarr_item: Utilisation de la saison S{season_to_use_for_move} identifiée par Sonarr (nom de fichier non parsable).")
        else:
            logger.error(f"_handle_staged_sonarr_item: Impossible de déterminer le numéro de saison pour '{original_filename_of_video}'. Annulation.")
            return {"success": False, "error": f"Impossible de déterminer la saison pour '{original_filename_of_video}'."}

    # --- Récupérer les détails de la série pour le chemin racine ---
    series_details_url = f"{sonarr_url.rstrip('/')}/api/v3/series/{series_id_target}"
    series_data, error_series_data = _make_arr_request('GET', series_details_url, sonarr_api_key)
    if error_series_data or not series_data:
        return {"success": False, "error": "Impossible de récupérer les détails de la série Sonarr."}
    series_root_folder_path = series_data.get('path')
    series_title = series_data.get('title', 'Série Inconnue')
    if not series_root_folder_path:
        return {"success": False, "error": "Chemin racine de la série non trouvé dans Sonarr."}

    # --- Déplacement du fichier principal ---
    dest_season_folder_name = f"Season {str(season_to_use_for_move).zfill(2)}" # Ex: Season 00, Season 13, Season 14
    dest_season_path_abs = Path(series_root_folder_path) / dest_season_folder_name
    dest_file_path_abs = dest_season_path_abs / original_filename_of_video # Garde le nom original du fichier

    logger.info(f"_handle_staged_sonarr_item: Déplacement MMS: '{main_video_file_abs_path_in_staging}' vers '{dest_file_path_abs}'")
    imported_successfully = False
    try:
        dest_season_path_abs.mkdir(parents=True, exist_ok=True)
        if main_video_file_abs_path_in_staging.resolve() != dest_file_path_abs.resolve():
            shutil.move(str(main_video_file_abs_path_in_staging), str(dest_file_path_abs))
        else:
            logger.warning(f"_handle_staged_sonarr_item: Source et destination identiques pour le déplacement {main_video_file_abs_path_in_staging}. Fichier déjà en place?")
        imported_successfully = True
    except Exception as e_move:
        logger.error(f"_handle_staged_sonarr_item: Erreur move '{main_video_file_abs_path_in_staging}': {e_move}. Tentative copie/suppr.")
        try:
            shutil.copy2(str(main_video_file_abs_path_in_staging), str(dest_file_path_abs))
            os.remove(str(main_video_file_abs_path_in_staging))
            imported_successfully = True
        except Exception as e_copy:
            logger.error(f"_handle_staged_sonarr_item: Erreur copie/suppr '{main_video_file_abs_path_in_staging}': {e_copy}")
            return {"success": False, "error": f"Échec du déplacement du fichier '{original_filename_of_video}': {e_copy}"}

    if not imported_successfully:
         return {"success": False, "error": f"Échec inattendu du déplacement du fichier '{original_filename_of_video}'."}

    # --- Nettoyage du dossier de staging d'origine ---
    # path_to_cleanup_in_staging_after_success est le chemin complet de l'item cliqué initialement.
    # C'est CE dossier/fichier qu'on veut nettoyer.
    # Si c'était un fichier, on nettoie son dossier parent (qui est original_release_folder_in_staging)
    # Si c'était un dossier, on le nettoie lui-même.
    actual_folder_to_cleanup = Path(path_to_cleanup_in_staging_after_success)
    if actual_folder_to_cleanup.is_file(): # Si on a cliqué sur un fichier, on nettoie son dossier parent
        actual_folder_to_cleanup = actual_folder_to_cleanup.parent

    if actual_folder_to_cleanup.exists() and actual_folder_to_cleanup.is_dir():
        logger.info(f"_handle_staged_sonarr_item: Nettoyage du dossier de staging: {actual_folder_to_cleanup}")
        time.sleep(1)
        cleanup_staging_subfolder_recursively(str(actual_folder_to_cleanup), staging_dir_str, orphan_exts)

    # --- Rescan Sonarr ---
    rescan_payload = {"name": "RescanSeries", "seriesId": series_id_target}
    command_url = f"{sonarr_url.rstrip('/')}/api/v3/command"
    _, error_rescan = _make_arr_request('POST', command_url, sonarr_api_key, json_data=rescan_payload)

    message = f"'{original_filename_of_video}' (pour '{series_title}', S{str(season_to_use_for_move).zfill(2)}) déplacé avec succès."
    status_code_override = 200
    if error_rescan:
        message += f" Échec du Rescan Sonarr: {error_rescan}."
        status_code_override = 207 # Multi-Status: une partie a réussi, une autre non
    else:
        message += " Rescan Sonarr initié."

    return {"success": True, "message": message, "status_code_override": status_code_override}

# ==============================================================================
# FIN DE LA FONCTION HELPER _handle_staged_sonarr_item
# ==============================================================================
# ==============================================================================
# NOUVELLE FONCTION HELPER POUR TRAITER UN ITEM RADARR DÉJÀ DANS LE STAGING
# ==============================================================================
def _handle_staged_radarr_item(item_name_in_staging, movie_id_target, path_to_cleanup_in_staging_after_success):
    """
    Gère l'import d'un item Radarr déjà présent dans le staging local.
    - MediaManagerSuite effectue le déplacement.
    - Déclenche un RescanMovie.
    - Nettoie le dossier de staging.
    Retourne un dictionnaire: {"success": True/False, "message": "..."}
    """
    logger.info(f"HELPER _handle_staged_radarr_item: Traitement de '{item_name_in_staging}' pour Movie ID {movie_id_target}.")

    # Récupérer les configs
    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir_str = current_app.config.get('STAGING_DIR')
    orphan_exts = current_app.config.get('ORPHAN_EXTENSIONS', [])

    path_of_item_in_staging_abs = (Path(staging_dir_str) / item_name_in_staging).resolve()
    if not path_of_item_in_staging_abs.exists():
        logger.error(f"_handle_staged_radarr_item: Item '{item_name_in_staging}' (résolu en {path_of_item_in_staging_abs}) non trouvé.")
        return {"success": False, "error": f"Item '{item_name_in_staging}' non trouvé dans le staging."}

    # Identifier le fichier vidéo principal
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
            logger.error(f"_handle_staged_radarr_item: Aucun fichier vidéo trouvé dans le dossier '{item_name_in_staging}'.")
            return {"success": False, "error": "Aucun fichier vidéo trouvé dans le dossier stagé."}
    else:
        return {"success": False, "error": "Item de staging non valide."}, 400

    logger.info(f"_handle_staged_radarr_item: Fichier vidéo principal identifié: {main_video_file_abs_path_in_staging}")

    # --- Récupérer les détails du film cible pour le chemin de destination ---
    movie_details_url = f"{radarr_url.rstrip('/')}/api/v3/movie/{movie_id_target}"
    logger.debug(f"_handle_staged_radarr_item: GET Radarr Movie Details: URL={movie_details_url}")
    movie_data, error_movie_data = _make_arr_request('GET', movie_details_url, radarr_api_key)

    if error_movie_data or not movie_data or not isinstance(movie_data, dict):
        logger.error(f"_handle_staged_radarr_item: Erreur détails film {movie_id_target}: {error_movie_data or 'Pas de données'}")
        return {"success": False, "error": "Impossible de récupérer les détails du film depuis Radarr."}

    # 'path' dans /api/v3/movie/{id} est le chemin complet du dossier du film
    expected_movie_folder_path_from_radarr_api = movie_data.get('path')
    movie_title = movie_data.get('title', 'Film Inconnu')
    if not expected_movie_folder_path_from_radarr_api:
        logger.error(f"_handle_staged_radarr_item: Chemin ('path') manquant pour film ID {movie_id_target} dans Radarr. Assurez-vous qu'un Root Folder est assigné.")
        return {"success": False, "error": f"Chemin de destination non configuré dans Radarr pour '{movie_title}'."}

    logger.info(f"_handle_staged_radarr_item: Chemin dossier final Radarr pour '{movie_title}': {expected_movie_folder_path_from_radarr_api}")

    # --- Déplacement du fichier vidéo ---
    destination_folder_for_movie = Path(expected_movie_folder_path_from_radarr_api).resolve()
    # On garde le nom original du fichier vidéo. Radarr le renommera si configuré.
    destination_video_file_path_abs = destination_folder_for_movie / original_filename_of_video

    logger.info(f"_handle_staged_radarr_item: Déplacement MMS: '{main_video_file_abs_path_in_staging}' vers '{destination_video_file_path_abs}'")
    imported_successfully = False
    try:
        destination_folder_for_movie.mkdir(parents=True, exist_ok=True) # Crée le dossier du film si besoin
        if main_video_file_abs_path_in_staging.resolve() != destination_video_file_path_abs.resolve():
            shutil.move(str(main_video_file_abs_path_in_staging), str(destination_video_file_path_abs))
        else:
            logger.warning(f"_handle_staged_radarr_item: Source et destination identiques: {main_video_file_abs_path_in_staging}")
        imported_successfully = True
    except Exception as e_move:
        logger.error(f"_handle_staged_radarr_item: Erreur move '{original_filename_of_video}': {e_move}. Tentative copie/suppr.")
        try:
            shutil.copy2(str(main_video_file_abs_path_in_staging), str(destination_video_file_path_abs))
            os.remove(str(main_video_file_abs_path_in_staging))
            imported_successfully = True
        except Exception as e_copy:
            logger.error(f"_handle_staged_radarr_item: Erreur copie/suppr '{original_filename_of_video}': {e_copy}")
            return {"success": False, "error": f"Échec du déplacement du fichier '{original_filename_of_video}': {e_copy}"}

    if not imported_successfully:
         return {"success": False, "error": f"Échec inattendu du déplacement du fichier '{original_filename_of_video}'."}

    # --- Nettoyage du dossier de staging d'origine ---
    actual_folder_to_cleanup = Path(path_to_cleanup_in_staging_after_success) # Ceci est le chemin de l'item cliqué
    if actual_folder_to_cleanup.is_file():
        actual_folder_to_cleanup = actual_folder_to_cleanup.parent

    if actual_folder_to_cleanup.exists() and actual_folder_to_cleanup.is_dir():
        logger.info(f"_handle_staged_radarr_item: Nettoyage dossier staging: {actual_folder_to_cleanup}")
        time.sleep(1)
        cleanup_staging_subfolder_recursively(str(actual_folder_to_cleanup), staging_dir_str, orphan_exts)

    # --- Rescan Radarr ---
    rescan_payload = {"name": "RescanMovie", "movieId": movie_id_target}
    command_url = f"{radarr_url.rstrip('/')}/api/v3/command"
    _, error_rescan = _make_arr_request('POST', command_url, radarr_api_key, json_data=rescan_payload)

    message = f"Fichier pour '{movie_title}' déplacé avec succès."
    status_code_override = 200
    if error_rescan:
        message += f" Échec du Rescan Radarr: {error_rescan}."
        status_code_override = 207
    else:
        message += " Rescan Radarr initié."

    return {"success": True, "message": message, "status_code_override": status_code_override}

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
# ==============================================================================
# NOUVELLE FONCTION HELPER POUR LE TRAITEMENT D'IMPORT SONARR
# ==============================================================================
def _execute_sonarr_import_processing(item_name_in_staging, # Nom du fichier/dossier dans le staging local
                                      series_id_target,
                                      # La saison/épisode que Sonarr a identifié OU que l'utilisateur a forcé:
                                      forced_season_num_for_move,
                                      # first_episode_num_for_naming, # Pour un nommage plus précis plus tard
                                      original_release_folder_to_cleanup, # Le dossier de la release dans le staging
                                      current_logger,
                                      app_config):
    """
    Logique principale pour traiter un item stagé pour Sonarr:
    Valide (si pas déjà fait), déplace le fichier par MMS, notifie Sonarr avec Rescan, nettoie le staging.
    Retourne un tuple (bool_success, message_str).
    'forced_season_num_for_move' est la saison à utiliser pour le placement.
    'original_release_folder_to_cleanup' est le chemin du dossier de la release dans le staging (peut être identique à item_name_in_staging si c'est un dossier).
    """
    current_logger.info(f"Exécution import processing pour item stagé: '{item_name_in_staging}', SérieID: {series_id_target}, Saison Cible: {forced_season_num_for_move}")

    sonarr_url = app_config.get('SONARR_URL')
    sonarr_api_key = app_config.get('SONARR_API_KEY')
    staging_dir_str = app_config.get('STAGING_DIR')
    staging_dir_pathobj = Path(staging_dir_str)
    orphan_exts = app_config.get('ORPHAN_EXTENSIONS', [])

    path_of_item_in_staging = staging_dir_pathobj / item_name_in_staging

    if not path_of_item_in_staging.exists():
        current_logger.error(f"_execute_sonarr_import_processing: Item '{item_name_in_staging}' non trouvé dans staging '{staging_dir_str}'.")
        return False, f"Item '{item_name_in_staging}' introuvable dans le staging."

    # Identifier le fichier vidéo principal à déplacer
    main_video_file_to_move_source_path = None
    original_filename_for_destination = None

    if path_of_item_in_staging.is_file():
        # S'assurer que c'est un fichier vidéo
        if any(str(path_of_item_in_staging).lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
            main_video_file_to_move_source_path = path_of_item_in_staging
            original_filename_for_destination = path_of_item_in_staging.name
        else:
            current_logger.error(f"_execute_sonarr_import_processing: Item '{item_name_in_staging}' est un fichier non vidéo.")
            return False, "L'item stagé n'est pas un fichier vidéo reconnu."

    elif path_of_item_in_staging.is_dir():
        # Chercher un fichier vidéo à l'intérieur du dossier stagé
        for root, _, files in os.walk(path_of_item_in_staging):
            for file_name in files:
                if any(file_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi', '.mov']):
                    main_video_file_to_move_source_path = Path(root) / file_name
                    original_filename_for_destination = file_name # On garde le nom original du fichier
                    break
            if main_video_file_to_move_source_path:
                break

    if not main_video_file_to_move_source_path or not main_video_file_to_move_source_path.exists():
        current_logger.error(f"_execute_sonarr_import_processing: Aucun fichier vidéo principal trouvé pour '{item_name_in_staging}'.")
        return False, f"Aucun fichier vidéo trouvé dans '{item_name_in_staging}'."

    current_logger.info(f"_execute_sonarr_import_processing: Fichier vidéo à déplacer: {main_video_file_to_move_source_path}")

    # Récupérer les détails de la série cible pour le chemin racine
    series_details_url = f"{sonarr_url.rstrip('/')}/api/v3/series/{series_id_target}"
    series_data, error_msg_series = _make_arr_request('GET', series_details_url, sonarr_api_key)

    if error_msg_series or not series_data:
        current_logger.error(f"_execute_sonarr_import_processing: Erreur détails série {series_id_target}: {error_msg_series}")
        return False, "Impossible de récupérer les détails de la série cible depuis Sonarr."

    series_root_folder_path_str = series_data.get('path')
    series_title_from_sonarr = series_data.get('title', 'Série Inconnue')
    if not series_root_folder_path_str:
        current_logger.error(f"_execute_sonarr_import_processing: Chemin racine non trouvé pour série {series_id_target}.")
        return False, "Chemin racine de la série non trouvé dans Sonarr."

    series_root_folder_path = Path(series_root_folder_path_str)

    # Construire le chemin de destination en utilisant forced_season_num_for_move
    season_folder_name = f"Season {str(forced_season_num_for_move).zfill(2)}"
    destination_season_folder_path = series_root_folder_path / season_folder_name
    destination_video_file_path = destination_season_folder_path / original_filename_for_destination

    current_logger.info(f"_execute_sonarr_import_processing: Déplacement final vers: {destination_video_file_path} (Saison {forced_season_num_for_move})")
    try:
        if not destination_season_folder_path.exists():
            destination_season_folder_path.mkdir(parents=True, exist_ok=True)
            current_logger.info(f"Dossier de saison créé: {destination_season_folder_path}")

        if os.path.normcase(str(main_video_file_to_move_source_path)) == os.path.normcase(str(destination_video_file_path)):
            current_logger.warning(f"_execute_sonarr_import_processing: Source et destination identiques.")
        else:
            shutil.move(str(main_video_file_to_move_source_path), str(destination_video_file_path))
        current_logger.info(f"_execute_sonarr_import_processing: Déplacement de '{original_filename_for_destination}' réussi.")
    except Exception as e_move:
        current_logger.error(f"_execute_sonarr_import_processing: Erreur shutil.move: {e_move}. Tentative copie/suppr.")
        try:
            shutil.copy2(str(main_video_file_to_move_source_path), str(destination_video_file_path))
            os.remove(str(main_video_file_to_move_source_path))
            current_logger.info(f"_execute_sonarr_import_processing: Copie/suppression de '{original_filename_for_destination}' réussie.")
        except Exception as e_copy:
            current_logger.error(f"_execute_sonarr_import_processing: Erreur copie/suppression fallback: {e_copy}")
            return False, f"Erreur lors du déplacement/copie du fichier: {e_copy}"

    # Nettoyage du dossier de release original dans le staging
    # original_release_folder_to_cleanup est le chemin du dossier qui contenait le fichier vidéo (ou le dossier de release)
    if original_release_folder_to_cleanup and original_release_folder_to_cleanup.exists():
        current_logger.info(f"_execute_sonarr_import_processing: Nettoyage du dossier de staging: {original_release_folder_to_cleanup}")
        time.sleep(1) # Petite attente
        if cleanup_staging_subfolder_recursively(str(original_release_folder_to_cleanup), staging_dir_str, orphan_exts):
            current_logger.info(f"_execute_sonarr_import_processing: Nettoyage staging pour '{original_release_folder_to_cleanup.name}' réussi.")
        else:
            current_logger.warning(f"_execute_sonarr_import_processing: Échec partiel nettoyage staging pour '{original_release_folder_to_cleanup.name}'.")

    # Rescan Sonarr
    rescan_payload = {"name": "RescanSeries", "seriesId": series_id_target}
    command_url = f"{sonarr_url.rstrip('/')}/api/v3/command"
    current_logger.debug(f"_execute_sonarr_import_processing: Envoi RescanSeries: Payload={rescan_payload}")
    _, error_msg_rescan = _make_arr_request('POST', command_url, sonarr_api_key, json_data=rescan_payload)

    final_msg = f"Fichier pour '{series_title_from_sonarr}' (S{forced_season_num_for_move}) déplacé vers la bibliothèque."
    if error_msg_rescan:
        final_msg += f" Le Rescan Sonarr a échoué: {error_msg_rescan}."
        return True, final_msg # Succès partiel (fichier déplacé mais rescan échoué)
    else:
        final_msg += " Rescan Sonarr initié."
        return True, final_msg
# FIN DE _execute_sonarr_import_processing
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
# ROUTE POUR AFFICHER LE CONTENU D'UN DOSSIER DISTANT DE LA SEEDBOX
# ------------------------------------------------------------------------------

@seedbox_ui_bp.route('/remote-view/<app_type_target>')
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
def sftp_retrieve_and_process_action():
    data = request.get_json()
    remote_path_posix = data.get('remote_path')
    app_type_of_remote_folder = data.get('app_type_of_remote_folder') # sonarr/radarr pour le type de dossier source
    target_series_id = data.get('target_series_id') # Si c'est pour Sonarr
    target_movie_id = data.get('target_movie_id')   # Si c'est pour Radarr

    # Récupérer la saison/épisode choisi par l'utilisateur s'il y a eu résolution de discordance
    # Ces paramètres sont envoyés par la fonction JS forceSonarrImport
    user_forced_season = data.get('target_season')
    user_forced_episode = data.get('target_episode') # Non utilisé par _handle_staged_sonarr_item pour le moment

    logger.info(f"SFTP Retrieve & Process: Remote='{remote_path_posix}', AppType='{app_type_of_remote_folder}', "
                f"SeriesID='{target_series_id}', MovieID='{target_movie_id}', "
                f"ForcedSeason='{user_forced_season}', ForcedEpisode='{user_forced_episode}'")

    sftp_host = current_app.config.get('SEEDBOX_SFTP_HOST')
    sftp_port = current_app.config.get('SEEDBOX_SFTP_PORT') # Récupération
    sftp_user = current_app.config.get('SEEDBOX_SFTP_USER') # Récupération
    sftp_password = current_app.config.get('SEEDBOX_SFTP_PASSWORD') # Récupération
    local_staging_dir_pathobj = Path(current_app.config.get('STAGING_DIR'))
    processed_log_file_str = current_app.config.get('PROCESSED_ITEMS_LOG_FILE_PATH_FOR_SFTP_SCRIPT')

    if not all([sftp_host, sftp_port, sftp_user, sftp_password, local_staging_dir_pathobj, processed_log_file_str]):
        logger.error("sftp_retrieve_and_process_action: Configuration SFTP, staging_dir ou log_file manquante.")
        return jsonify({"success": False, "error": "Configuration serveur incomplète pour cette action."}), 500

    if not remote_path_posix or not app_type_of_remote_folder or not (target_series_id or target_movie_id):
        return jsonify({"success": False, "error": "Données POST manquantes (chemin distant, type d'app ou ID cible)."}), 400

    item_basename_on_seedbox = Path(remote_path_posix).name
    local_staged_item_path_obj = local_staging_dir_pathobj / item_basename_on_seedbox

    # --- Étape 1: Rapatriement SFTP ---
    sftp_client = None; transport = None; success_download = False
    try:
        logger.debug(f"SFTP R&P: Connexion à {sftp_host}:{sftp_port} avec utilisateur {sftp_user}")
        transport = paramiko.Transport((sftp_host, int(sftp_port))) # Utilisation de sftp_port converti en int
        transport.set_keepalive(60) # Ajout keepalive
        transport.connect(username=sftp_user, password=sftp_password)
        sftp_client = paramiko.SFTPClient.from_transport(transport)
        logger.info(f"SFTP R&P: Connecté à {sftp_host}. Téléchargement de '{remote_path_posix}'.")

        success_download = _download_sftp_item_recursive_local(sftp_client, remote_path_posix, local_staged_item_path_obj, logger)

        if success_download:
            logger.info(f"SFTP R&P: Download de '{item_basename_on_seedbox}' réussi vers '{local_staged_item_path_obj}'.")
            if processed_log_file_str:
                # TODO: Ajouter la logique de mise à jour de processed_sftp_items.json ici si nécessaire
                # Pour l'instant, on logue seulement que le DL a réussi.
                # La logique de log est dans manual_sftp_download_action, pourrait être factorisée.
                logger.debug("SFTP R&P: La mise à jour du log des items traités n'est pas implémentée ici, mais le DL a réussi.")
                pass
        else:
            logger.error(f"SFTP R&P: Échec du téléchargement de '{remote_path_posix}'.")
            return jsonify({"success": False, "error": f"Échec du téléchargement SFTP de '{item_basename_on_seedbox}'."}), 500
    except paramiko.ssh_exception.AuthenticationException as e_auth:
        logger.error(f"SFTP R&P: Erreur d'authentification SFTP: {e_auth}")
        return jsonify({"success": False, "error": "Erreur d'authentification SFTP."}), 401
    except Exception as e_sftp_outer:
        logger.error(f"SFTP R&P: Erreur SFTP ('{remote_path_posix}'): {e_sftp_outer}", exc_info=True)
        return jsonify({"success": False, "error": f"Erreur SFTP lors du téléchargement: {e_sftp_outer}"}), 500
    finally:
        if sftp_client: sftp_client.close()
        if transport: transport.close()
        logger.debug("SFTP R&P: Connexion SFTP fermée.")

    # --- Étape 2: Appel au handler approprié si le téléchargement a réussi ---
    if success_download:
        logger.info(f"SFTP R&P: Rapatriement terminé. Traitement de '{item_basename_on_seedbox}' (localisé à '{local_staged_item_path_obj}')...")

        final_result_dict = None
        path_to_cleanup_after_success_abs = str(local_staged_item_path_obj) # Correction ici

        if app_type_of_remote_folder == 'sonarr' and target_series_id:
            final_result_dict = _handle_staged_sonarr_item(
                item_name_in_staging=item_basename_on_seedbox,
                series_id_target=target_series_id,
                path_to_cleanup_in_staging_after_success=path_to_cleanup_after_success_abs,
                user_chosen_season=data.get('target_season') # Vient du JS si discordance S/E a été résolue
            )
        elif app_type_of_remote_folder == 'radarr' and target_movie_id:
            final_result_dict = _handle_staged_radarr_item( # APPEL AU NOUVEAU HELPER RADARR
                item_name_in_staging=item_basename_on_seedbox,
                movie_id_target=target_movie_id,
                path_to_cleanup_in_staging_after_success=path_to_cleanup_after_success_abs
            )
        else:
            return jsonify({"success": False, "error": "Type d'app ou ID cible invalide pour traitement final."}), 400

        # Gérer la réponse du helper (qui peut inclure action_required pour Sonarr)
        if final_result_dict.get("action_required") == "resolve_season_episode_mismatch":
             logger.info(f"SFTP R&P: Discordance S/E détectée par le handler Sonarr, retour au frontend.")
             return jsonify(final_result_dict), 200
        elif final_result_dict.get("success"):
            flash(final_result_dict.get("message"), "success")
            return jsonify(final_result_dict), final_result_dict.get("status_code_override", 200)
        else: # Echec du handler
            flash(final_result_dict.get("error", "Erreur traitement final."), "danger")
            return jsonify(final_result_dict), final_result_dict.get("status_code_override", 500)
    else:
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

    # Si pas de discordance bloquante, appeler le handler.
    # path_to_cleanup_in_staging_after_success est le chemin complet de l'item cliqué dans l'UI.
    result_dict = _handle_staged_sonarr_item(
        item_name_in_staging=item_name_from_frontend, # Le nom de l'item tel que connu par l'UI du staging
        series_id_target=series_id_from_frontend,
        path_to_cleanup_in_staging_after_success=str(path_of_item_in_staging_abs),
        user_chosen_season=sonarr_season_num_for_validation # On passe la saison que Sonarr a identifiée (ou None si pas trouvée)
                                                            # _handle_staged_sonarr_item utilisera ça ou refera un scan.
                                                            # C'est mieux si _handle_staged_sonarr_item est autonome.
                                                            # Donc, on ne passe pas user_chosen_season ici si c'est le flux normal.
    )

    if result_dict.get("action_required") == "resolve_season_episode_mismatch": # Au cas où _handle_staged_sonarr_item le retourne
        return jsonify(result_dict), 200
    elif result_dict.get("success"):
        return jsonify(result_dict), result_dict.get("status_code_override", 200)
    else:
        return jsonify(result_dict), result_dict.get("status_code_override", 500)

# FIN de trigger_sonarr_import
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# NOUVELLE ROUTE POUR L'IMPORT FORCÉ SONARR (PLACÉE ICI)
# ------------------------------------------------------------------------------
@seedbox_ui_bp.route('/force-sonarr-import-action', methods=['POST'])
def force_sonarr_import_action():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name') # Nom de l'item UI original (dossier ou fichier du staging)
    series_id_from_frontend = data.get('series_id')
    target_season_for_move = data.get('target_season') # Saison choisie par l'utilisateur pour le déplacement

    logger.info(f"Force Sonarr Import Action pour item: '{item_name_from_frontend}', Série ID: {series_id_from_frontend}, Saison Cible: {target_season_for_move}")

    if not all([item_name_from_frontend, series_id_from_frontend, target_season_for_move is not None]):
        return jsonify({"success": False, "error": "Données manquantes pour l'import forcé."}), 400

    # original_release_folder_to_cleanup:
    # C'est le chemin du dossier de la release dans le staging qui doit être nettoyé.
    # Si item_name_from_frontend est un dossier, c'est lui. Si c'est un fichier, c'est son parent.
    staging_dir = Path(current_app.config.get('STAGING_DIR'))
    path_of_item_clicked_in_staging = staging_dir / item_name_from_frontend

    cleanup_folder = path_of_item_clicked_in_staging if path_of_item_clicked_in_staging.is_dir() else path_of_item_clicked_in_staging.parent

    success, message = _execute_sonarr_import_processing(
        item_name_in_staging=item_name_from_frontend, # L'item tel qu'il est dans le staging
        series_id_target=series_id_from_frontend,
        forced_season_num_for_move=target_season_for_move, # La saison que l'utilisateur a choisie
        original_release_folder_to_cleanup=cleanup_folder,
        current_logger=logger,
        app_config=current_app.config
    )

    if success:
        flash(message, "success")
        return jsonify({"success": True, "message": message})
    else:
        flash(message, "danger")
        return jsonify({"success": False, "error": message}), 500

# FIN DE force_sonarr_import_action (MODIFIÉE)
# ------------------------------------------------------------------------------
# trigger_radarr_import
# ------------------------------------------------------------------------------

@seedbox_ui_bp.route('/trigger-radarr-import', methods=['POST'])
def trigger_radarr_import():
    data = request.get_json()
    item_name_from_frontend = data.get('item_name') # Nom de l'item UI (dossier ou fichier dans le staging)
    movie_id_from_frontend = data.get('movie_id')

    logger.info(f"TRIGGER_RADARR_IMPORT: Début pour item '{item_name_from_frontend}', Movie ID {movie_id_from_frontend}")

    radarr_url = current_app.config.get('RADARR_URL')
    radarr_api_key = current_app.config.get('RADARR_API_KEY')
    staging_dir = current_app.config.get('STAGING_DIR')

    if not all([item_name_from_frontend, movie_id_from_frontend, radarr_url, radarr_api_key, staging_dir]):
        return jsonify({"success": False, "error": "Données manquantes ou Radarr non configuré."}), 400

    path_of_item_in_staging_abs = (Path(staging_dir) / item_name_from_frontend).resolve()
    if not path_of_item_in_staging_abs.exists():
        return jsonify({"success": False, "error": f"Item '{item_name_from_frontend}' non trouvé dans le staging."}), 404

    # Déterminer le chemin à scanner pour le GET manualimport initial
    path_to_scan_for_validation_get_obj = path_of_item_in_staging_abs.parent if path_of_item_in_staging_abs.is_file() else path_of_item_in_staging_abs
    path_for_api_get_validation_win = str(path_to_scan_for_validation_get_obj).replace('/', '\\')

    main_video_filename_for_validation = None
    if path_of_item_in_staging_abs.is_file():
        main_video_filename_for_validation = path_of_item_in_staging_abs.name
    elif path_of_item_in_staging_abs.is_dir():
        for f_name in os.listdir(path_of_item_in_staging_abs):
            if any(f_name.lower().endswith(ext) for ext in ['.mkv', '.mp4', '.avi']):
                main_video_filename_for_validation = f_name
                break

    if main_video_filename_for_validation: # Seulement si on a un fichier vidéo à valider
        manual_import_get_url = f"{radarr_url.rstrip('/')}/api/v3/manualimport"
        get_params = {'folder': path_for_api_get_validation_win, 'filterExistingFiles': 'false'}
        logger.debug(f"TRIGGER_RADARR_IMPORT (Validation MovieID): GET Radarr ManualImport: URL={manual_import_get_url}, Params={get_params}")
        manual_import_candidates, error_msg_get = _make_arr_request('GET', manual_import_get_url, radarr_api_key, params=get_params)

        if not error_msg_get and isinstance(manual_import_candidates, list):
            for candidate in manual_import_candidates:
                candidate_file_path_from_api = candidate.get('path')
                if not candidate_file_path_from_api: continue

                abs_cand_path_in_staging_val = (path_to_scan_for_validation_get_obj / candidate_file_path_from_api).resolve()

                if abs_cand_path_in_staging_val.name.lower() == main_video_filename_for_validation.lower():
                    candidate_movie_info = candidate.get('movie')
                    if candidate_movie_info and candidate_movie_info.get('id') is not None and candidate_movie_info.get('id') != movie_id_from_frontend:
                        logger.error(f"TRIGGER_RADARR_IMPORT: CONFLIT MovieID! Fichier '{main_video_filename_for_validation}' identifié par Radarr comme MovieID {candidate_movie_info.get('id')}, "
                                     f"mais l'utilisateur cible MovieID {movie_id_from_frontend}. Import annulé.")
                        return jsonify({"success": False, "error": f"Conflit d'identification Radarr: Le fichier semble correspondre à un autre film (ID {candidate_movie_info.get('id')}) que celui sélectionné (ID {movie_id_from_frontend})."}), 409
                    break # On a trouvé et validé notre fichier principal
    else:
        logger.info("TRIGGER_RADARR_IMPORT: Aucun fichier vidéo principal trouvé dans l'item pour validation Radarr ID. Passage direct au handler.")


    # Si pas de conflit majeur, appeler le handler
    result_dict = _handle_staged_radarr_item(
        item_name_in_staging=item_name_from_frontend,
        movie_id_target=movie_id_from_frontend,
        path_to_cleanup_in_staging_after_success=str(path_of_item_in_staging_abs)
    )

    if result_dict.get("success"):
        return jsonify(result_dict), result_dict.get("status_code_override", 200)
    else:
        return jsonify(result_dict), result_dict.get("status_code_override", 500)

# FIN de trigger_radarr_import


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