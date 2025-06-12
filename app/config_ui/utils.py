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
        # Gérer le cas où .env.template n'existe pas.
        # Un message d'erreur est printé, et une liste vide est retournée,
        # ce qui sera géré par la route pour afficher un message à l'utilisateur.
        print(f"ERREUR : Le fichier {TEMPLATE_ENV_PATH} est introuvable.")
        return []

    params = [] # Liste pour stocker les dictionnaires de paramètres parsés.
    # Charge les valeurs actuelles du .env principal sans affecter os.environ.
    # Cela permet de comparer les valeurs du .env.template avec celles réellement en cours d'utilisation.
    current_env_values = dotenv_values(DOTENV_PATH)

    with open(TEMPLATE_ENV_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Ignorer les lignes vides. Les séparateurs de section sont traités spécifiquement.
            if not line or line.startswith('# ---'):
                # Conserver les séparateurs de section pour l'affichage dans le formulaire.
                if line.startswith('# ---'):
                    params.append({'is_separator': True, 'text': line[2:-2].strip()}) # Extrait le texte du séparateur.
                continue

            comment_match = re.search(r'#\s*(.*)', line)
            description = ''
            var_line = line
            if comment_match:
                description = comment_match.group(1).strip() # Extrait le contenu du commentaire.
                var_line = line[:comment_match.start()].strip() # Isole la partie de la ligne avant le commentaire (potentielle variable).

            # Gérer les lignes qui sont entièrement des commentaires (non associées directement à une variable sur la même ligne).
            if var_line.startswith('#'):
                # Ces commentaires peuvent être des descriptions générales pour une section ou un groupe de variables.
                if description and not any(p.get('name') for p in params if 'name' in p): # Commentaire général en début de fichier/section.
                     params.append({'is_comment_general': True, 'text': description})
                elif description: # Commentaire de bloc pour un groupe de variables ou une explication.
                     params.append({'is_comment_block': True, 'text': description})
                continue


            if '=' in var_line:
                name, default_value = var_line.split('=', 1) # Sépare la variable de sa valeur par défaut.
                name = name.strip()
                default_value = default_value.strip()

                # Récupérer la valeur actuelle du .env principal.
                # Si la clé n'existe pas dans .env, la valeur par défaut du .env.template est utilisée comme valeur actuelle.
                current_value = current_env_values.get(name, default_value)

                # --- Inférence de Type ---
                # L'ordre d'inférence est :
                # 1. Mots-clés dans le nom de la variable (ex: PASSWORD, TOKEN -> type 'password').
                # 2. Forme de la valeur par défaut (ex: 'true'/'false' -> type 'bool'; '123' -> type 'int').
                # 3. Commentaire explicite `# TYPE: <type>` qui surcharge les inférences précédentes.
                # Le type par défaut est 'string'.
                param_type = 'string'
                options = None

                # 1. Inférence basée sur des mots-clés dans le nom de la variable.
                if 'PASSWORD' in name.upper() or 'TOKEN' in name.upper() or 'API_KEY' in name.upper() or 'SECRET_KEY' in name.upper():
                    param_type = 'password'
                # 2. Inférence basée sur la forme de la valeur par défaut.
                elif default_value.lower() in ['true', 'false', 'yes', 'no', '1', '0']: # Booléens
                    param_type = 'bool'
                    options = [('True', 'True'), ('False', 'False')] # Options pour le rendu du formulaire.
                    # Normaliser la valeur actuelle pour correspondre aux options si c'est un booléen.
                    if str(current_value).lower() in ['true', '1', 't', 'yes']:
                        current_value = 'True'
                    elif str(current_value).lower() in ['false', '0', 'f', 'no']:
                        current_value = 'False'
                    else: # Si la valeur actuelle n'est pas un booléen clair, forcer en utilisant la valeur par défaut normalisée.
                        current_value = 'True' if default_value.lower() in ['true', '1', 't', 'yes'] else 'False'
                elif default_value.isdigit(): # Entiers
                    param_type = 'int'
                # Heuristique simple pour list_str (ex: "item1,item2").
                # Vérifie la présence de virgules et s'assure que le premier segment ne contient pas d'espaces
                # (pour éviter de traiter des phrases comme des listes).
                elif ',' in default_value and (not default_value.split(',')[0] or not any(c.isspace() for c in default_value.split(',')[0])):
                    param_type = 'list_str'

                # 3. Priorité au commentaire de type explicite (ex: "# TYPE: bool").
                #    Ceci surcharge toute inférence précédente.
                type_comment_match = re.search(r'#\s*TYPE:\s*(\w+)', description, re.IGNORECASE)
                if type_comment_match:
                    explicit_type = type_comment_match.group(1).lower()
                    if explicit_type in ['string', 'int', 'bool', 'list_str', 'password']:
                        param_type = explicit_type # Appliquer le type explicite.
                    # Si le type explicite est booléen, s'assurer que les options et la valeur actuelle sont correctement (re)définies.
                    if explicit_type == 'bool':
                        options = [('True', 'True'), ('False', 'False')]
                        # Re-normaliser current_value basé sur le type explicite bool.
                        if str(current_value).lower() in ['true', '1', 't', 'yes']:
                            current_value = 'True'
                        elif str(current_value).lower() in ['false', '0', 'f', 'no']:
                            current_value = 'False'
                        else: # Forcer en utilisant la valeur par défaut normalisée.
                             current_value = 'True' if default_value.lower() in ['true', '1', 't', 'yes'] else 'False'

                # Nettoyer la description de l'annotation de type pour éviter de l'afficher dans l'UI.
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
