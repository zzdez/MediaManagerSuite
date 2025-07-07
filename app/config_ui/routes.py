import secrets
from flask import render_template, request, redirect, url_for, session, flash, current_app, get_flashed_messages
from . import config_ui_bp
from dotenv import set_key, load_dotenv # Removed dotenv_values as it's not directly used here, but in utils.
from .utils import parse_template_env, DOTENV_PATH
from app import login_required # Added import

from dotenv import dotenv_values # Ajout de l'import

@config_ui_bp.route('/')
@login_required
def show_config():
    """
    Affiche la page principale de l'interface de configuration.
    Lit .env.template et .env pour construire une liste d'items pour le template.
    """
    # DOTENV_PATH est défini dans app/config_ui/utils.py et importé
    # S'assurer que DOTENV_PATH pointe bien vers le fichier .env actuel
    env_file_path = DOTENV_PATH
    env_template_file_path = '.env.template' # Supposons qu'il est à la racine

    try:
        # Charger les valeurs actuelles du fichier .env pour les pré-remplir
        env_values = dotenv_values(env_file_path)
        if not os.path.exists(env_file_path):
            flash(f"Fichier .env non trouvé à '{env_file_path}'. Les valeurs actuelles ne peuvent pas être chargées. Les valeurs par défaut du template seront affichées.", "warning")
            current_app.logger.warning(f"Fichier .env non trouvé à '{env_file_path}' lors de l'affichage de la configuration.")
            env_values = {} # Utiliser un dictionnaire vide si .env n'existe pas
    except Exception as e:
        flash(f"Erreur lors de la lecture du fichier .env ({env_file_path}): {e}. Les valeurs par défaut du template seront affichées.", "danger")
        current_app.logger.error(f"Erreur lors de la lecture de {env_file_path}: {e}")
        env_values = {}

    config_items = []
    try:
        with open(env_template_file_path, 'r') as f:
            for line_number, line_content in enumerate(f, 1):
                line = line_content.strip()

                if not line:
                    config_items.append({'type': 'spacer'})
                    continue

                if line.startswith('---') and line.endswith('---'):
                    header_text = line.strip('- ').strip()
                    config_items.append({'type': 'header', 'text': header_text})
                elif line.startswith('#'):
                    comment_text = line.strip('# ')
                    # Distinguer les commentaires pleine ligne des commentaires en fin de variable (non géré ici car on lit .env.template)
                    config_items.append({'type': 'comment', 'text': comment_text})
                elif '=' in line:
                    key, default_value_template = line.split('=', 1)
                    key = key.strip()
                    default_value_template = default_value_template.strip()

                    # Utilise la valeur du .env actuel si elle existe, sinon la valeur du template
                    current_value = env_values.get(key, default_value_template)

                    # Gérer les commentaires en fin de ligne pour les variables
                    description_comment = ""
                    if '#' in default_value_template:
                        parts = default_value_template.split('#', 1)
                        default_value_template = parts[0].strip()
                        description_comment = parts[1].strip()
                        # Si current_value vient de env_values, il n'aura pas le commentaire.
                        # Si current_value est default_value_template, il faut aussi enlever le commentaire pour la valeur du champ.
                        if current_value == (parts[0].strip() + " # " + description_comment): # Si c'était la valeur par défaut avec commentaire
                             current_value = parts[0].strip()


                    config_items.append({
                        'type': 'variable',
                        'key': key,
                        'value': current_value, # Valeur à afficher dans le champ
                        'default_template_value': default_value_template, # Pour référence si besoin
                        'description': description_comment, # Commentaire descriptif
                        'is_password': 'PASSWORD' in key.upper() or 'SECRET_KEY' in key.upper() or 'TOKEN' in key.upper() or 'API_KEY' in key.upper()
                    })
                else:
                    # Gère les lignes de description qui ne sont ni des commentaires, ni des variables
                    # (Peu probable dans un .env.template standard, mais pour être complet)
                    config_items.append({'type': 'description', 'text': line})

        if not config_items: # Si le template était vide
             flash(f"Le fichier .env.template à '{env_template_file_path}' est vide ou n'a pas pu être parsé correctement.", "warning")

    except FileNotFoundError:
        flash(f"Erreur critique : Le fichier .env.template est introuvable à '{env_template_file_path}'. Impossible d'afficher la configuration.", "danger")
        current_app.logger.error(f".env.template non trouvé à '{env_template_file_path}'")
        return render_template('config_ui/index.html', config_items=[], title="Erreur de Configuration")
    except Exception as e:
        flash(f"Erreur inattendue lors de la lecture de .env.template : {e}", "danger")
        current_app.logger.error(f"Erreur inattendue lecture .env.template : {e}", exc_info=True)
        return render_template('config_ui/index.html', config_items=[], title="Erreur de Configuration")

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
