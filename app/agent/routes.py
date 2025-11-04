from flask import request, jsonify, current_app
from . import agent_bp
from app.utils import trailer_manager
from app.utils.media_info_manager import media_info_manager

@agent_bp.route('/get_trailer_info', methods=['GET'])
def get_trailer_info_route():
    """
    Point de terminaison unifié pour obtenir les informations sur une bande-annonce.
    Utilise le TrailerManager pour gérer la logique de cache, de verrouillage et de recherche.
    """
    media_type = request.args.get('media_type')
    external_id = request.args.get('external_id')
    title = request.args.get('title')
    year = request.args.get('year')
    page_token = request.args.get('page_token')

    if not all([media_type, external_id, title]):
        return jsonify({'status': 'error', 'message': 'Les paramètres media_type, external_id et title sont requis.'}), 400

    try:
        result = trailer_manager.get_trailer_info(media_type, external_id, title=title, year=year, page_token=page_token)
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue dans get_trailer_info_route pour {media_type}_{external_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Une erreur interne est survenue.'}), 500

@agent_bp.route('/lock_trailer', methods=['POST'])
def lock_trailer_route():
    """
    Verrouille une bande-annonce spécifique pour un média via le TrailerManager.
    """
    data = request.json
    media_type = data.get('media_type')
    external_id = data.get('external_id')
    video_data = data.get('video_data')

    if not all([media_type, external_id, video_data]):
        return jsonify({'status': 'error', 'message': 'Les paramètres media_type, external_id et video_data sont requis.'}), 400

    try:
        trailer_manager.lock_trailer(media_type, external_id, video_data)
        return jsonify({'status': 'success', 'message': 'Bande-annonce verrouillée avec succès.'})
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue dans lock_trailer_route pour {media_type}_{external_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Une erreur interne est survenue.'}), 500

@agent_bp.route('/unlock_trailer', methods=['POST'])
def unlock_trailer_route():
    """
    Déverrouille la bande-annonce pour un média via le TrailerManager.
    """
    data = request.json
    media_type = data.get('media_type')
    external_id = data.get('external_id')

    if not all([media_type, external_id]):
        return jsonify({'status': 'error', 'message': 'Les paramètres media_type et external_id sont requis.'}), 400

    try:
        success = trailer_manager.unlock_trailer(media_type, external_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Bande-annonce déverrouillée avec succès.'})
        else:
            return jsonify({'status': 'error', 'message': 'Impossible de déverrouiller la bande-annonce. Entrée non trouvée.'}), 404
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue dans unlock_trailer_route pour {media_type}_{external_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Une erreur interne est survenue.'}), 500

@agent_bp.route('/get_locked_trailer_id', methods=['GET'])
def get_locked_trailer_id_route():
    """
    Retourne l'ID de la vidéo d'une bande-annonce verrouillée.
    """
    media_type = request.args.get('media_type')
    external_id = request.args.get('external_id')

    if not all([media_type, external_id]):
        return jsonify({'status': 'error', 'message': 'Les paramètres media_type et external_id sont requis.'}), 400

    try:
        video_id = trailer_manager.get_locked_trailer_video_id(media_type, external_id)
        if video_id:
            return jsonify({'status': 'success', 'video_id': video_id})
        else:
            return jsonify({'status': 'not_found', 'message': 'Aucune bande-annonce verrouillée trouvée.'}), 404
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue dans get_locked_trailer_id_route pour {media_type}_{external_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Une erreur interne est survenue.'}), 500

@agent_bp.route('/media/details/<media_type>/<int:external_id>', methods=['GET'])
def get_media_details_route(media_type, external_id):
    """
    Point de terminaison pour obtenir le "tableau de bord" d'informations
    pour un média donné.
    """
    if not all([media_type, external_id]):
        return jsonify({'status': 'error', 'message': 'Les paramètres media_type et external_id sont requis.'}), 400

    try:
        details = media_info_manager.get_media_details(media_type, external_id)
        return jsonify({'status': 'success', 'details': details})
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue dans get_media_details_route pour {media_type}_{external_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Une erreur interne est survenue.'}), 500

@agent_bp.route('/clear_trailer_cache', methods=['POST'])
def clear_trailer_cache_route():
    """
    Supprime l'entrée d'un média de la base de données des bandes-annonces.
    """
    data = request.json
    media_type = data.get('media_type')
    external_id = data.get('external_id')

    if not all([media_type, external_id]):
        return jsonify({'status': 'error', 'message': 'Les paramètres media_type et external_id sont requis.'}), 400

    try:
        success = trailer_manager.clear_trailer_cache(media_type, external_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Cache de la bande-annonce effacé avec succès.'})
        else:
            return jsonify({'status': 'not_found', 'message': 'Entrée non trouvée dans le cache.'}), 404
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue dans clear_trailer_cache_route pour {media_type}_{external_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Une erreur interne est survenue.'}), 500