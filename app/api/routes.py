from flask import jsonify, request, current_app
from . import api_bp
from app.utils.cookie_manager import get_ygg_cookie_status
from app.auth import login_required
from app.utils.plex_client import get_user_specific_plex_server
from app.utils.arr_client import get_sonarr_root_folders, get_radarr_root_folders
from app.utils.plex_mapping_manager import get_plex_mappings, save_plex_mappings

@api_bp.route('/cookie/status')
@login_required
def cookie_status():
    """
    Returns the current status of the YGG cookie.
    """
    status = get_ygg_cookie_status()
    return jsonify(status)

@api_bp.route('/mapping-data', methods=['GET'])
@login_required
def get_mapping_data():
    """
    Fournit les données nécessaires pour l'interface de configuration du mapping,
    y compris les mappings actuellement sauvegardés.
    """
    try:
        # Récupérer les bibliothèques Plex
        plex_server = get_user_specific_plex_server(silent=True)
        if not plex_server:
            return jsonify({"error": "Plex server not available"}), 503

        plex_libraries = []
        for section in plex_server.library.sections():
            if section.type in ['movie', 'show']:
                plex_libraries.append({
                    "name": section.title,
                    "type": section.type,
                    "locations": list(section.locations)
                })

        # Récupérer les root folders de Sonarr et Radarr
        sonarr_folders = get_sonarr_root_folders()
        radarr_folders = get_radarr_root_folders()

        # Charger les mappings existants
        current_mappings = get_plex_mappings()

        return jsonify({
            "plex_libraries": plex_libraries,
            "sonarr_root_folders": sonarr_folders,
            "radarr_root_folders": radarr_folders,
            "current_mappings": current_mappings
        })
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la récupération des données de mapping : {e}")
        return jsonify({"error": "An internal error occurred while fetching mapping data"}), 500

@api_bp.route('/mapping-data', methods=['POST'])
@login_required
def save_mapping_data():
    """
    Sauvegarde la configuration du mapping fournie par l'utilisateur.
    """
    try:
        data = request.json
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid data format: expected a JSON object"}), 400

        save_plex_mappings(data)

        return jsonify({"success": True, "message": "Mappings saved successfully."})
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la sauvegarde des données de mapping : {e}")
        return jsonify({"error": "An internal error occurred while saving mapping data"}), 500
