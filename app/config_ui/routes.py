# app/config_ui/routes.py (Version Finale et Complète)

import os
import logging
from flask import render_template, request, redirect, url_for, flash, current_app, jsonify
from . import config_ui_bp
from dotenv import dotenv_values, set_key

# Imports depuis nos modules utilitaires
from app.utils.prowlarr_client import get_prowlarr_categories
from app.utils.config_manager import load_search_categories, save_search_categories
from app.utils import backup_manager
from app.auth import login_required

logger = logging.getLogger(__name__)

@config_ui_bp.route('/', methods=['GET'])
@login_required
def show_config():
    """
    Affiche la page de configuration, incluant les variables .env
    et LA LISTE COMPLÈTE des catégories Prowlarr.
    """
    
    # --- PARTIE .ENV (INCHANGÉE) ---
    config_items = []
    try:
        # ... (la logique de parsing du .env.template reste exactement la même) ...
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        template_path = os.path.join(current_app.root_path, '..', '.env.template')
        env_values = dotenv_values(dotenv_path) if os.path.exists(dotenv_path) else {}
        if not os.path.exists(template_path):
            flash('Fichier .env.template introuvable !', 'danger')
        else:
            with open(template_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    if line.startswith('---') and line.endswith('---'): config_items.append({'type': 'header', 'text': line.strip('- ').strip()})
                    elif line.startswith('#'): config_items.append({'type': 'comment', 'text': line.strip('# ').strip()})
                    elif '=' in line:
                        key, default_value = line.split('=', 1)
                        key = key.strip()
                        current_value = env_values.get(key, default_value.strip())
                        is_password = any(s in key.upper() for s in ['PASSWORD', 'SECRET', 'TOKEN', 'API_KEY'])
                        # Détecter si la variable est une liste pour un meilleur affichage
                        is_list = key.upper().endswith('_LIST')
                        config_items.append({
                            'type': 'textarea' if is_list else 'variable',
                            'key': key,
                            'value': current_value,
                            'is_password': is_password
                        })
                    else: config_items.append({'type': 'description', 'text': line})
    except Exception as e:
        flash(f"Erreur lors de la lecture des fichiers de configuration : {e}", "danger")

    # --- PARTIE CATÉGORIES (SANS FILTRE) ---
    # On récupère toutes les catégories et on les envoie directement au template.
    all_prowlarr_categories = get_prowlarr_categories()
    search_config = load_search_categories()
    
    return render_template('config_ui/index.html',
                           title="Configuration de l'Application",
                           config_items=config_items,
                           all_categories=all_prowlarr_categories, # On passe la liste complète
                           search_config=search_config)


@config_ui_bp.route('/save', methods=['POST'])
@login_required
def save_config():
    """Sauvegarde les modifications du .env ET des catégories de recherche."""
    try:
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        
        # --- LOGIQUE DE SAUVEGARDE DES CATÉGORIES CORRIGÉE ---
        # Utilise getlist pour récupérer toutes les valeurs des checkboxes
        sonarr_cats_to_save = request.form.getlist('sonarr_categories', type=int)
        radarr_cats_to_save = request.form.getlist('radarr_categories', type=int)

        search_settings = {
            'sonarr_categories': sonarr_cats_to_save,
            'radarr_categories': radarr_cats_to_save
        }
        save_search_categories(search_settings)
        logging.info(f"Catégories de recherche sauvegardées : Sonarr={sonarr_cats_to_save}, Radarr={radarr_cats_to_save}")

        # --- LOGIQUE DE SAUVEGARDE DU .ENV (INCHANGÉE) ---
        # On ignore les clés de catégories pour ne pas les écrire dans le .env
        env_keys_to_ignore = ['sonarr_categories', 'radarr_categories']
        for key, value in request.form.items():
            if key not in env_keys_to_ignore:
                set_key(dotenv_path, key, value)

        # On ignore les clés de catégories pour ne pas les écrire dans le .env
        env_keys_to_ignore = ['sonarr_categories', 'radarr_categories']
        # Sauvegarde des variables .env
        form_keys = list(request.form.keys())
        for key in form_keys:
            if key not in env_keys_to_ignore:
                value = request.form[key]
                set_key(dotenv_path, key, value, quote_mode='always')

        flash("Configuration sauvegardée avec succès.", "success")

        # Vérifier si les paramètres de sauvegarde ont changé pour informer l'utilisateur
        backup_schedule_changed = 'BACKUP_SCHEDULE' in request.form
        backup_retention_changed = 'BACKUP_RETENTION' in request.form

        if backup_schedule_changed or backup_retention_changed:
            flash("Pour que les changements de planification de sauvegarde soient pris en compte, veuillez redémarrer l'application.", "info")

    except Exception as e:
        logging.error(f"Erreur lors de la sauvegarde de la configuration : {e}", exc_info=True)
        flash(f"Une erreur est survenue lors de la sauvegarde : {e}", "danger")
    
    return redirect(url_for('config_ui.show_config'))

# --- API Routes pour la gestion des sauvegardes ---

@config_ui_bp.route('/backups', methods=['GET'])
@login_required
def get_backups_list():
    """Retourne la liste des sauvegardes au format JSON."""
    backups = backup_manager.get_backups()
    return jsonify(backups)

@config_ui_bp.route('/backups/create', methods=['POST'])
@login_required
def manual_backup():
    """Déclenche une sauvegarde manuelle."""
    result = backup_manager.create_backup()
    if result:
        return jsonify({'success': True, 'message': 'Sauvegarde manuelle créée avec succès.'})
    else:
        return jsonify({'success': False, 'message': 'Erreur lors de la création de la sauvegarde manuelle.'}), 500

@config_ui_bp.route('/backups/<string:filename>/restore', methods=['POST'])
@login_required
def restore_backup(filename):
    """Restaure une sauvegarde spécifique."""
    success, message = backup_manager.restore_backup(filename)
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 500

@config_ui_bp.route('/backups/<string:filename>', methods=['DELETE'])
@login_required
def delete_backup(filename):
    """Supprime une sauvegarde spécifique."""
    success, message = backup_manager.delete_backup(filename)
    if success:
        return jsonify({'success': True, 'message': message})
    else:
        return jsonify({'success': False, 'message': message}), 500