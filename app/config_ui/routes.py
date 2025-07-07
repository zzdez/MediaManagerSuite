import os # Ajout de l'import os
import secrets
from flask import render_template, request, redirect, url_for, session, flash, current_app, get_flashed_messages
from . import config_ui_bp
from dotenv import set_key, load_dotenv # Removed dotenv_values as it's not directly used here, but in utils.
from .utils import parse_template_env, DOTENV_PATH
from app import login_required # Added import

from dotenv import dotenv_values # Ajout de l'import

@config_ui_bp.route('/configure', methods=['GET'])
@login_required
def show_config():
    """Affiche la page de configuration en se basant sur .env.template."""
    config_items = []
    env_values = {}
    
    try:
        # Construire les chemins de manière robuste à partir de la racine de l'app
        dotenv_path = os.path.join(current_app.root_path, '..', '.env')
        template_path = os.path.join(current_app.root_path, '..', '.env.template')

        # Charger les valeurs actuelles du fichier .env pour les pré-remplir
        if os.path.exists(dotenv_path):
            env_values = dotenv_values(dotenv_path)
        
        # Parser le template pour construire la page
        if not os.path.exists(template_path):
            flash('Fichier .env.template introuvable ! Impossible de charger la page de configuration.', 'danger')
        else:
            with open(template_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    
                    if not line:
                        continue # Ignore les lignes vides pour un meilleur espacement
                    
                    if line.startswith('---') and line.endswith('---'):
                        header_text = line.strip('- ').strip()
                        config_items.append({'type': 'header', 'text': header_text})
                    elif line.startswith('#'):
                        comment_text = line.strip('# ').strip()
                        config_items.append({'type': 'comment', 'text': comment_text})
                    elif '=' in line:
                        key, default_value = line.split('=', 1)
                        key = key.strip()
                        current_value = env_values.get(key, default_value.strip())
                        config_items.append({
                            'type': 'variable', 
                            'key': key, 
                            'value': current_value,
                            'is_password': 'PASSWORD' in key.upper() or 'SECRET' in key.upper() or 'TOKEN' in key.upper() or 'API_KEY' in key.upper()
                        })
                    else:
                        # Gère les lignes de description qui ne sont ni des commentaires, ni des variables
                        config_items.append({'type': 'description', 'text': line})

    except Exception as e:
        logger.error(f"Erreur critique lors de la construction de la page de configuration : {e}")
        flash(f"Une erreur est survenue lors de la lecture des fichiers de configuration : {e}", "danger")

    return render_template('config_ui/index.html',
                           config_items=config_items,
                           title="Configuration de l'Application")

@config_ui_bp.route('/save', methods=['POST'])
@login_required
def save_config():
    """
    Traite la soumission du formulaire de configuration.
    Sauvegarde les modifications apportées aux variables d'environnement dans le fichier .env.
    """
    # Récupérer la structure attendue des variables (noms, types par défaut) depuis .env.template.
    # Cela sert de référence pour savoir quelles variables traiter et comment les valider/convertir.
    expected_params = parse_template_env()
    if not expected_params: # Problème critique si .env.template n'est pas lisible.
        flash("Erreur critique : Impossible de lire la structure de configuration depuis .env.template. Sauvegarde annulée.", "danger")
        return redirect(url_for('config_ui.show_config'))

    error_found = False # Indicateur pour un feedback utilisateur en cas d'erreur de validation/sauvegarde.
    changes_made = False # Indicateur pour savoir si au moins une valeur a été effectivement modifiée.

    for param_info in expected_params:
        # Ignorer les éléments non-variables comme les séparateurs ou les blocs de commentaires purs.
        if param_info.get('is_separator') or param_info.get('is_comment_general') or param_info.get('is_comment_block'):
            continue

        key_name = param_info['name']
        expected_type = param_info['type']
        # Valeur actuelle lue du .env (ou la valeur par défaut du .env.template si non présente dans .env), avant modification.
        current_value_from_file = param_info['current_value']

        # Traitement spécifique pour les booléens (provenant de checkboxes HTML).
        # Une checkbox non cochée n'envoie pas sa clé dans les données du formulaire.
        if expected_type == 'bool':
            # Si le nom du champ (ex: 'FLASK_DEBUG') est présent dans request.form, la case était cochée (valeur 'True').
            # Sinon, elle n'était pas cochée (valeur 'False').
            form_value = 'True' if key_name in request.form else 'False'
        else:
            # Pour les autres types, récupérer la valeur du formulaire.
            form_value = request.form.get(key_name)

        # Si une valeur (non booléenne) n'est pas trouvée dans le formulaire (form_value is None),
        # cela peut indiquer un champ qui a été désactivé côté client ou un problème de soumission.
        # On choisit de ne pas modifier la variable correspondante dans .env si elle n'est pas explicitement envoyée.
        if form_value is None and expected_type != 'bool':
            current_app.logger.debug(f"Clé '{key_name}' non trouvée dans les données du formulaire POST, ignorée pour la sauvegarde.")
            continue

        value_to_save = form_value # Valeur à sauvegarder, potentiellement après conversion/validation.

        # Validation et conversion de type (exemple pour les entiers).
        if expected_type == 'int':
            try:
                # Convertir en int pour validation, puis reconvertir en str pour sauvegarde homogène dans .env.
                value_to_save = str(int(form_value))
            except ValueError:
                flash(f"Erreur de type pour '{key_name}': '{form_value}' n'est pas un entier valide. Non sauvegardé.", "danger")
                error_found = True
                continue # Ne pas sauvegarder cette clé en cas d'erreur de validation.
        elif expected_type == 'list_str':
            # Pour list_str, s'assurer que la valeur est une chaîne. La structure (virgules) est gérée par l'utilisateur.
            value_to_save = str(form_value)
        # Pour 'string', 'password', et 'bool' (déjà 'True'/'False'), pas de conversion spéciale nécessaire avant sauvegarde.

        # Sauvegarder la variable dans le fichier .env uniquement si la nouvelle valeur est différente de l'ancienne.
        # Toutes les valeurs sont comparées comme des chaînes, car c'est ainsi qu'elles sont stockées dans .env.
        if value_to_save != str(current_value_from_file):
            try:
                # Utilise python-dotenv pour écrire la paire clé/valeur dans le fichier .env spécifié.
                set_key(DOTENV_PATH, key_name, value_to_save)
                current_app.logger.info(f"Configuration sauvegardée: {key_name} = '{value_to_save}'")
                changes_made = True
            except Exception as e: # Intercepter les erreurs potentielles lors de l'écriture du fichier.
                flash(f"Erreur lors de la sauvegarde de '{key_name}' dans {DOTENV_PATH}: {e}", "danger")
                current_app.logger.error(f"Erreur lors de la sauvegarde de '{key_name}' dans {DOTENV_PATH}: {e}")
                error_found = True
                continue # Passer à la clé suivante en cas d'erreur d'écriture.

    # Fournir un feedback global à l'utilisateur basé sur le résultat des opérations.
    if error_found:
        flash("Certaines valeurs n'ont pas été sauvegardées en raison d'erreurs de validation ou d'écriture.", "warning")
    elif changes_made:
        flash("Configuration sauvegardée avec succès. Certaines modifications peuvent nécessiter un redémarrage de l'application pour prendre pleinement effet.", "success")
        # Tentative de rechargement des variables d'environnement pour la session applicative actuelle.
        # Note: Cela recharge les variables pour python-dotenv et peut affecter os.environ si `override=True`.
        # Cependant, la configuration de Flask (app.config) et les objets déjà initialisés avec
        # d'anciennes valeurs de configuration pourraient ne pas être mis à jour dynamiquement par cette action.
        # Un redémarrage manuel de l'application reste la méthode la plus sûre pour garantir la prise en compte de toutes les modifications.
        load_dotenv(DOTENV_PATH, override=True)
        # Tenter de recharger la configuration de l'application Flask à partir de l'objet Config.
        # L'efficacité de cette action dépend de la manière dont l'application utilise sa configuration après le démarrage initial.
        current_app.config.from_object('config.Config')
    else:
        flash("Aucune modification n'a été détectée dans les valeurs soumises.", "info")

    return redirect(url_for('config_ui.show_config')) # Rediriger vers la page de configuration pour voir les changements.
