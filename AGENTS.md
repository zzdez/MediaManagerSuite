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

### 3. Confirmation Fiable d'un Déplacement de Fichier Sonarr/Radarr

**Problème :** Après avoir initié un déplacement de média via l'API (`PUT /api/v3/[series|movie]/{id}?moveFiles=true`), il est impossible d'obtenir un signal fiable de l'API pour savoir quand le transfert physique du fichier est terminé.

**Analyses des Méthodes Non Fiables :**
Au cours d'un long processus de débogage, les stratégies suivantes se sont avérées **inefficaces et ne doivent pas être utilisées** :
1.  **Polling de la file d'attente (`/api/v3/queue`) :** L'élément disparaît de la file d'attente dès que le transfert *commence*, pas quand il se termine.
2.  **Polling de l'historique global (`/api/v3/history`) :** Sur un serveur actif, le volume d'événements est tel que l'événement de déplacement pertinent est "noyé" et poussé hors de la première page de résultats avant d'être détecté.
3.  **Vérification du `path` du média :** L'API met à jour le champ `path` dans sa base de données dès que le déplacement est *initié*, pas quand il est physiquement terminé.
4.  **Polling de l'historique spécifique au média (`/history/series` ou `/history/movie`) :** Il a été confirmé que l'API **ne génère aucun événement** de type `seriesMoved` ou `movieFileImported` pour les déplacements initiés via l'API.

**Solution et Règle d'Or :**
La seule source de vérité fiable pour confirmer la fin d'un déplacement de fichier est le **système de fichiers lui-même**. La stratégie correcte et définitive est la suivante :
1.  **Avant** d'initier le déplacement, récupérer et stocker le chemin source complet du média (ex: `D:\Series\Nom de la Série`).
2.  Lancer la commande de déplacement via l'API.
3.  Implémenter une boucle de polling qui vérifie à intervalles réguliers si le chemin source existe toujours en utilisant `os.path.exists(source_path)`.
4.  La tâche est considérée comme terminée uniquement lorsque `os.path.exists()` renvoie `False`, indiquant que le dossier/fichier source a été supprimé/déplacé.

### Session du 2025-10-27 : Amélioration de l'onglet "Recherche par Média"

**Résumé de la session précédente :**

Nous avons finalisé avec succès une série d'améliorations majeures pour l'interface de l'Éditeur Plex, en nous concentrant sur le feedback utilisateur après les déplacements de médias et l'enrichissement de l'information présentée.

*   **Ce qui a fonctionné :**
    1.  **Mise à jour en temps réel :** Le chemin d'accès d'un média est maintenant mis à jour instantanément dans le tableau après un déplacement réussi, éliminant le besoin de recharger la page.
    2.  **Scan Plex automatique :** Un scan des bibliothèques Plex concernées est automatiquement lancé à la fin d'un déplacement en masse, assurant que Plex reflète rapidement les changements.
    3.  **Statuts de Production :** Les fiches des séries affichent désormais leur statut de production depuis Sonarr ("Terminée", "En Production", etc.) à côté de leur statut de visionnage Plex.
    4.  **Interface améliorée :** Les statuts de visionnage et de production ont été séparés en deux colonnes distinctes et sont maintenant triables indépendamment, avec une logique de tri personnalisée pour le statut de production.
    5.  **Correction de régression et de layout :** Nous avons identifié et corrigé une régression critique dans la logique de filtrage par dossier racine pour garantir des correspondances strictes. Le layout a également été restauré à son état compact d'origine.

*   **Processus itératif :** Le développement a été très collaboratif. La séparation des colonnes a initialement affecté le layout, et une réorganisation du code a malencontreusement réintroduit un ancien bug de filtrage. Ces deux points ont été rapidement identifiés et corrigés grâce à vos retours précis.

**Objectif pour la nouvelle session :**

Améliorer l'onglet **"Recherche par Média"** de la page de recherche.

*   **1. Enrichir les fiches de résultats :** L'objectif est de fournir plus de contexte sur chaque film ou série présenté.
    *   Ajouter un indicateur visuel pour savoir si le média est déjà présent dans Sonarr ou Radarr.
    *   Afficher son statut de surveillance (*Monitored* / *Unmonitored*).
    *   Réutiliser les badges de statut de visionnage (depuis Plex) et de statut de production (depuis Sonarr) que nous avons développés pour l'Éditeur Plex.

*   **2. Ajouter un média sans recherche de torrent :**
    *   Implémenter une nouvelle fonctionnalité pour ajouter un film ou une série à la liste de surveillance de Sonarr/Radarr directement depuis les résultats de recherche.
    *   Cette action ne doit **pas** déclencher de recherche de torrents. C'est une fonctionnalité cruciale pour ajouter des médias qui ne sont pas encore sortis.

*   **3. Empêcher les téléchargements en double :**
    *   Modifier le comportement d'ajout via MMS (quand un torrent est choisi depuis la "Recherche Libre").
    *   Il faut configurer l'ajout à Sonarr/Radarr de manière à ce que leur fonction de recherche automatique de releases soit désactivée pour ce nouvel ajout. MMS doit être le seul à gérer le téléchargement initial pour éviter les doublons.
