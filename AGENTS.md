# AGENTS.md - Base de Connaissances pour les Agents IA

Ce fichier documente les leçons apprises, les décisions architecturales et les points techniques importants découverts lors du développement de l'application. Le but est d'assurer la continuité, d'éviter les régressions et d'accélérer les futurs développements.

## Leçons Apprises et Points Techniques Clés

### 1. Déplacement de Média via l'API Radarr

**Problème :** Lors d'une tentative de déplacement d'un film, l'API de Radarr semblait ignorer le nouveau dossier de destination et tentait de déplacer le fichier vers son propre emplacement, provoquant une erreur.

**Cause Racine :** L'objet "film" envoyé à l'API de Radarr (`PUT /api/v3/movie/{id}`) contient plusieurs champs liés au chemin. Une simple mise à jour du champ `rootFolderPath` est insuffisante si d'autres champs de chemin entrent en conflit. Il a été découvert que le champ `folderName` renvoyé par Radarr contenait le chemin complet du dossier du film (ex: `D:\Movies\Titre (2023)`), et non juste le nom du dossier.

**Solution et Règle d'Or :**
Pour construire un nouveau chemin de destination valide pour Radarr, il faut :
1.  Prendre la valeur de `folderName` (ou `path` comme fallback) de l'objet film original.
2.  Utiliser `os.path.basename()` pour en extraire **uniquement** le nom du dossier final (ex: `Titre (2023)`).
3.  Utiliser `os.path.join()` pour combiner le nouveau dossier racine de destination avec ce nom de dossier.
4.  Mettre à jour de manière cohérente **tous** les champs de chemin pertinents dans l'objet film avant de l'envoyer à l'API :
    *   `rootFolderPath` (le nouveau dossier racine)
    *   `path` (le chemin complet du dossier dans la nouvelle destination)
    *   `movieFile.path` (le chemin complet du fichier vidéo lui-même dans la nouvelle destination)

### 2. Suivi de la Progression des Tâches en Arrière-Plan

**Problème :** L'interface utilisateur affiche une notification de succès immédiatement après le lancement d'une tâche de longue durée (comme un déplacement de masse), alors que l'opération est toujours en cours en arrière-plan.

**Architecture Validée :**
*   Le backend doit gérer les tâches longues dans un thread séparé (ex: via un `BulkMoveManager`).
*   Le backend doit exposer une API de statut (ex: `GET /api/task_status/<task_id>`) qui retourne l'état actuel de la tâche (ex: 'running', 'completed', 'failed') et un message de progression.
*   Le frontend **ne doit pas** considérer la tâche comme terminée après l'appel initial. Il doit lancer une boucle de *polling* (ex: avec `setInterval`) qui interroge régulièrement l'API de statut.
*   L'interface doit être mise à jour dynamiquement en fonction de la réponse de l'API de statut (ex: afficher un indicateur de progression). La notification finale (succès/échec) et le rafraîchissement des données ne doivent être déclenchés que lorsque l'API de statut renvoie un état final ('completed' ou 'failed').
