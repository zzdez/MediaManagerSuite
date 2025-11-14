from flask import Blueprint

dashboard_bp = Blueprint(
    'dashboard_bp',
    __name__,
    template_folder='templates',
    static_folder='static',
    static_url_path='/dashboard/static'
)

from app.dashboard import routes
