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
        # --- DÉBUT DU BLOC DE DÉBOGAGE ---
        received_key = request.headers.get('X-Internal-API-Key')
        expected_key = current_app.config.get('INTERNAL_API_KEY')

        print("--- DÉBOGAGE AUTHENTIFICATION INTERNE ---")
        print(f"Clé reçue   : '{received_key}'")
        print(f"Clé attendue : '{expected_key}'")

        if received_key and expected_key:
            print(f"Les clés correspondent ? -> {received_key == expected_key}")
        else:
            print("Une des clés est manquante.")
        print("---------------------------------------")
        # --- FIN DU BLOC DE DÉBOGAGE ---

        if not received_key or received_key != expected_key:
            return jsonify({'message': 'Accès non autorisé.'}), 403

        return f(*args, **kwargs)
    return decorated_function
