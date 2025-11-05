from flask import jsonify, request, current_app
from . import api_bp
from app.utils.cookie_manager import get_ygg_cookie_status
from app.auth import login_required
from app.utils.plex_client import get_plex_admin_server
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
        plex_server = get_plex_admin_server()
        if not plex_server:
            return jsonify({"error": "Plex server not available or configured"}), 503

        plex_libs_aggregated = {}
        for section in plex_server.library.sections():
            if section.type in ['movie', 'show']:
                if section.title not in plex_libs_aggregated:
                    plex_libs_aggregated[section.title] = {
                        "name": section.title,
                        "type": section.type,
                        "locations": []
                    }
                plex_libs_aggregated[section.title]["locations"].extend(section.locations)

        plex_libraries = list(plex_libs_aggregated.values())

        sonarr_folders = get_sonarr_root_folders()
        radarr_folders = get_radarr_root_folders()
        current_mappings = get_plex_mappings()

        return jsonify({
            "plex_libraries": plex_libraries,
            "sonarr_root_folders": sonarr_folders,
            "radarr_root_folders": radarr_folders,
            "current_mappings": current_mappings
        })
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la récupération des données de mapping : {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while fetching mapping data"}), 500

@api_bp.route('/mapping-data', methods=['POST'])
@login_required
def save_mapping_data():
    """
    Sauvegarde la configuration du mapping fournie par l'utilisateur.
    """
    try:
        data = request.json
        save_plex_mappings(data)
        return jsonify({"success": True, "message": "Mappings saved successfully."})
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la sauvegarde des données de mapping : {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while saving mapping data"}), 500

@api_bp.route('/history/search')
@login_required
def search_archive_history():
    """
    Recherche dans la base de données d'archives les médias correspondant à un titre.
    """
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify({'error': 'A title parameter is required.'}), 400

    try:
        from app.utils.archive_manager import find_archived_media_by_title
        results = find_archived_media_by_title(title)
        return jsonify(results)
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la recherche dans l'historique d'archives : {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while searching the archive."}), 500
