# app/api/routes.py
import re
from datetime import datetime, timedelta
from flask import jsonify, current_app
from . import api_bp
from app.utils.plex_mapping_manager import load_plex_mappings
from app.auth import login_required
from app.utils.cookie_manager import check_ygg_cookie_validity
from app.utils.plex_client import get_user_specific_plex_server
from app.utils.arr_client import get_sonarr_root_folders, get_radarr_root_folders

@api_bp.route('/mappings', methods=['GET'])
@login_required
def get_mappings():
    """
    Endpoint API pour récupérer la configuration du mapping des bibliothèques Plex.
    """
    mappings = load_plex_mappings()
    return jsonify(mappings)

@api_bp.route('/cookie/status', methods=['GET'])
@login_required
def get_cookie_status():
    """
    Vérifie la validité du cookie YGG et retourne son statut.
    """
    is_valid, expires_in_seconds, status_message = check_ygg_cookie_validity()

    return jsonify({
        'is_valid': is_valid,
        'expires_in_seconds': expires_in_seconds,
        'status_message': status_message
    })

@api_bp.route('/mapping-data', methods=['GET'])
@login_required
def get_mapping_data():
    """
    Agrège toutes les données nécessaires pour l'interface de mapping dynamique.
    """
    try:
        # 1. Récupérer les bibliothèques Plex et leurs chemins
        plex_server = get_user_specific_plex_server(silent=True) # Utilise l'admin si pas d'utilisateur
        if not plex_server:
            return jsonify({'error': "Connexion au serveur Plex impossible."}), 500

        plex_libraries = []
        ignored_libs = current_app.config.get('PLEX_LIBRARIES_TO_IGNORE', [])
        for lib in plex_server.library.sections():
            if lib.type in ['movie', 'show'] and lib.title not in ignored_libs:
                plex_libraries.append({
                    'name': lib.title,
                    'paths': lib.locations
                })

        # 2. Récupérer les dossiers racines de Sonarr et Radarr
        sonarr_folders = get_sonarr_root_folders() or []
        radarr_folders = get_radarr_root_folders() or []

        # 3. Récupérer la configuration de mapping actuelle
        current_mapping = load_plex_mappings()

        return jsonify({
            'plex_libraries': plex_libraries,
            'sonarr_root_folders': [f['path'] for f in sonarr_folders],
            'radarr_root_folders': [f['path'] for f in radarr_folders],
            'current_mapping': current_mapping
        })

    except Exception as e:
        current_app.logger.error(f"Erreur lors de la récupération des données de mapping : {e}", exc_info=True)
        return jsonify({'error': 'Une erreur est survenue sur le serveur.'}), 500
