# app/search_ui/__init__.py

from flask import Blueprint, render_template, request, flash, jsonify, Response, stream_with_context, current_app
from app.auth import login_required
from config import Config

# 1. Définition du Blueprint (seul code global avec les imports "sûrs")
search_ui_bp = Blueprint(
    'search_ui',
    __name__,
    template_folder='templates',
    static_folder='static'
)

# 2. Toutes les routes. Les imports "à risque" sont maintenant DANS les fonctions.

@search_ui_bp.route('/', methods=['GET'])
@login_required
def search_page():
    # Imports locaux
    from app.utils.prowlarr_client import search_prowlarr

    query = request.args.get('query', '').strip()
    year = request.args.get('year')
    lang = request.args.get('lang')
    results = None

    if query:
        raw_results = search_prowlarr(query, year=year, lang=lang)
        if raw_results is not None:
            results = raw_results
        else:
            flash("Erreur de communication avec Prowlarr.", "danger")
            results = []

    return render_template('search_ui/search.html', title="Recherche", results=results, query=query)


@search_ui_bp.route('/api/search/lookup', methods=['POST'])
def search_lookup():
    # Imports locaux
    from app.utils.arr_client import search_sonarr_by_title, search_radarr_by_title

    data = request.get_json()
    term = data.get('term')
    media_type = data.get('media_type')

    if not term or not media_type:
        return jsonify({'error': 'Missing term or media_type'}), 400

    try:
        if media_type == 'tv':
            results = search_sonarr_by_title(term)
            simplified_results = [{'title': s.get('title'), 'year': s.get('year'), 'tvdbId': s.get('tvdbId')} for s in results]
            return jsonify(simplified_results)
        elif media_type == 'movie':
            results = search_radarr_by_title(term)
            simplified_results = [{'title': m.get('title'), 'year': m.get('year'), 'tmdbId': m.get('tmdbId')} for m in results]
            return jsonify(simplified_results)
        else:
            return jsonify({'error': 'Invalid media_type specified'}), 400
    except Exception as e:
        current_app.logger.error(f"Erreur dans search_lookup: {e}", exc_info=True)
        return jsonify({'error': f'An error occurred while communicating with the service: {str(e)}'}), 500


@search_ui_bp.route('/api/enrich/details', methods=['POST'])
def enrich_details():
    # Imports locaux
    from app.utils.tvdb_client import TheTVDBClient
    from app.utils.tmdb_client import TMDbClient

    # Initialisation des clients ici
    tvdb_client = TheTVDBClient(api_key=Config.TVDB_API_KEY, pin=Config.TVDB_PIN)
    tmdb_client = TMDbClient(api_key=Config.TMDB_API_KEY)

    data = request.get_json()
    media_id = data.get('media_id')
    media_type = data.get('media_type')

    if not media_id or not media_type:
        return jsonify({'error': 'Missing media_id or media_type'}), 400

    try:
        if media_type == 'tv':
            details = tvdb_client.get_series_details_by_id(media_id, lang='fra')
            if details:
                formatted_details = {
                    'id': details.get('tvdb_id'),
                    'title': details.get('name'),
                    'year': details.get('year'),
                    'overview': details.get('overview'),
                    'poster': details.get('image_url'),
                    'status': details.get('status')
                }
                return jsonify(formatted_details)
        elif media_type == 'movie':
            details = tmdb_client.get_movie_details(media_id, lang='fr-FR')
            if details:
                formatted_details = {
                    'id': details.get('id'),
                    'title': details.get('title'),
                    'year': details.get('release_date', 'N/A')[:4],
                    'overview': details.get('overview'),
                    'poster': f"https://image.tmdb.org/t/p/w500{details.get('poster_path')}" if details.get('poster_path') else '',
                    'status': details.get('status')
                }
                return jsonify(formatted_details)

        return jsonify({'error': 'Media not found'}), 404

    except Exception as e:
        current_app.logger.error(f"Erreur dans enrich_details: {e}", exc_info=True)
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

# NOTE: Les autres routes de l'ancien fichier 'routes.py' comme '/download-and-map', etc.
# doivent aussi être migrées ici en utilisant le même pattern d'imports locaux si elles
# sont toujours utilisées. Pour l'instant, je me concentre sur le strict nécessaire pour
# faire fonctionner la recherche et la modale.
