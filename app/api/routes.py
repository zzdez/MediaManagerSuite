# app/api/routes.py
from flask import jsonify
from . import api_bp
from app.utils.plex_mapping_manager import load_plex_mappings
from app.auth import login_required

@api_bp.route('/mappings', methods=['GET'])
@login_required
def get_mappings():
    """
    Endpoint API pour récupérer la configuration du mapping des bibliothèques Plex.
    """
    mappings = load_plex_mappings()
    return jsonify(mappings)
