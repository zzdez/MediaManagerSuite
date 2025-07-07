# app/plex_editor/utils.py
import os
import shutil
from flask import current_app, flash

# --- Fonctions d'aide pour la configuration (celles qui restent utiles ici) ---
def _is_dry_run_mode():
    return not current_app.config.get('PERFORM_ACTUAL_DELETION', False)

def _get_orphan_extensions():
    return current_app.config.get('ORPHAN_CLEANER_EXTENSIONS', [])


# --- Fonctions de vérification du contenu ---
def _is_file_ignorable(filename, orphan_extensions):
    filename_lower = filename.lower()
    if not filename_lower.startswith('.') and filename_lower in [ext.lower() for ext in orphan_extensions if not ext.startswith('.')]:
        return True
    return any(filename_lower.endswith(ext.lower()) for ext in orphan_extensions if ext.startswith('.'))

# MODIFIÉE pour accepter active_plex_library_roots
def _is_directory_content_ignorable(dir_path, orphan_extensions, active_plex_library_roots, level=0, max_recursion_depth_for_subfolders=1):
    if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
        current_app.logger.debug(f"Nettoyage: _is_directory_content_ignorable: Chemin '{dir_path}' non valide.")
        return False
    if level > max_recursion_depth_for_subfolders:
        current_app.logger.warning(f"Nettoyage: _is_directory_content_ignorable: Profondeur max ({max_recursion_depth_for_subfolders}) atteinte pour '{dir_path}'.")
        return False

    current_app.logger.debug(f"Nettoyage (level {level}): _is_directory_content_ignorable: Vérification contenu de '{dir_path}'.")

    norm_dir_path = os.path.normpath(dir_path)
    # Utilisation de active_plex_library_roots passé en argument
    if any(norm_dir_path == root for root in active_plex_library_roots):
        current_app.logger.info(f"Nettoyage: _is_directory_content_ignorable: '{dir_path}' est un chemin racine de bibliothèque Plex. Non ignorable.")
        return False

    dir_listing = os.listdir(dir_path)
    if not dir_listing:
        current_app.logger.debug(f"Nettoyage: _is_directory_content_ignorable: '{dir_path}' est vide.")
        return True

    for item_name in dir_listing:
        item_path = os.path.join(dir_path, item_name)
        if os.path.isfile(item_path):
            if not _is_file_ignorable(item_name, orphan_extensions):
                current_app.logger.debug(f"Nettoyage: _is_directory_content_ignorable: Fichier non ignorable '{item_name}' dans '{dir_path}'.")
                return False
        elif os.path.isdir(item_path):
            # Passer active_plex_library_roots à l'appel récursif
            if not _is_directory_content_ignorable(item_path, orphan_extensions, active_plex_library_roots, level + 1, max_recursion_depth_for_subfolders):
                current_app.logger.debug(f"Nettoyage: _is_directory_content_ignorable: Sous-dossier '{item_name}' dans '{dir_path}' a contenu non ignorable.")
                return False
        else:
            current_app.logger.debug(f"Nettoyage: _is_directory_content_ignorable: Type non géré '{item_name}' dans '{dir_path}'.")
            return False

    current_app.logger.debug(f"Nettoyage: _is_directory_content_ignorable: Contenu de '{dir_path}' (level {level}) entièrement ignorable.")
    return True

# --- Fonction Principale de Nettoyage ---
# MODIFIÉE pour accepter dynamic_plex_library_roots et base_paths_guards
def cleanup_parent_directory_recursively(media_filepath,
                                         dynamic_plex_library_roots,
                                         base_paths_guards, # <<< NOM CORRECT DU PARAMÈTRE
                                         _current_level=0,
                                         max_levels_up=5):
    is_dry_run = _is_dry_run_mode()
    dry_run_prefix = "[SIMULATION] " if is_dry_run else ""

    if not media_filepath:
        current_app.logger.warning(f"{dry_run_prefix}Nettoyage: Appel avec media_filepath vide. Arrêt.")
        return

    if _current_level == 0:
        current_app.logger.info(f"--- {dry_run_prefix}Nettoyage de dossier DEMARRÉ pour le parent de: {media_filepath} ---")

    if _current_level >= max_levels_up:
        current_app.logger.info(f"{dry_run_prefix}Nettoyage: Limite de {max_levels_up} niveaux de remontée atteinte. Arrêt pour '{media_filepath}'.")
        return

    if _current_level == 0:
        dir_to_check = os.path.dirname(os.path.abspath(media_filepath))
    else:
        dir_to_check = os.path.abspath(media_filepath)

    current_app.logger.info(f"{dry_run_prefix}Nettoyage (niveau {_current_level + 1}): Vérification de '{dir_to_check}'.")

    # --- Garde-fous Importants ---
    if not os.path.exists(dir_to_check):
        current_app.logger.info(f"{dry_run_prefix}Le répertoire '{dir_to_check}' n'existe plus (probablement supprimé par Plex ou une action précédente).")

        parent_to_check_next = os.path.dirname(dir_to_check)

        # On remonte si le parent est différent du dossier actuel (pas à la racine)
        if parent_to_check_next != dir_to_check:
             current_app.logger.info(f"{dry_run_prefix}Nettoyage: Le dossier '{os.path.basename(dir_to_check)}' n'existant plus, tentative de vérification du parent '{parent_to_check_next}'.")
             cleanup_parent_directory_recursively(parent_to_check_next, # On passe le chemin du dossier parent
                                                  dynamic_plex_library_roots,
                                                  base_paths_guards,
                                                  _current_level + 1,
                                                  max_levels_up)
        else:
            current_app.logger.info(f"{dry_run_prefix}Nettoyage: Racine ('{dir_to_check}') atteinte après constatation de sa non-existence (ou de celle de son enfant). Arrêt de la remontée.")
        return # Important de retourner ici car dir_to_check n'existe plus
    if not os.path.isdir(dir_to_check):
        current_app.logger.warning(f"{dry_run_prefix}Chemin '{dir_to_check}' n'est pas un répertoire. Arrêt.")
        return

    norm_dir_to_check = os.path.normpath(dir_to_check)
    if any(norm_dir_to_check == root for root in dynamic_plex_library_roots):
        msg = f"Nettoyage: '{dir_to_check}' est un chemin racine de bibliothèque Plex (dynamique). Non supprimé."
        current_app.logger.info(f"{dry_run_prefix}{msg}")
        if _current_level == 0: flash(msg, "info")
        return

    # Utilisation de base_paths_guards (nom correct du paramètre)
    if base_paths_guards:
        is_protected_by_a_guard = False
        current_app.logger.debug(f"Nettoyage: Vérification des garde-fous pour '{norm_dir_to_check}'. Gardes-fous fournis: {base_paths_guards}") # LOG 0
        for guard_path_from_list in base_paths_guards:
            norm_guard = os.path.abspath(os.path.normpath(guard_path_from_list))
            current_path_to_evaluate = os.path.abspath(norm_dir_to_check)

            # LOGS DE DÉBOGAGE DÉTAILLÉS
            current_app.logger.debug(f"Nettoyage GUARD CHECK: CurrentPath='{current_path_to_evaluate}', Guard='{norm_guard}'") # LOG 1
            condition1 = (current_path_to_evaluate == norm_guard)
            # Pour startswith, s'assurer que norm_guard a un séparateur final si ce n'est pas juste le lecteur
            guard_for_startswith = norm_guard
            if not norm_guard.endswith(os.sep): # S'il ne finit pas par ex: '\', on l'ajoute
                 guard_for_startswith += os.sep

            # Sauf si norm_guard est juste la racine du lecteur (ex: D:\), auquel cas startswith("D:\") est bon.
            # Si norm_guard est "D:", guard_for_startswith devient "D:\"
            # Si norm_guard est "D:\foo", guard_for_startswith devient "D:\foo\"

            condition2 = current_path_to_evaluate.startswith(guard_for_startswith)

            current_app.logger.debug(f"Nettoyage GUARD CHECK: Cond1 (equals): {condition1}, GuardForStartswith: '{guard_for_startswith}', Cond2 (startswith): {condition2}") # LOG 2

            if condition1 or condition2:
                is_protected_by_a_guard = True
                current_app.logger.debug(f"Nettoyage: '{current_path_to_evaluate}' EST protégé par le garde-fou '{norm_guard}'.") # LOG 3
                break
            else:
                current_app.logger.debug(f"Nettoyage: '{current_path_to_evaluate}' N'EST PAS protégé par ce garde-fou spécifique '{norm_guard}'.") # LOG 4

        if not is_protected_by_a_guard:
            msg = f"Nettoyage: '{dir_to_check}' n'est sous la protection d'aucun des chemins de garde configurés: {base_paths_guards}. Arrêt de la remontée."
            current_app.logger.info(f"{dry_run_prefix}{msg}") # Ce log apparaît
            if _current_level == 0: flash(msg, "warning")
            return
    else:
        current_app.logger.warning(f"{dry_run_prefix}Aucun base_paths_guards fourni. La remontée pourrait être risquée.")
        if _current_level == 0: flash("Avertissement: Aucun garde-fou de chemin de base pour le nettoyage.", "warning")


    orphan_extensions = _get_orphan_extensions()
    if _is_directory_content_ignorable(dir_to_check, orphan_extensions, dynamic_plex_library_roots):
        action_description = "serait supprimé" if is_dry_run else "va être supprimé"
        current_app.logger.info(f"{dry_run_prefix}Répertoire '{dir_to_check}' {action_description} (contenu ignorable).")
        dir_basename_for_flash = os.path.basename(dir_to_check)

        if not is_dry_run:
            try:
                shutil.rmtree(dir_to_check)
                success_msg = f"Nettoyage: Dossier '{dir_basename_for_flash}' supprimé."
                current_app.logger.info(success_msg + f" Chemin: {dir_to_check}")
                if _current_level == 0: flash(success_msg, "success")
            except Exception as e_rm:
                err_msg = f"Erreur suppression de '{dir_to_check}': {e_rm}"
                current_app.logger.error(err_msg, exc_info=True)
                if _current_level == 0: flash(f"Erreur suppression dossier '{dir_basename_for_flash}': {type(e_rm).__name__}.", "danger")
                return
        else:
            if _current_level == 0:
                 flash(f"[SIMULATION] Nettoyage: Dossier '{dir_basename_for_flash}' (et contenu ignorable) serait supprimé.", "info")

        parent_dir = os.path.dirname(dir_to_check)
        if parent_dir != dir_to_check :
             cleanup_parent_directory_recursively(parent_dir,
                                                  dynamic_plex_library_roots,
                                                  base_paths_guards, # UTILISER LE NOM CORRECT
                                                  _current_level + 1,
                                                  max_levels_up)
        else:
            current_app.logger.info(f"{dry_run_prefix}Nettoyage: Racine atteinte à '{dir_to_check}'. Arrêt.")
    else:
        current_app.logger.info(f"{dry_run_prefix}Répertoire '{dir_to_check}' contient des éléments non ignorables. Arrêt pour cette branche.")
        if _current_level == 0: flash(f"Nettoyage: Dossier '{os.path.basename(dir_to_check)}' contient des éléments importants et n'a pas été supprimé.", "info")

# --- Fonction get_media_filepath (inchangée) ---
def get_media_filepath(item):
    # ... (votre code existant) ...
    try:
        if hasattr(item, 'media') and item.media and \
           hasattr(item.media[0], 'parts') and item.media[0].parts and \
           hasattr(item.media[0].parts[0], 'file'):
            return item.media[0].parts[0].file
        current_app.logger.warning(f"Chemin de fichier non trouvé pour l'item: {getattr(item, 'title', item.ratingKey)}")
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la récupération du chemin du fichier pour {getattr(item, 'title', item.ratingKey)}: {e}", exc_info=True)
    return None