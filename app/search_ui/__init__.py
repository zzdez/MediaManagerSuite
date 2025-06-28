from flask import Blueprint

search_ui_bp = Blueprint(
    'search_ui',
    __name__,
    template_folder='templates',
    static_folder='static'
)

from . import routes
