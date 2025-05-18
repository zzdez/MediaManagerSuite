import os
import shutil
import logging
import requests # Ajouté pour les appels API
from flask import Flask, render_template, request, redirect, url_for, flash
from requests.exceptions import RequestException # Pour gérer les erreurs de connexion

# Configuration du logging simple
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Crée une instance de l'application Flask
app = Flask(__name__)

# --- Configuration Obligatoire ---
app.config['SECRET_KEY'] = '[REDACTED_FLASK_SECRET_KEY]' # !!! CHANGEZ CECI !!!
STAGING_DIR = r"X:\seedbox_staging"

# --- Configuration API Sonarr/Radarr ---
SONARR_URL = "http://192.168.10.15:8989"
SONARR_API_KEY = "[REDACTED_SONARR_KEY]"

RADARR_URL = "http://192.168.10.15:7878"
RADARR_API_KEY = "[REDACTED_RADARR_KEY]"
# ---------------------------------------------------------------------

# --- Nouvelle fonction pour appeler les API *Arr ---
def call_arr_api(base_url, api_key, command_name, item_path):
    """Appelle l'API Sonarr/Radarr pour déclencher un scan."""
    # Détermine l'endpoint de l'API (v3 est courant pour les versions récentes)
    api_endpoint = f"{base_url.rstrip('/')}/api/v3/command"
    # Certains utilisent encore /api/ ; on pourrait ajouter une logique de test si v3 échoue

    headers = {
        'X-Api-Key': api_key,
        'Content-Type': 'application/json'
    }
    payload = {
        "name": command_name, # "DownloadedEpisodesScan" ou "DownloadedMoviesScan"
        "path": item_path,
        "importMode": "Move", # Tente de déplacer/supprimer après import
        "downloadClientId": "" # Peut généralement être laissé vide
        # D'autres paramètres pourraient être ajoutés si nécessaire (ex: tvdbId, tmdbId)
    }

    logging.info(f"Appel API vers {api_endpoint} - Commande: {command_name} - Chemin: {item_path}")

    try:
        response = requests.post(api_endpoint, headers=headers, json=payload, timeout=30) # Timeout de 30s
        response.raise_for_status() # Lève une exception pour les codes d'erreur HTTP (4xx ou 5xx)

        # L'API *Arr retourne souvent 201 Created pour une commande acceptée
        if response.status_code == 201:
            logging.info(f"Commande '{command_name}' acceptée par {base_url} pour '{os.path.basename(item_path)}'.")
            return True, f"Commande '{command_name}' envoyée avec succès pour '{os.path.basename(item_path)}'."
        else:
            # Cas où raise_for_status ne lèverait pas d'erreur mais le code n'est pas 201
            logging.warning(f"Réponse inattendue de {base_url} (Code: {response.status_code}): {response.text}")
            return False, f"Réponse inattendue de l'API (Code: {response.status_code}). Vérifiez les logs de l'application *Arr."

    except RequestException as e:
        logging.error(f"Erreur de communication avec l'API {base_url}: {e}")
        # Essayer de donner une erreur plus spécifique si possible
        error_details = str(e)
        if "Failed to establish a new connection" in error_details:
            return False, f"Erreur : Impossible de se connecter à {base_url}. L'URL est-elle correcte et l'application *Arr est-elle lancée ?"
        elif "401 Client Error: Unauthorized" in error_details:
             return False, f"Erreur 401 : Non autorisé. La clé API est-elle correcte pour {base_url} ?"
        elif "404 Client Error: Not Found" in error_details:
             return False, f"Erreur 404 : Non trouvé. L'URL de l'API ({api_endpoint}) est-elle correcte ?"
        else:
            return False, f"Erreur de communication avec l'API : {error_details}"
    except Exception as e:
        # Autre erreur inattendue
        logging.error(f"Erreur inattendue lors de l'appel API vers {base_url}: {e}")
        return False, f"Erreur inattendue : {e}"


@app.route('/')
def index():
    items = []
    if not os.path.isdir(STAGING_DIR):
        flash(f"Erreur : Le dossier de staging '{STAGING_DIR}' n'a pas été trouvé.", 'danger')
    else:
        try:
            items = os.listdir(STAGING_DIR)
            items.sort()
        except OSError as e:
            flash(f"Erreur lors de la lecture du dossier '{STAGING_DIR}': {e}", 'danger')

    return render_template('index.html',
                           items=items,
                           staging_dir=STAGING_DIR) # Plus besoin de passer les URLs ici

# Route pour gérer les actions (POST uniquement)
@app.route('/action', methods=['POST'])
def handle_action():
    action = request.form.get('action')
    item_name = request.form.get('item_name')

    if not item_name or not action:
        flash("Action ou nom d'item manquant.", 'warning')
        return redirect(url_for('index'))

    item_path = os.path.join(STAGING_DIR, item_name)
    logging.info(f"Action demandée : '{action}' pour l'item : '{item_path}'")

    if not os.path.exists(item_path):
        flash(f"L'item '{item_name}' n'existe plus dans le staging.", 'warning')
        return redirect(url_for('index'))

    # --- Logique pour chaque action ---
    if action == 'delete':
        try:
            if os.path.isfile(item_path):
                os.remove(item_path)
                logging.info(f"Fichier supprimé : {item_path}")
                flash(f"Fichier '{item_name}' supprimé avec succès.", 'success')
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
                logging.info(f"Dossier supprimé : {item_path}")
                flash(f"Dossier '{item_name}' supprimé avec succès.", 'success')
            else:
                logging.warning(f"Tentative de suppression d'un item non reconnu : {item_path}")
                flash(f"Impossible de déterminer le type de '{item_name}' pour le supprimer.", 'danger')
        except OSError as e:
            logging.error(f"Erreur lors de la suppression de '{item_path}': {e}")
            flash(f"Erreur lors de la suppression de '{item_name}': {e}", 'danger')

    elif action == 'sonarr':
        if not SONARR_URL or not SONARR_API_KEY or 'VOTRE_CLE_API' in SONARR_API_KEY:
             flash("L'URL ou la clé API de Sonarr ne sont pas configurées dans app.py.", 'danger')
        else:
            success, message = call_arr_api(SONARR_URL, SONARR_API_KEY, "DownloadedEpisodesScan", item_path)
            flash(message, 'success' if success else 'danger')

    elif action == 'radarr':
        if not RADARR_URL or not RADARR_API_KEY or 'VOTRE_CLE_API' in RADARR_API_KEY:
             flash("L'URL ou la clé API de Radarr ne sont pas configurées dans app.py.", 'danger')
        else:
            success, message = call_arr_api(RADARR_URL, RADARR_API_KEY, "DownloadedMoviesScan", item_path)
            flash(message, 'success' if success else 'danger')

    else:
        flash(f"Action inconnue : '{action}'", 'warning')
        logging.warning(f"Action inconnue reçue : {action} pour {item_path}")

    return redirect(url_for('index'))


if __name__ == '__main__':
    # ... (les vérifications au démarrage restent les mêmes) ...
     if 'VOTRE_CLE_API' in SONARR_API_KEY or 'VOTRE_CLE_API' in RADARR_API_KEY:
        logging.warning("**************************************************************")
        logging.warning("ATTENTION : Les URLs ou clés API Sonarr/Radarr ne semblent pas")
        logging.warning("            avoir été configurées dans app.py !")
        logging.warning("**************************************************************")
     if 'votre_super_cle_secrete_ici_a_changer' in app.config['SECRET_KEY']:
        logging.warning("**************************************************************")
        logging.warning("ATTENTION : La SECRET_KEY n'a pas été changée de sa valeur")
        logging.warning("            par défaut dans app.py ! Changez-la.")
        logging.warning("**************************************************************")

     app.run(host='0.0.0.0', port=5011, debug=True)