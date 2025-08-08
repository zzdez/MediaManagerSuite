from flask import Blueprint, request, jsonify, current_app, session
from app.utils.trailer_finder import get_trailer

trailer_bp = Blueprint('trailer', __name__, url_prefix='/api/trailer')

@trailer_bp.route('/find', methods=['POST'])
def find_trailer_endpoint():
    data = request.json
    title = data.get('title')
    year = data.get('year')
    media_type = data.get('media_type')
    rating_key = data.get('ratingKey')
    user_id = session.get('plex_user_id') # Assure-toi de récupérer le user_id depuis la session

    if not all([title, year, media_type]):
        return jsonify({'error': 'Titre, année et type de média sont requis.'}), 400

    trailer_url = get_trailer(
        title=title,
        year=year,
        media_type=media_type,
        youtube_api_key=current_app.config['YOUTUBE_API_KEY'],
        rating_key=rating_key, # <-- PASSER LE RATING_KEY
        user_id=user_id # <-- PASSER LE USER_ID
    )

    if trailer_url:
        return jsonify({'success': True, 'url': trailer_url})
    else:
        return jsonify({'success': False, 'message': 'Aucune bande-annonce trouvée.'})
