# app/config_ui/routes.py (Version Finale et Complète)

import os
import logging
from flask import render_template, request, redirect, url_for, flash, current_app
from . import config_ui_bp
from dotenv import dotenv_values, set_key

# Imports depuis nos modules utilitaires
from app.utils.prowlarr_client import get_prowlarr_categories
from app.utils.config_manager import load_search_categories, save_search_categories
from app.auth import login_required # Utilisation du bon décorateur d'authentification

logger = logging.getLogger(__name__)

@config_ui_bp.route('/', methods=['GET'])
@login_required
def show_config():
    """Affiche la page de configuration et la section des catégories filtrées par la whitelist COMPLÈTE."""
    
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

    # --- PARTIE CATÉGORIES (AVEC LES WHITELISTS COMPLÈTES ET VÉRIFIÉES) ---
    SONARR_WHITELIST = [
        5000, 5030, 5040, 5050, 5060, 5070, 5080, 100013, 100014, 100015, 100016, 100017,
        100030, 100032, 100034, 100098, 100101, 100104, 100109, 100110, 100123,
        102179, 102182, 102184, 102186 # Ajout Sport de Ygg
    ]
    RADARR_WHITELIST = [
        2000, 2020, 2030, 2040, 2045, 2050, 2060, 2070, 2080, 100001, 100003, 100004,
        100005, 100006, 100007, 100008, 100009, 100012, 100020, 100031, 100033,
        100094, 100095, 100100, 100107, 100118, 100119, 100122, 100125, 100126,
        100127, 102145, 102178, 102180, 102181, 102183, 102185, 102187
    ]
    
    all_categories = get_prowlarr_categories()
    search_config = load_search_categories()
    
    sonarr_display_categories = [cat for cat in all_categories if int(cat['@attributes']['id']) in SONARR_WHITELIST]
    radarr_display_categories = [cat for cat in all_categories if int(cat['@attributes']['id']) in RADARR_WHITELIST]

    return render_template('config_ui/index.html',
                           title="Configuration de l'Application",
                           config_items=config_items,
                           sonarr_categories=sonarr_display_categories,
                           radarr_categories=radarr_display_categories,
                           search_config=search_config)


@config_ui_bp.route('/save', methods=['POST'])
@login_required
def save_config():
    """Sauvegarde les modifications du .env ET des catégories de recherche."""
    try:
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        
        env_vars_to_save = {}
        sonarr_cats_to_save = []
        radarr_cats_to_save = []

        for key, value in request.form.items():
            if key.startswith('sonarr_categories'):
                sonarr_cats_to_save.append(int(value))
            elif key.startswith('radarr_categories'):
                radarr_cats_to_save.append(int(value))
            else:
                env_vars_to_save[key] = value

        # Sauvegarde des variables .env
        for key, value in env_vars_to_save.items():
            set_key(dotenv_path, key, value)
        
        # Sauvegarde des catégories
        search_settings = {'sonarr_categories': sonarr_cats_to_save, 'radarr_categories': radarr_cats_to_save}
        save_search_categories(search_settings)

        flash("Configuration sauvegardée avec succès. Certains changements peuvent nécessiter un redémarrage.", "success")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de la configuration : {e}", exc_info=True)
        flash(f"Une erreur est survenue lors de la sauvegarde : {e}", "danger")
    
    return redirect(url_for('config_ui.show_config'))