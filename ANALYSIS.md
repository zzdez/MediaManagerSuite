# Analyse pour le Service de Recherche de Bandes-Annonces

Ce document détaille l'analyse du fichier `app/plex_editor/routes.py` en vue de la création du nouveau service `trailer_finder`.

## 1. Accès au Client Plex

Dans la fonction `get_media_items()`, l'objet qui représente la connexion au serveur Plex de l'utilisateur est obtenu via un appel à la fonction `get_user_specific_plex_server_from_id(user_id)`.

Le nom de la variable qui contient cet objet est `target_plex_server`.

**Extrait de code pertinent :**
```python
# Dans la fonction get_media_items()
try:
    target_plex_server = get_user_specific_plex_server_from_id(user_id)
    if not target_plex_server:
        return jsonify({'error': f"Impossible de se connecter en tant que {user_id}."}), 500

    # ... le reste de la fonction utilise `target_plex_server` pour les appels Plex ...
```

## 2. Construction d'URL Authentifiée

La bibliothèque `python-plexapi` permet bien de construire des URLs authentifiées. L'analyse du code confirme que la méthode `.url(path, includeToken=True)` est disponible sur l'objet `target_plex_server` et est d'ailleurs déjà utilisée pour générer les URLs des affiches (posters).

**Extrait de code confirmant l'utilisation :**
```python
# Dans la boucle sur les items dans get_media_items()
thumb_path = getattr(item_from_lib, 'thumb', None)
if thumb_path:
    item_from_lib.poster_url = target_plex_server.url(thumb_path, includeToken=True)
else:
    item_from_lib.poster_url = None
```
Cette utilisation confirme que `target_plex_server.url('/some/path', includeToken=True)` est la méthode correcte à employer pour construire une URL incluant le token d'authentification.

## 3. Structure des Données des Items

Dans la fonction `get_media_items()`, les informations sur les médias ne sont pas stockées dans une liste de dictionnaires. À la place, le code itère sur des objets médias (`Movie`, `Show`, etc.) retournés par la bibliothèque `plexapi`. De nouveaux attributs sont ajoutés dynamiquement à ces objets avant de les ajouter à la liste `all_media_from_plex`.

Pour insérer l'URL de la bande-annonce (`trailer_url`), il faudrait donc ajouter un nouvel attribut directement à l'objet `item_from_lib` à l'intérieur de la boucle `for`.

**Exemple de la structure et du point d'insertion :**
```python
# Dans la boucle `for item_from_lib in items_from_lib:`
for item_from_lib in items_from_lib:
    # ... Ajouts d'attributs existants ...
    item_from_lib.library_name = library.title
    item_from_lib.poster_url = target_plex_server.url(getattr(item_from_lib, 'thumb', ''), includeToken=True)

    # ...
    # EMPLACEMENT IDÉAL POUR AJOUTER LA NOUVELLE INFORMATION
    # item_from_lib.trailer_url = "URL_DE_LA_BANDE_ANNONCE_ICI"
    # ...

    all_media_from_plex.append(item_from_lib)
```
Le nouvel attribut `trailer_url` serait ainsi accessible sur chaque objet `item` dans le template `_media_table.html` qui est rendu à la fin.
