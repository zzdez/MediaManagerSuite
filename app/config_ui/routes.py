# app/config_ui/routes.py (Version Finale et Complète)

import os
import json
import logging
from flask import render_template, request, redirect, url_for, flash, current_app
from . import config_ui_bp
from dotenv import dotenv_values, set_key

# Imports depuis nos modules utilitaires
from app.utils.prowlarr_client import get_prowlarr_categories
from app.utils.config_manager import load_search_categories, save_search_categories
from app.utils.plex_mapping_manager import load_plex_mappings, save_plex_mappings
from app.auth import login_required # Utilisation du bon décorateur d'authentification

logger = logging.getLogger(__name__)

@config_ui_bp.route('/', methods=['GET'])
@login_required
def show_config():
    """
    Affiche la page de configuration, incluant les variables .env,
    les catégories Prowlarr et le mapping des bibliothèques Plex.
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
    all_prowlarr_categories = get_prowlarr_categories()
    search_config = load_search_categories()

    # --- PARTIE MAPPING BIBLIOTHÈQUES PLEX ---
    plex_mappings = load_plex_mappings()
    # On formate en JSON pour l'affichage dans le textarea
    plex_mappings_json = json.dumps(plex_mappings, indent=4)
    
    return render_template('config_ui/index.html',
                           title="Configuration de l'Application",
                           config_items=config_items,
                           all_categories=all_prowlarr_categories,
                           search_config=search_config,
                           plex_mappings_json=plex_mappings_json)


@config_ui_bp.route('/save', methods=['POST'])
@login_required
def save_config():
    """Sauvegarde les modifications du .env, des catégories et du mapping Plex."""
    try:
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        
        # --- SAUVEGARDE DU MAPPING PLEX ---
        plex_mappings_str = request.form.get('plex_mappings', '{}')
        try:
            plex_mappings_data = json.loads(plex_mappings_str)
            success, message = save_plex_mappings(plex_mappings_data)
            if not success:
                flash(f"Erreur lors de la sauvegarde du mapping Plex : {message}", "danger")
        except json.JSONDecodeError:
            flash("Erreur : Le format JSON du mapping des bibliothèques Plex est invalide.", "danger")

        # --- SAUVEGARDE DES CATÉGORIES ---
        sonarr_cats_to_save = request.form.getlist('sonarr_categories', type=int)
        radarr_cats_to_save = request.form.getlist('radarr_categories', type=int)
        search_settings = {
            'sonarr_categories': sonarr_cats_to_save,
            'radarr_categories': radarr_cats_to_save
        }
        save_search_categories(search_settings)

        # --- SAUVEGARDE DU .ENV ---
        env_keys_to_ignore = ['sonarr_categories', 'radarr_categories', 'plex_mappings']
        for key, value in request.form.items():
            if key not in env_keys_to_ignore:
                set_key(dotenv_path, key, value)

        flash("Configuration sauvegardée avec succès.", "success")
    except Exception as e:
        logging.error(f"Erreur lors de la sauvegarde de la configuration : {e}", exc_info=True)
        flash(f"Une erreur est survenue lors de la sauvegarde : {e}", "danger")
    
    return redirect(url_for('config_ui.show_config'))