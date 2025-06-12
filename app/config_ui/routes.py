import secrets
from flask import render_template, request, redirect, url_for, session, flash, current_app, get_flashed_messages
from . import config_ui_bp
from dotenv import set_key, load_dotenv # Removed dotenv_values as it's not directly used here, but in utils.
from .utils import parse_template_env, DOTENV_PATH

CONFIG_UI_AUTHENTICATED_KEY = 'config_ui_authenticated' # Clé utilisée pour stocker l'état d'authentification dans la session.

@config_ui_bp.before_request
def require_login():
    """
    Exécuté avant chaque requête pour les routes de ce blueprint.
    Vérifie si l'utilisateur est authentifié pour accéder aux pages de configuration.
    Redirige vers la page de connexion si non authentifié, en conservant l'URL initialement demandée.
    Exclut la page de connexion elle-même et les fichiers statiques de cette vérification.
    """
    # Permettre l'accès aux fichiers statiques (CSS, JS) et à la page de login sans authentification.
    if request.endpoint and ('static' in request.endpoint or request.endpoint == 'config_ui.login'):
        return

    # Si l'utilisateur n'est pas authentifié (clé absente de la session), le rediriger vers la page de login.
    # 'next=request.url' est ajouté pour que l'utilisateur soit redirigé vers la page
    # qu'il tentait d'accéder après une connexion réussie.
    if not session.get(CONFIG_UI_AUTHENTICATED_KEY):
        return redirect(url_for('config_ui.login', next=request.url))

@config_ui_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Gère l'accès à l'interface de configuration.
    Si l'utilisateur est déjà connecté, il est redirigé vers la page de configuration.
    En méthode GET, affiche le formulaire de connexion.
    En méthode POST, vérifie le mot de passe fourni :
        - En cas de succès, enregistre l'authentification dans la session et redirige.
        - En cas d'échec, affiche un message d'erreur.
    """
    # Si l'utilisateur est déjà authentifié, le rediriger vers la page principale de configuration.
    if session.get(CONFIG_UI_AUTHENTICATED_KEY):
        return redirect(url_for('config_ui.show_config'))

    if request.method == 'POST':
        password_form = request.form.get('password', '') # Récupère le mot de passe du formulaire.
        # Récupère le mot de passe de configuration stocké dans la configuration de l'application.
        config_password = current_app.config.get('CONFIG_UI_PASSWORD', '')

        # Utilisation de secrets.compare_digest pour une comparaison de mots de passe
        # résistante aux attaques par canal auxiliaire (timing attacks).
        if config_password and secrets.compare_digest(password_form, config_password):
            session[CONFIG_UI_AUTHENTICATED_KEY] = True # Enregistre l'état authentifié.
            # Rend la session persistante (sa durée de vie est contrôlée par permanent_session_lifetime dans Flask).
            session.permanent = True
            next_page = request.args.get('next') # Vérifie si une URL de redirection 'next' est présente.
            flash('Connexion réussie.', 'success')
            # Redirige vers la page 'next' ou, par défaut, vers la page de configuration.
            return redirect(next_page or url_for('config_ui.show_config'))
        else:
            flash('Mot de passe incorrect. Vérifiez la variable CONFIG_UI_PASSWORD dans votre .env.', 'danger')

    # Afficher le formulaire de connexion pour une requête GET ou si la connexion POST a échoué.
    return render_template('login_config.html', title="Connexion Configuration")

@config_ui_bp.route('/logout')
def logout():
    """
    Gère la déconnexion de l'interface de configuration.
    Supprime l'indicateur d'authentification de la session et redirige vers la page de connexion.
    """
    session.pop(CONFIG_UI_AUTHENTICATED_KEY, None) # Supprime la clé d'authentification de la session.
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('config_ui.login'))

@config_ui_bp.route('/')
def show_config():
    """
    Affiche la page principale de l'interface de configuration.
    Utilise `parse_template_env` pour lire la structure et les valeurs actuelles des variables
    d'environnement (depuis `.env.template` et `.env`) et les passe au template.
    """
    # Récupère la liste des paramètres structurés (nom, valeur, type, description).
    params_list = parse_template_env()
    # Si .env.template est introuvable ou vide, `params_list` sera vide.
    # Un message d'avertissement est alors flashé à l'utilisateur.
    if not params_list:
        flash("Attention : Le fichier .env.template n'a pas pu être lu ou est vide. Impossible d'afficher la configuration.", "warning")

    # Rend le template 'configuration.html' en lui passant les paramètres.
    return render_template('configuration.html',
                           title="Configuration de l'Application",
                           params=params_list)

@config_ui_bp.route('/save', methods=['POST'])
def save_config():
    """
    Traite la soumission du formulaire de configuration.
    Sauvegarde les modifications apportées aux variables d'environnement dans le fichier .env.
    """
    # Mesure de sécurité : vérifier à nouveau l'authentification avant toute action de sauvegarde.
    if not session.get(CONFIG_UI_AUTHENTICATED_KEY):
        flash("Accès non autorisé.", "danger")
        return redirect(url_for('config_ui.login'))

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
