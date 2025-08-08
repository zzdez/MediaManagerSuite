from flask import Blueprint, request, jsonify, current_app
from app.utils.trailer_finder import find_youtube_trailer

trailer_bp = Blueprint('trailer', __name__, url_prefix='/api/trailer')

@trailer_bp.route('/find', methods=['POST'])
def find_trailer_endpoint():
    data = request.json
    title = data.get('title')
    year = data.get('year')
    media_type = data.get('media_type')

    if not all([title, year, media_type]):
        return jsonify({'error': 'Titre, année et type de média sont requis.'}), 400

    trailer_url = find_youtube_trailer(
        title, year, current_app.config['YOUTUBE_API_KEY'], media_type
    )

    if trailer_url:
        return jsonify({'success': True, 'url': trailer_url})
    else:
        return jsonify({'success': False, 'message': 'Aucune bande-annonce trouvée.'})
