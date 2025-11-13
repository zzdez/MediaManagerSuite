# app/utils/backup_manager.py

import os
import zipfile
import logging
from datetime import datetime
from flask import current_app

logger = logging.getLogger(__name__)

def get_backup_dir():
    """Retourne le chemin du dossier des sauvegardes et le crée s'il n'existe pas."""
    backup_dir = os.path.join(current_app.instance_path, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def create_backup():
    """
    Crée une archive ZIP de tous les fichiers .json du dossier 'instance'.
    Retourne le chemin du fichier de sauvegarde créé ou None en cas d'erreur.
    """
    try:
        instance_path = current_app.instance_path
        backup_dir = get_backup_dir()

        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_filename = f'backup-{timestamp}.zip'
        backup_filepath = os.path.join(backup_dir, backup_filename)

        json_files_found = False
        with zipfile.ZipFile(backup_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(instance_path):
                # On ne veut pas sauvegarder le dossier des sauvegardes lui-même
                if root == backup_dir:
                    continue
                for file in files:
                    if file.endswith('.json'):
                        json_files_found = True
                        file_path = os.path.join(root, file)
                        # On stocke le chemin relatif à 'instance' pour faciliter la restauration
                        arcname = os.path.relpath(file_path, instance_path)
                        zipf.write(file_path, arcname)

        if not json_files_found:
            logger.warning("Aucun fichier .json n'a été trouvé dans le dossier 'instance' pour la sauvegarde.")
            os.remove(backup_filepath) # On supprime l'archive vide
            return None

        logger.info(f"Sauvegarde créée avec succès : {backup_filename}")
        manage_retention()
        return backup_filepath
    except Exception as e:
        logger.error(f"Erreur lors de la création de la sauvegarde : {e}", exc_info=True)
        return None

def manage_retention():
    """
    Vérifie le nombre de sauvegardes et supprime les plus anciennes
    si le nombre dépasse la limite définie dans la configuration.
    """
    try:
        retention_count = int(os.getenv('BACKUP_RETENTION', 7))
        backup_dir = get_backup_dir()

        backups = sorted(
            [os.path.join(backup_dir, f) for f in os.listdir(backup_dir) if f.endswith('.zip')],
            key=os.path.getmtime,
            reverse=True
        )

        if len(backups) > retention_count:
            files_to_delete = backups[retention_count:]
            for f in files_to_delete:
                os.remove(f)
                logger.info(f"Ancienne sauvegarde supprimée (rétention) : {os.path.basename(f)}")
    except (ValueError, TypeError) as e:
        logger.error(f"Erreur de configuration pour BACKUP_RETENTION. Doit être un nombre entier. Erreur : {e}")
    except Exception as e:
        logger.error(f"Erreur lors de la gestion de la rétention des sauvegardes : {e}", exc_info=True)


def get_backups():
    """
    Retourne une liste de dictionnaires contenant les informations
    sur les sauvegardes existantes, triées de la plus récente à la plus ancienne.
    """
    try:
        backup_dir = get_backup_dir()
        backups = []
        for filename in sorted(os.listdir(backup_dir), reverse=True):
            if filename.endswith('.zip'):
                filepath = os.path.join(backup_dir, filename)
                file_stat = os.stat(filepath)
                backups.append({
                    'filename': filename,
                    'size': f"{file_stat.st_size / 1024:.2f} KB",
                    'created_at': datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
        return backups
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de la liste des sauvegardes : {e}", exc_info=True)
        return []

def restore_backup(filename):
    """
    Restaure les fichiers d'une archive de sauvegarde spécifique
    dans le dossier 'instance'.
    """
    try:
        backup_dir = get_backup_dir()
        filepath = os.path.join(backup_dir, filename)

        if not os.path.exists(filepath):
            logger.error(f"Le fichier de sauvegarde '{filename}' n'existe pas.")
            return False, f"Le fichier de sauvegarde '{filename}' n'existe pas."

        with zipfile.ZipFile(filepath, 'r') as zipf:
            # La restauration se fait dans le dossier 'instance'
            zipf.extractall(current_app.instance_path)

        logger.info(f"Sauvegarde '{filename}' restaurée avec succès.")
        return True, f"Sauvegarde '{filename}' restaurée avec succès."
    except Exception as e:
        logger.error(f"Erreur lors de la restauration de la sauvegarde '{filename}': {e}", exc_info=True)
        return False, f"Erreur lors de la restauration : {e}"

def delete_backup(filename):
    """
    Supprime un fichier de sauvegarde spécifique.
    """
    try:
        backup_dir = get_backup_dir()
        filepath = os.path.join(backup_dir, filename)

        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Sauvegarde '{filename}' supprimée avec succès.")
            return True, f"Sauvegarde '{filename}' supprimée avec succès."
        else:
            logger.warning(f"Tentative de suppression d'une sauvegarde inexistante : {filename}")
            return False, "Le fichier n'existe pas."
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de la sauvegarde '{filename}': {e}", exc_info=True)
        return False, f"Erreur lors de la suppression : {e}"
