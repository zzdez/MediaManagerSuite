# app/plex_editor/__init__.py
from flask import Blueprint

# Créer un Blueprint pour le module plex_editor
# 'plex_editor' : nom du Blueprint
# __name__ : nom du module/package actuel
# template_folder='templates' : indique où chercher les templates pour ce Blueprint
# url_prefix='/plex' : toutes les routes de ce Blueprint commenceront par /plex (ex: /plex/index, /plex/library/...)
plex_editor_bp = Blueprint('plex_editor', __name__,
                           template_folder='templates',
                           url_prefix='/plex')

# Importer les routes APRÈS la création du Blueprint pour éviter les imports circulaires
from . import routes
# Si utils.py est spécifique à ce blueprint et n'est pas partagé, il n'a pas besoin d'être importé ici globalement