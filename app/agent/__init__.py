from flask import Blueprint
agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')
from . import routes
