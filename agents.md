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
Session du 2025-10-27 : Amélioration de l'onglet "Recherche par Média"
Résumé de la session précédente :

Nous avons finalisé avec succès une série d'améliorations majeures pour l'interface de l'Éditeur Plex, en nous concentrant sur le feedback utilisateur après les déplacements de médias et l'enrichissement de l'information présentée.

Ce qui a fonctionné :

Mise à jour en temps réel : Le chemin d'accès d'un média est maintenant mis à jour instantanément dans le tableau après un déplacement réussi, éliminant le besoin de recharger la page.
Scan Plex automatique : Un scan des bibliothèques Plex concernées est automatiquement lancé à la fin d'un déplacement en masse, assurant que Plex reflète rapidement les changements.
Statuts de Production : Les fiches des séries affichent désormais leur statut de production depuis Sonarr ("Terminée", "En Production", etc.) à côté de leur statut de visionnage Plex.
Interface améliorée : Les statuts de visionnage et de production ont été séparés en deux colonnes distinctes et sont maintenant triables indépendamment, avec une logique de tri personnalisée pour le statut de production.
Correction de régression et de layout : Nous avons identifié et corrigé une régression critique dans la logique de filtrage par dossier racine pour garantir des correspondances strictes. Le layout a également été restauré à son état compact d'origine.
Processus itératif : Le développement a été très collaboratif. La séparation des colonnes a initialement affecté le layout, et une réorganisation du code a malencontreusement réintroduit un ancien bug de filtrage. Ces deux points ont été rapidement identifiés et corrigés grâce à vos retours précis.

Objectif pour la nouvelle session :

Améliorer l'onglet "Recherche par Média" de la page de recherche.

1. Enrichir les fiches de résultats : L'objectif est de fournir plus de contexte sur chaque film ou série présenté.

Ajouter un indicateur visuel pour savoir si le média est déjà présent dans Sonarr ou Radarr.
Afficher son statut de surveillance (Monitored / Unmonitored).
Réutiliser les badges de statut de visionnage (depuis Plex) et de statut de production (depuis Sonarr) que nous avons développés pour l'Éditeur Plex.
2. Ajouter un média sans recherche de torrent :

Implémenter une nouvelle fonctionnalité pour ajouter un film ou une série à la liste de surveillance de Sonarr/Radarr directement depuis les résultats de recherche.
Cette action ne doit pas déclencher de recherche de torrents. C'est une fonctionnalité cruciale pour ajouter des médias qui ne sont pas encore sortis.
3. Empêcher les téléchargements en double :

Modifier le comportement d'ajout via MMS (quand un torrent est choisi depuis la "Recherche Libre").
Il faut configurer l'ajout à Sonarr/Radarr de manière à ce que leur fonction de recherche automatique de releases soit désactivée pour ce nouvel ajout. MMS doit être le seul à gérer le téléchargement initial pour éviter les doublons.
4. Investigation du Bug des Releases "MULTI" (Session du 2025-10-28)
Problème : Les releases de torrents contenant la langue "MULTI" (ex: The.Lowdown.S01E01.MULTi.720p.WEB.H264-TFA) n'apparaissent pas dans les résultats de la "Recherche Libre", même lorsque le filtre de langue est sur "Tous". La configuration de l'application définit pourtant "MULTI" comme un alias de "FRENCH".

Investigation et Leçons Apprises :

Hypothèse 1 (Incorrecte) : Problème de parsing de langue.

Action : Modification de app/utils/release_parser.py pour mieux gérer les alias et normaliser "multi" en "french".
Résultat : Échec. Le problème persistait, indiquant que les releases "MULTI" n'arrivaient même pas jusqu'à l'étape de parsing.
Hypothèse 2 (Incorrecte) : Suppression complète du filtrage.

Action : Suppression du paramètre cat lors de l'appel à l'API Prowlarr dans app/utils/prowlarr_client.py.
Résultat : Échec et retour utilisateur confirmant que le filtrage par catégorie est une fonctionnalité essentielle pour exclure les types de contenu non désirés (musique, livres, etc.).
Hypothèse 3 (Correcte) : Filtrage par catégorie trop restrictif.

Analyse : Les logs de Prowlarr, fournis par l'utilisateur, ont montré l'appel API exact effectué par l'application : ...&cat=5000,5030,5040,.... Cet appel demande explicitement à Prowlarr de ne retourner que les résultats appartenant à une liste de catégories prédéfinies.
Cause Racine : La release "MULTI" (The.Lowdown.S01E01.MULTi...) se trouve sur l'indexeur dans une catégorie qui n'est pas incluse dans la liste envoyée à Prowlarr. Le problème n'est ni la langue, ni le parsing, mais bien la sélection des catégories en amont.
Objectif pour la Prochaine Session : La solution ne consiste pas à supprimer le filtrage par catégorie, mais à le rendre correct. Il faudra :

Identifier la ou les catégories Prowlarr exactes contenant les releases "MULTI" souhaitées. La liste complète des catégories a été fournie par l'utilisateur.
S'assurer que ces catégories sont correctement sélectionnées dans l'interface de configuration de l'application (page /configuration).
Vérifier que la logique qui charge ces catégories (load_search_categories dans app/utils/config_manager.py) et les applique dans app/search_ui/__init__.py fonctionne comme prévu.
Si nécessaire, modifier l'interface de configuration pour rendre la sélection des catégories plus claire ou plus robuste.

---
### Résumé de Session (Fin Octobre 2025) - Correction des Bandes-Annonces

**Objectif :** Corriger les régressions critiques de la modale de recherche de bande-annonce (fonctionnalités manquantes, erreurs 404).

**Progrès :**
- L'architecture a été refactorisée avec succès pour utiliser une seule modale et un système d'événement global (), ce qui est une base solide.
- Le bug 404 principal sur la recherche initiale () a été corrigé en alignant le format de l'URL du frontend avec la route du backend (utilisation de paramètres de requête).
- L'interface visuelle de la modale a été restaurée.

**Échec Final et État Actuel :**
- La session s'est terminée sur une nouvelle erreur 404, cette fois lors du clic sur le bouton "Effacer les résultats".
- **Cause :** Le même type de bug que précédemment. Le JS appelle une URL avec des paramètres dans le chemin (), alors que la route backend attend une URL simple () avec les données envoyées dans le corps d'une requête POST.

**Plan d'Action Impératif pour la Prochaine Session :**
1.  **Corriger l'appel  :** Dans , modifier l'appel  pour envoyer  et  dans le corps de la requête .
2.  **AUDITER TOUS LES APPELS API :** Vérifier systématiquement **tous** les appels  dans  (, , etc.) pour s'assurer qu'ils sont conformes à leurs routes backend respectives (chemin vs. corps de la requête).
3.  **Tester exhaustivement** chaque bouton de la modale.


---
### Résumé de Session (Fin Octobre 2025) - Correction des Bandes-Annonces

**Objectif :** Corriger les régressions critiques de la modale de recherche de bande-annonce (fonctionnalités manquantes, erreurs 404).

**Progrès :**
- L'architecture a été refactorisée avec succès pour utiliser une seule modale et un système d'événement global (`openTrailerSearch`), ce qui est une base solide.
- Le bug 404 principal sur la recherche initiale (`get_trailer_info`) a été corrigé en alignant le format de l'URL du frontend avec la route du backend (utilisation de paramètres de requête).
- L'interface visuelle de la modale a été restaurée.

**Échec Final et État Actuel :**
- La session s'est terminée sur une nouvelle erreur 404, cette fois lors du clic sur le bouton "Effacer les résultats".
- **Cause :** Le même type de bug que précédemment. Le JS appelle une URL avec des paramètres dans le chemin (`/api/agent/clear_trailer_cache/tv/123`), alors que la route backend attend une URL simple (`/api/agent/clear_trailer_cache`) avec les données envoyées dans le corps d'une requête POST.

**Plan d'Action Impératif pour la Prochaine Session :**
1.  **Corriger l'appel `clear_trailer_cache` :** Dans `app/static/js/global_trailer_search.js`, modifier l'appel `fetch` pour envoyer `media_type` et `external_id` dans le corps de la requête `POST`.
2.  **AUDITER TOUS LES APPELS API :** Vérifier systématiquement **tous** les appels `fetch` dans `global_trailer_search.js` (`lock_trailer`, `unlock_trailer`, etc.) pour s'assurer qu'ils sont conformes à leurs routes backend respectives (chemin vs. corps de la requête).
3.  **Tester exhaustivement** chaque bouton de la modale.

---
### Résumé de Session (31 Octobre 2025) - Stabilisation de la Modale de Bande-Annonce

**Objectif :** Finaliser la refactorisation de la modale de bande-annonce et corriger les bugs persistants.

**Succès :**
1.  **Correction de l'erreur `TypeError` à l'ouverture :** Le bug qui empêchait la modale de s'ouvrir a été résolu en corrigeant une incohérence d'ID (`#trailer-selection-modal` vs. `#trailer-search-modal`) entre le HTML et le JavaScript.
2.  **Correction de la régression `undefined_undefined` :** La cause de la création de clés `undefined_undefined` dans la base de données a été identifiée et corrigée. Les boutons de bande-annonce sur la page "Recherche par Média" n'avaient pas les bons attributs `data-`. Le code dans `app/static/js/search_logic.js` a été corrigé pour générer et lire les bons attributs (`data-media-type`, `data-external-id`).
3.  **Correction de la fonctionnalité "Effacer les résultats" :** Le bouton "Effacer les résultats" était non fonctionnel. Une solution full-stack a été implémentée : création de la route API `POST /api/agent/clear_trailer_cache`, ajout de la logique de suppression dans `TrailerManager`, et ajout du gestionnaire d'événements `fetch` dans le JavaScript.
4.  **Correction de la barre de recherche "Affiner" :** Cette barre de recherche était également non fonctionnelle. Un gestionnaire d'événements a été ajouté pour capturer le clic, construire une nouvelle requête de recherche et réutiliser la fonction `fetchAndRenderTrailers` pour mettre à jour les résultats.

**Échec Final et État Actuel :**
Malgré les corrections successives, la session s'est terminée sur une persistance de la régression `undefined_undefined`. Les logs fournis par l'utilisateur montrent que l'API est toujours appelée avec `media_type=undefined`.

**Cause la Plus Probable :**
Nous avons tourné en rond, corrigeant le bug dans `search_logic.js` à plusieurs reprises. Il semble y avoir un problème persistant où les modifications apportées à ce fichier ne sont pas correctement conservées ou prises en compte, menant à une réintroduction systématique du même bug. L'environnement de test Playwright s'est également avéré très instable et peu fiable, nous faisant perdre un temps considérable.

**Plan d'Action Impératif pour la Nouvelle Session :**
L'objectif est de repartir sur une base "fraîche" et de valider une fois pour toutes le correctif pour le bug `undefined_undefined`.
1.  **Vérification Initiale :** Commencer par inspecter **immédiatement** le fichier `app/static/js/search_logic.js`.
2.  **Confirmer l'État du Bug :** Vérifier la fonction `renderMediaResults` et le gestionnaire de clic `.search-trailer-btn`. S'assurer que les boutons sont générés avec `data-media-type` et `data-external-id`, et que le gestionnaire de clic lit bien ces deux attributs pour les passer à l'événement `openTrailerSearch`.
3.  **Appliquer le Correctif (si nécessaire) :** Si le bug est toujours présent, le corriger de manière définitive comme nous l'avons déjà fait.
4.  **Tester Manuellement :** Étant donné les échecs de Playwright, il sera plus efficace de lancer l'application et de demander à l'utilisateur de confirmer manuellement que le bug a disparu depuis la page "Recherche par Média".
5.  **Passer aux Bugs Suivants :** Une fois ce problème de base résolu, nous pourrons nous attaquer aux autres bugs potentiels de la modale.
