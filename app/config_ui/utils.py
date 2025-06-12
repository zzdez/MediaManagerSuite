import os
import re
from dotenv import dotenv_values

# Chemin vers le template.env (supposant que config.py est à la racine du projet)
# et que utils.py est dans app/config_ui/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) # Racine du projet
TEMPLATE_ENV_PATH = os.path.join(BASE_DIR, '.env.template')
DOTENV_PATH = os.path.join(BASE_DIR, '.env')


def parse_template_env():
    '''
    Analyse le fichier .env.template pour extraire les variables, leurs valeurs par défaut,
    leurs types inférés et leurs descriptions (commentaires).

    Tente également de récupérer les valeurs actuelles du fichier .env principal.

    Retourne:
        list: Une liste de dictionnaires, où chaque dictionnaire contient:
              'name' (str): Le nom de la variable.
              'default_value' (str): La valeur par défaut du template.
              'current_value' (str): La valeur actuelle du .env principal (ou default_value si non trouvée).
              'type' (str): Le type inféré ('string', 'bool', 'int', 'list_str', 'password').
              'description' (str): Le commentaire associé à la variable.
              'options' (list, optionnel): Options pour les types 'select' (par ex. pour booléens).
    '''
    if not os.path.exists(TEMPLATE_ENV_PATH):
        # Gérer le cas où template.env n'existe pas
        # Vous pourriez logger une erreur ici ou retourner une liste vide.
        print(f"ERREUR : Le fichier {TEMPLATE_ENV_PATH} est introuvable.")
        return []

    params = []
    current_env_values = dotenv_values(DOTENV_PATH)

    with open(TEMPLATE_ENV_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('# ---'): # Ignorer les lignes vides et les séparateurs de section
                # Conserver les séparateurs de section pour l'affichage
                if line.startswith('# ---'):
                    params.append({'is_separator': True, 'text': line[2:-2].strip()})
                continue

            comment_match = re.search(r'#\s*(.*)', line)
            description = ''
            var_line = line
            if comment_match:
                description = comment_match.group(1).strip()
                var_line = line[:comment_match.start()].strip() # Ce qui est avant le commentaire

            if var_line.startswith('#'): # Si la ligne entière est un commentaire (non traité comme description de var)
                if description and not any(p.get('name') for p in params if 'name' in p): # Si c'est un commentaire général avant toute variable
                     params.append({'is_comment_general': True, 'text': description})
                elif description: # Si c'est un commentaire après des variables, peut-être pour un groupe
                     params.append({'is_comment_block': True, 'text': description})
                continue


            if '=' in var_line:
                name, default_value = var_line.split('=', 1)
                name = name.strip()
                default_value = default_value.strip()
                
                # Essayer de récupérer la valeur actuelle du .env principal
                current_value = current_env_values.get(name, default_value)

                # Inférence de type (simplifiée)
                param_type = 'string' # Par défaut
                options = None

                # Inférence basée sur le nom (convention pour les mots de passe/tokens)
                if 'PASSWORD' in name.upper() or 'TOKEN' in name.upper() or 'API_KEY' in name.upper() or 'SECRET_KEY' in name.upper():
                    param_type = 'password'
                elif default_value.lower() in ['true', 'false', 'yes', 'no', '1', '0']:
                    param_type = 'bool'
                    options = [('True', 'True'), ('False', 'False')] # Ou Yes/No selon la préférence
                     # Mettre à jour current_value pour correspondre aux options si booléen
                    if str(current_value).lower() in ['true', '1', 't', 'yes']:
                        current_value = 'True'
                    elif str(current_value).lower() in ['false', '0', 'f', 'no']:
                        current_value = 'False'
                    else: # Si la valeur actuelle n'est pas clairement un booléen reconnu, utiliser la valeur par défaut
                        current_value = 'True' if default_value.lower() in ['true', '1', 't', 'yes'] else 'False'

                elif default_value.isdigit():
                    param_type = 'int'
                elif ',' in default_value and not any(c.isspace() for c in default_value.split(',')[0]): # Simple heuristique pour list_str
                    param_type = 'list_str'
                
                # Priorité aux commentaires de type explicite
                type_comment_match = re.search(r'#\s*TYPE:\s*(\w+)', description, re.IGNORECASE)
                if type_comment_match:
                    explicit_type = type_comment_match.group(1).lower()
                    if explicit_type in ['string', 'int', 'bool', 'list_str', 'password']:
                        param_type = explicit_type
                    if explicit_type == 'bool':
                        options = [('True', 'True'), ('False', 'False')]
                        if str(current_value).lower() in ['true', '1', 't', 'yes']:
                            current_value = 'True'
                        elif str(current_value).lower() in ['false', '0', 'f', 'no']:
                            current_value = 'False'
                        else:
                             current_value = 'True' if default_value.lower() in ['true', '1', 't', 'yes'] else 'False'


                # Nettoyer la description si elle contenait le type
                description = re.sub(r'#\s*TYPE:\s*\w+', '', description).strip()
                
                params.append({
                    'name': name,
                    'default_value': default_value,
                    'current_value': current_value,
                    'type': param_type,
                    'description': description,
                    'options': options,
                    'is_separator': False,
                    'is_comment_general': False,
                    'is_comment_block': False
                })
            elif description: # Ligne de commentaire seule qui n'est pas un séparateur
                 params.append({'is_comment_block': True, 'text': description})


    return params

if __name__ == '__main__':
    # Pour tester la fonction directement
    # Assurez-vous que .env.template et .env existent à la racine du projet pour ce test
    
    # Créer un .env.template de test
    sample_template_content = """
# --- Section Générale ---
APP_NAME=MaSuperApp # Nom de l'application
DEBUG_MODE=False # TYPE: bool # Activer le mode débug
PORT_NUMBER=8080 # TYPE: int # Port d'écoute
ADMIN_EMAIL=admin@example.com # Email de l'administrateur
SECRET_API_KEY=replace_this_key # Ceci est une clé secrète

# --- Section Base de données ---
DB_HOST=localhost
DB_USER=user_db
DB_PASSWORD=pass # Mot de passe sensible

# Liste de fonctionnalités activées
# TYPE: list_str
ENABLED_FEATURES=feature1,feature2,feature3
"""
    with open(TEMPLATE_ENV_PATH, 'w', encoding='utf-8') as f:
        f.write(sample_template_content)

    # Créer un .env de test
    sample_env_content = """
APP_NAME=MonAppModifiée
DEBUG_MODE=True
PORT_NUMBER=9000
# ADMIN_EMAIL est commenté ou manquant
SECRET_API_KEY=actual_secret_key_from_env
DB_HOST=127.0.0.1
DB_USER=prod_user
DB_PASSWORD=real_password
ENABLED_FEATURES=feature1,feature3,new_feature
"""
    with open(DOTENV_PATH, 'w', encoding='utf-8') as f:
        f.write(sample_env_content)

    parsed_params = parse_template_env()
    if parsed_params:
        print(f"Variables parsées depuis {TEMPLATE_ENV_PATH} (et valeurs de {DOTENV_PATH}):")
        for param in parsed_params:
            if param.get('is_separator'):
                print(f"\n--- {param.get('text')} ---")
            elif param.get('is_comment_general') or param.get('is_comment_block'):
                print(f"# {param.get('text')}")
            else:
                print(
                    f"  Nom: {param.get('name')}, "
                    f"Type: {param.get('type')}, "
                    f"Défaut: '{param.get('default_value')}', "
                    f"Actuel: '{param.get('current_value')}', "
                    f"Description: '{param.get('description')}'"
                    f"{', Options: ' + str(param.get('options')) if param.get('options') else ''}"
                )
    else:
        print("Aucun paramètre n'a été parsé ou le fichier template est introuvable.")

    # Nettoyage des fichiers de test
    # os.remove(TEMPLATE_ENV_PATH)
    # os.remove(DOTENV_PATH)
    print("\nATTENTION: Les fichiers .env.template et .env ont été modifiés/créés pour le test.")
    print("Veuillez les vérifier ou les restaurer si nécessaire.")
