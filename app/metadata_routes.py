from flask import Blueprint, request, jsonify
from app.utils.tvdb_client import CustomTVDBClient  # Corrected import

metadata_bp = Blueprint('metadata', __name__, url_prefix='/api/metadata')

@metadata_bp.route('/search_series', methods=['GET'])
def search_series_endpoint():
    query = request.args.get('query')
    if not query:
        return jsonify({'error': 'Query is required.'}), 400

    client = CustomTVDBClient()
    # Suppose que ton client a une fonction 'search_series'
    results = client.search_series(query, lang='fra') # Use 'fra' for TVDB

    return jsonify(results)
