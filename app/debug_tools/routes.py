# app/debug_tools/routes.py
import os
from flask import Blueprint, render_template, request, flash, current_app, redirect, url_for, jsonify
from app.auth import login_required
from app.utils.mapping_manager import add_or_update_torrent_in_map
from pathlib import Path

debug_tools_bp = Blueprint(
    'debug_tools',
    __name__,
    template_folder='templates'
)

@debug_tools_bp.route('/staging_simulator')
@login_required
def staging_simulator_page():
    """Affiche la page du simulateur de staging."""
    return render_template('debug_tools/staging_simulator.html', title="Simulateur de Staging")

@debug_tools_bp.route('/staging_simulator/run', methods=['POST'])
@login_required
def run_staging_simulation():
    """Crée un faux item pour que le staging_processor le traite."""
    release_name = request.form.get('release_name')
    torrent_hash = request.form.get('torrent_hash')
    app_type = request.form.get('app_type') # 'sonarr' ou 'radarr'
    target_id = request.form.get('target_id')

    if not all([release_name, torrent_hash, app_type, target_id]):
        flash("Tous les champs sont requis.", "danger")
        return redirect(url_for('debug_tools.staging_simulator_page'))

    try:
        # 1. Créer un faux fichier dans le répertoire de staging
        staging_path = current_app.config.get('LOCAL_STAGING_PATH')
        if not staging_path:
            raise ValueError("LOCAL_STAGING_PATH n'est pas configuré.")

        fake_file_path = Path(staging_path) / release_name
        # S'assurer que le dossier parent existe (si la release simule un dossier)
        fake_file_path.parent.mkdir(parents=True, exist_ok=True)
        # Créer le fichier
        with open(fake_file_path, 'w') as f:
            f.write(f"Fichier de simulation pour {release_name}")

        current_app.logger.info(f"SIMULATEUR: Faux fichier créé à '{fake_file_path}'")

        # 2. Ajouter une entrée dans le mapping avec le statut 'pending_staging'
        add_or_update_torrent_in_map(
            release_name=release_name,
            torrent_hash=torrent_hash.upper(),
            status='pending_staging',
            seedbox_download_path=f"/simulated/path/{release_name}",
            folder_name=release_name,
            app_type=app_type,
            target_id=str(target_id),
            label='simulation',
            original_torrent_name=release_name
        )
        current_app.logger.info(f"SIMULATEUR: Entrée de mapping créée pour le hash {torrent_hash.upper()}")

        flash(f"Simulation lancée pour '{release_name}'. Le staging processor le traitera au prochain cycle.", "success")

    except Exception as e:
        current_app.logger.error(f"SIMULATEUR: Erreur lors du lancement de la simulation: {e}", exc_info=True)
        flash(f"Erreur de simulation : {e}", "danger")

    return redirect(url_for('debug_tools.staging_simulator_page'))

@debug_tools_bp.route('/clear_trailer_cache', methods=['POST'])
@login_required
def clear_trailer_cache():
    """Supprime le fichier de cache des trailers."""
    try:
        # Le chemin est relatif au répertoire racine de l'instance
        cache_file_path = Path(current_app.instance_path) / 'trailer_cache.json'

        if cache_file_path.exists():
            os.remove(cache_file_path)
            message = "Fichier de cache des trailers ('instance/trailer_cache.json') supprimé avec succès."
            current_app.logger.info(f"DEBUG: {message}")
            return jsonify({'success': True, 'message': message})
        else:
            message = "Aucun fichier de cache à supprimer."
            current_app.logger.info(f"DEBUG: {message}")
            return jsonify({'success': True, 'message': message})

    except Exception as e:
        error_message = f"Erreur lors de la suppression du cache des trailers: {e}"
        current_app.logger.error(error_message, exc_info=True)
        return jsonify({'success': False, 'error': error_message}), 500
