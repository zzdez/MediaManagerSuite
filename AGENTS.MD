## Leçons Apprises & Bonnes Pratiques

### Suivi Fiable des Déplacements de Média (Sonarr/Radarr)

- **Principe Asynchrone :** Les commandes de déplacement de fichiers dans Sonarr et Radarr sont asynchrones. Une réponse `200 OK` de l'API signifie seulement que la tâche a été acceptée et mise en file d'attente, **pas** que le déplacement des fichiers est terminé.
- **Stratégies de Suivi :** Pour obtenir un suivi fiable de la progression, il est impératif d'interroger activement l'état de la tâche :
    - **Pour Radarr :** Utiliser la commande `MoveMovies`, récupérer le `commandId` retourné, et interroger l'endpoint `/api/v3/command/{id}` jusqu'à ce que le statut soit `completed`.
    - **Pour Sonarr :** La commande `MoveFiles` n'est pas fiable pour le suivi. La bonne méthode est de mettre à jour l'objet série avec le nouveau `rootFolderPath`, puis d'interroger cet objet série en boucle jusqu'à ce que la valeur du `rootFolderPath` corresponde bien au nouveau chemin.

### Interaction avec l'API Plex

- **Récupération de la Bibliothèque :** Pour obtenir la section de bibliothèque d'un média Plex (notamment pour les séries TV), ne pas utiliser l'attribut `plex_item.library` qui peut causer une `AttributeError`. La méthode robuste est d'utiliser `plex_server.library.sectionByID(plex_item.librarySectionID)`.

### Débogage des Tests Frontend (Playwright)

- **Erreurs 500 Inattendues :** Si un script Playwright échoue sur une page d'erreur générique (`500 Internal Server Error`), le problème vient quasi certainement du backend qui a planté lors du rendu de la page. Le premier réflexe doit être d'arrêter le débogage frontend et d'analyser les logs de l'application (ex: `app.log`) pour trouver la traceback Python complète de l'erreur.
