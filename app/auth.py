# app/auth.py

from functools import wraps
from flask import session, request, redirect, url_for, flash

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            session['next_url'] = request.url
            flash("Veuillez vous connecter pour accéder à cette page.", 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
