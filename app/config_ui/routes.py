# app/config_ui/routes.py (Version Unifiée)
import os
import logging
from flask import render_template, request, redirect, url_for, flash, current_app
from . import config_ui_bp
from dotenv import dotenv_values, set_key
from app.utils.prowlarr_client import get_prowlarr_categories
from app.utils.config_manager import load_search_categories, save_search_categories
from app.auth import login_required

logger = logging.getLogger(__name__)

@config_ui_bp.route('/', methods=['GET'])
@login_required
def show_config():
    """Affiche la page de configuration en se basant sur .env.template ET les catégories Prowlarr."""
    
    # --- PARTIE .ENV (INCHANGÉE) ---
    config_items = []
    try:
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        template_path = os.path.join(current_app.root_path, '..', '.env.template')
        env_values = dotenv_values(dotenv_path) if os.path.exists(dotenv_path) else {}
        if not os.path.exists(template_path):
            flash('Fichier .env.template introuvable !', 'danger')
        else:
            with open(template_path, 'r', encoding='utf-8') as f:
                for line in f:
                    # ... (la logique de parsing du .env.template reste exactement la même)
                    line = line.strip()
                    if not line: continue
                    if line.startswith('---') and line.endswith('---'): config_items.append({'type': 'header', 'text': line.strip('- ').strip()})
                    elif line.startswith('#'): config_items.append({'type': 'comment', 'text': line.strip('# ').strip()})
                    elif '=' in line:
                        key, default_value = line.split('=', 1)
                        key = key.strip()
                        current_value = env_values.get(key, default_value.strip())
                        is_password = any(s in key.upper() for s in ['PASSWORD', 'SECRET', 'TOKEN', 'API_KEY'])
                        config_items.append({'type': 'variable', 'key': key, 'value': current_value, 'is_password': is_password})
                    else: config_items.append({'type': 'description', 'text': line})
    except Exception as e:
        flash(f"Erreur lors de la lecture des fichiers de configuration : {e}", "danger")

    # --- PARTIE CATÉGORIES (LOGIQUE AMÉLIORÉE) ---
    all_categories = get_prowlarr_categories()
    search_config = load_search_categories()

    sonarr_display_categories = []
    radarr_display_categories = []

    sonarr_keywords = ['tv', 'séries', 'series', 'émissions', 'shows']
    radarr_keywords = ['movies', 'films', 'concert']

    for category in all_categories:
        cat_name = category['@attributes']['name'].lower()
        # Répartit les catégories dans les deux listes en fonction de mots-clés
        if any(keyword in cat_name for keyword in sonarr_keywords):
            sonarr_display_categories.append(category)
        elif any(keyword in cat_name for keyword in radarr_keywords):
            radarr_display_categories.append(category)

    return render_template('config_ui/index.html',
                           title="Configuration de l'Application",
                           config_items=config_items,
                           sonarr_categories=sonarr_display_categories,
                           radarr_categories=radarr_display_categories,
                           search_config=search_config)

@config_ui_bp.route('/save', methods=['POST'])
@login_required
def save_config():
    try:
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        
        # --- NOUVEAU: SÉPARER LES VARIABLES .ENV DES CATÉGORIES ---
        env_vars_to_save = {}
        sonarr_cats_to_save = []
        radarr_cats_to_save = []

        for key, value in request.form.items():
            if key.startswith('sonarr_category_'):
                sonarr_cats_to_save.append(int(value))
            elif key.startswith('radarr_category_'):
                radarr_cats_to_save.append(int(value))
            else:
                env_vars_to_save[key] = value

        # Sauvegarde des variables .env
        for key, value in env_vars_to_save.items():
            set_key(dotenv_path, key, value)
        
        # Sauvegarde des catégories
        search_settings = {
            'sonarr_categories': sonarr_cats_to_save,
            'radarr_categories': radarr_cats_to_save
        }
        save_search_categories(search_settings)

        flash("Configuration sauvegardée avec succès.", "success")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde : {e}", exc_info=True)
        flash(f"Une erreur est survenue : {e}", "danger")

    return redirect(url_for('config_ui.show_config'))