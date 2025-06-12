# app/config_ui/__init__.py
from flask import Blueprint

config_ui_bp = Blueprint(
    'config_ui',
    __name__,
    template_folder='../templates/config_ui',  # Point to the new templates subfolder
    static_folder='../static' # Assuming you might have static files for this blueprint later
)

# Import routes after Blueprint creation to avoid circular imports
from . import routes