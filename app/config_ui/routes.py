# app/config_ui/routes.py

import os
import logging
from flask import render_template, request, redirect, url_for, flash, current_app
from . import config_ui_bp  # Importe le Blueprint depuis __init__.py
from dotenv import dotenv_values, set_key

# Initialisation du logger pour ce module
logger = logging.getLogger(__name__)

@config_ui_bp.route('/', methods=['GET'])
@config_ui_bp.route('/configure', methods=['GET']) # Accepte les deux URLs pour être sûr
def show_config():
    """Affiche la page de configuration en se basant sur .env.template."""
    config_items = []
    
    try:
        # Construire les chemins de manière robuste à partir de la racine de l'app
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        template_path = os.path.join(current_app.root_path, '..', '.env.template')

        # Charger les valeurs actuelles du fichier .env pour les pré-remplir
        env_values = dotenv_values(dotenv_path) if os.path.exists(dotenv_path) else {}
        
        # Parser le template pour construire la page
        if not os.path.exists(template_path):
            flash('Fichier .env.template introuvable ! Impossible de charger la page de configuration.', 'danger')
        else:
            with open(template_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    
                    if not line:
                        continue # Ignore les lignes vides
                    
                    if line.startswith('---') and line.endswith('---'):
                        config_items.append({'type': 'header', 'text': line.strip('- ').strip()})
                    elif line.startswith('#'):
                        config_items.append({'type': 'comment', 'text': line.strip('# ').strip()})
                    elif '=' in line:
                        key, default_value = line.split('=', 1)
                        key = key.strip()
                        current_value = env_values.get(key, default_value.strip())
                        is_password = any(s in key.upper() for s in ['PASSWORD', 'SECRET', 'TOKEN', 'API_KEY'])
                        config_items.append({
                            'type': 'variable', 
                            'key': key, 
                            'value': current_value,
                            'is_password': is_password
                        })
                    else:
                        config_items.append({'type': 'description', 'text': line})

    except Exception as e:
        logger.error(f"Erreur critique lors de la construction de la page de configuration : {e}", exc_info=True)
        flash(f"Une erreur est survenue lors de la lecture des fichiers de configuration : {e}", "danger")

    return render_template('config_ui/index.html',
                           config_items=config_items,
                           title="Configuration de l'Application")

@config_ui_bp.route('/save', methods=['POST'])
def save_config():
    """Sauvegarde les modifications de la configuration dans le fichier .env."""
    try:
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        
        # Sauvegarder chaque clé reçue du formulaire
        for key, value in request.form.items():
            set_key(dotenv_path, key, value)
        
        flash("Configuration sauvegardée avec succès. Un redémarrage de l'application est nécessaire pour appliquer les changements.", "success")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de la configuration : {e}", exc_info=True)
        flash(f"Une erreur est survenue lors de la sauvegarde de la configuration : {e}", "danger")
    
    return redirect(url_for('config_ui.show_config'))