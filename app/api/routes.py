from flask import jsonify
from . import api_bp
from app.utils.cookie_manager import get_ygg_cookie_status
from app.auth import login_required
import os
import json

@api_bp.route('/cookie/status')
@login_required
def cookie_status():
    """
    Returns the current status of the YGG cookie.
    """
    status = get_ygg_cookie_status()
    return jsonify(status)

@api_bp.route('/search/filter-options')
@login_required
def search_filter_options():
    """
    Returns the dynamic filter options from environment variables.
    """
    # Languages
    languages_str = os.getenv('SEARCH_FILTER_LANGUAGES', '{}')
    try:
        languages = json.loads(languages_str)
    except json.JSONDecodeError:
        languages = {}

    # Release Groups
    release_groups_str = os.getenv('SEARCH_FILTER_RELEASE_GROUPS', '')
    release_groups = sorted([group.strip() for group in release_groups_str.split(',') if group.strip()])

    return jsonify({
        'languages': languages,
        'release_groups': release_groups
    })
