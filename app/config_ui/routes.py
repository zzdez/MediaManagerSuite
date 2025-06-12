import secrets # Ajout de l'import secrets
from flask import render_template, request, redirect, url_for, session, flash, current_app
from . import config_ui_bp
from dotenv import set_key, load_dotenv, dotenv_values # Ajout pour la sauvegarde
from .utils import parse_template_env, DOTENV_PATH # Assurez-vous que DOTENV_PATH est défini dans utils.py

CONFIG_UI_AUTHENTICATED_KEY = 'config_ui_authenticated'

@config_ui_bp.before_request
def require_login():
    if request.endpoint and ('static' in request.endpoint or request.endpoint == 'config_ui.login'):
        return
    if not session.get(CONFIG_UI_AUTHENTICATED_KEY):
        return redirect(url_for('config_ui.login', next=request.url))

@config_ui_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get(CONFIG_UI_AUTHENTICATED_KEY):
        return redirect(url_for('config_ui.show_config'))

    if request.method == 'POST':
        password_form = request.form.get('password', '') # Default to empty string if not found
        config_password = current_app.config.get('CONFIG_UI_PASSWORD', '') # Default to empty string

        # Utilisation de compare_digest pour une comparaison sécurisée
        if config_password and secrets.compare_digest(password_form, config_password):
            session[CONFIG_UI_AUTHENTICATED_KEY] = True
            session.permanent = True
            next_page = request.args.get('next')
            flash('Connexion réussie.', 'success')
            return redirect(next_page or url_for('config_ui.show_config'))
        else:
            flash('Mot de passe incorrect. Vérifiez la variable CONFIG_UI_PASSWORD dans votre .env.', 'danger')
    
    return render_template('login_config.html', title="Connexion Configuration")

@config_ui_bp.route('/logout')
def logout():
    session.pop(CONFIG_UI_AUTHENTICATED_KEY, None)
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('config_ui.login'))

@config_ui_bp.route('/')
def show_config():
    # Récupérer les paramètres en utilisant la nouvelle fonction utilitaire
    params_list = parse_template_env()
    if not params_list:
        flash("Attention : Le fichier .env.template n'a pas pu être lu ou est vide. Impossible d'afficher la configuration.", "warning")
    
    # Le template 'configuration.html' a été créé comme fichier vide à l'étape 1 du plan.
    # Il sera rempli à l'étape suivante du plan général.
    return render_template('configuration.html', 
                           title="Configuration de l'Application", 
                           params=params_list)

@config_ui_bp.route('/save', methods=['POST'])
def save_config():
    if not session.get(CONFIG_UI_AUTHENTICATED_KEY):
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('config_ui.login'))

    # Récupérer la structure attendue et les types depuis template.env
    expected_params = parse_template_env()
    if not expected_params:
        flash("Erreur critique : Impossible de lire la structure de configuration depuis .env.template. Sauvegarde annulée.", "danger")
        return redirect(url_for('config_ui.show_config'))

    error_found = False
    changes_made = False

    for param_info in expected_params:
        if param_info.get('is_separator') or param_info.get('is_comment_general') or param_info.get('is_comment_block'):
            continue # Ignorer les éléments non-variables

        key_name = param_info['name']
        expected_type = param_info['type']
        current_value_from_file = param_info['current_value'] # Valeur avant modif, lue du .env

        # Traitement spécifique pour les booléens (checkboxes)
        if expected_type == 'bool':
            # Si le nom du champ (ex: 'DEBUG_MODE') est dans form, la case est cochée = True.
            # Sinon, elle n'est pas cochée = False.
            form_value = 'True' if key_name in request.form else 'False'
        else:
            form_value = request.form.get(key_name)

        # Si la valeur n'est pas trouvée dans le formulaire (ex: champ désactivé ou problème),
        # on ne la modifie pas, sauf si c'est un booléen (géré ci-dessus).
        if form_value is None and expected_type != 'bool':
            # current_app.logger.warning(f"Clé {key_name} non trouvée dans le formulaire de sauvegarde, ignorée.")
            # On pourrait choisir de ne rien faire ou de la considérer comme une chaîne vide.
            # Pour l'instant, on ne la modifie pas si elle n'est pas explicitement envoyée
            # (sauf pour les booléens).
            continue


        value_to_save = form_value

        # Validation et conversion de type (simple)
        if expected_type == 'int':
            try:
                value_to_save = str(int(form_value)) # Convertir en int puis reconvertir en str pour sauvegarde
            except ValueError:
                flash(f"Erreur de type pour '{key_name}': '{form_value}' n'est pas un entier valide. Non sauvegardé.", "danger")
                error_found = True
                continue # Ne pas sauvegarder cette clé
        elif expected_type == 'list_str':
            # Assurer que c'est une chaîne, les virgules sont gérées par l'utilisateur
            value_to_save = str(form_value)
        # Pour 'string', 'password', 'bool' (déjà string 'True'/'False'), pas de conversion spéciale ici.

        # Sauvegarder uniquement si la valeur a changé
        if value_to_save != str(current_value_from_file): # Comparer comme des chaînes
            try:
                set_key(DOTENV_PATH, key_name, value_to_save)
                # current_app.logger.info(f"Configuration sauvegardée: {key_name} = {value_to_save}")
                changes_made = True
            except Exception as e:
                flash(f"Erreur lors de la sauvegarde de '{key_name}' dans {DOTENV_PATH}: {e}", "danger")
                # current_app.logger.error(f"Erreur lors de la sauvegarde de '{key_name}' dans {DOTENV_PATH}: {e}")
                error_found = True
                continue
    
    if error_found:
        flash("Certaines valeurs n'ont pas été sauvegardées en raison d'erreurs.", "warning")
    elif changes_made:
        flash("Configuration sauvegardée avec succès. Certaines modifications peuvent nécessiter un redémarrage de l'application.", "success")
        # Recharger les variables d'environnement dans l'application actuelle si possible/nécessaire.
        # Note: Cela ne recharge pas la config de Flask si elle est déjà initialisée.
        # C'est surtout pour que `parse_template_env` lise les nouvelles valeurs la prochaine fois.
        load_dotenv(DOTENV_PATH, override=True)
        current_app.config.from_object('config.Config') # Tenter de recharger la config de l'app
                                                        # Cela peut avoir des effets limités sur les objets déjà initialisés.
    else:
        flash("Aucune modification détectée.", "info")

    return redirect(url_for('config_ui.show_config'))