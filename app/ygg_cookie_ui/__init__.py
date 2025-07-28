from flask import Blueprint

ygg_cookie_ui_bp = Blueprint(
    'ygg_cookie_ui',
    __name__,
    template_folder='templates'
)

from . import routes
