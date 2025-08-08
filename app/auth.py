# app/auth.py

from functools import wraps
from flask import session, request, redirect, url_for, flash, jsonify, current_app

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            session['next_url'] = request.url
            flash("Veuillez vous connecter pour accéder à cette page.", 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def internal_api_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-Internal-API-Key')
        if not api_key or api_key != current_app.config['INTERNAL_API_KEY']:
            return jsonify({'message': 'Accès non autorisé.'}), 403
        return f(*args, **kwargs)
    return decorated_function
