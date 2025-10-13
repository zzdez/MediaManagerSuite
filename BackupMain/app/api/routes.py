from flask import jsonify
from . import api_bp
from app.utils.cookie_manager import get_ygg_cookie_status
from app.auth import login_required

@api_bp.route('/cookie/status')
@login_required
def cookie_status():
    """
    Returns the current status of the YGG cookie.
    """
    status = get_ygg_cookie_status()
    return jsonify(status)
