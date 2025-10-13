# app/seedbox_ui/__init__.py
from flask import Blueprint

seedbox_ui_bp = Blueprint('seedbox_ui', __name__,
                          template_folder='templates',
                          url_prefix='/seedbox') # Ex: /seedbox/staging, /seedbox/action

from . import routes 