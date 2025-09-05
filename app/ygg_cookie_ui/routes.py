import os
import json
from flask import (
    render_template, request, flash, redirect, url_for, current_app
)
from werkzeug.utils import secure_filename
from app.auth import login_required
from . import ygg_cookie_ui_bp

ALLOWED_EXTENSIONS = {'json'}

def allowed_file(filename):
    """Vérifie si l'extension du fichier est autorisée."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@ygg_cookie_ui_bp.route('/upload-cookie', methods=['GET', 'POST'])
@login_required
def upload_ygg_cookie():
    """
    Gère l'upload du fichier de cookies JSON.
    Enregistre le fichier dans instance/ygg_cookies.json.
    """
    if request.method == 'POST':
        if 'cookie_file' not in request.files:
            flash('Aucun fichier sélectionné.', 'danger')
            return redirect(request.url)

        file = request.files['cookie_file']
        if file.filename == '':
            flash('Aucun fichier sélectionné.', 'danger')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            try:
                file_content = file.read().decode('utf-8')
                cookies_data = json.loads(file_content)

                if not isinstance(cookies_data, list) or not all('name' in c and 'value' in c and 'expirationDate' in c for c in cookies_data):
                     raise ValueError("Le JSON doit être une liste d'objets contenant 'name', 'value', et 'expirationDate'.")

                instance_path = current_app.instance_path
                if not os.path.exists(instance_path):
                    os.makedirs(instance_path)

                save_path = os.path.join(instance_path, 'ygg_cookies.json')
                with open(save_path, 'w') as f:
                    json.dump(cookies_data, f, indent=4)

                flash('Le fichier de cookies JSON a été mis à jour avec succès.', 'success')
                return redirect(url_for('ygg_cookie_ui.upload_ygg_cookie'))

            except json.JSONDecodeError:
                flash('Erreur: Le fichier fourni n\'est pas un JSON valide.', 'danger')
            except ValueError as e:
                flash(f'Erreur de validation: {e}', 'danger')
            except Exception as e:
                current_app.logger.error(f"Erreur inattendue lors de l'upload du cookie YGG : {e}", exc_info=True)
                flash(f'Une erreur inattendue est survenue : {e}', 'danger')

            return redirect(request.url)
        else:
            flash('Type de fichier non autorisé. Veuillez utiliser un fichier .json.', 'warning')
            return redirect(request.url)

    return render_template('ygg_cookie_ui/upload.html')

# Supprimer l'ancienne route de rafraîchissement si elle existe toujours
# ou la laisser pour compatibilité si nécessaire, mais ici on la remplace.
# L'ancienne route /refresh-ygg-cookie est implicitement supprimée par ce nouveau contenu.
