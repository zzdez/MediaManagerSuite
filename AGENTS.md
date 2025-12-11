# AGENTS.md

Ce fichier sert de journal de bord pour notre collaboration. Il a pour but de conserver une trace des échanges, des décisions et des réalisations importantes, afin de faciliter le suivi du projet et de garantir une mémoire à long terme des interventions.

## Configuration de l'Environnement de Développement

Pour lancer l'application localement, les étapes suivantes sont essentielles :

1.  **Créer le fichier d'environnement** : Copiez le template avec `cp .env.template .env`.
2.  **Installer les dépendances** : Exécutez `pip install -r requirements.txt`.
3.  **Créer le répertoire de cookies** : Assurez-vous que le répertoire pour les cookies YGG existe avec `mkdir -p /home/jules/Downloads`.

Sans ces étapes, l'application risque de ne pas démarrer ou de présenter des dysfonctionnements (pages blanches, erreurs 400). Pour les tests frontend avec Playwright, le mot de passe par défaut défini dans `.env.template` est `your_secure_password_here`.

## Historique du projet

### Gestion des Bandes-annonces

- **Modale globale** : Une modale unique (`trailer_search_modal.html`) est utilisée à travers toute l'application. Elle est déclenchée via un événement JavaScript global `openTrailerSearch`.
- **Mise à jour de l'UI en temps réel** : Pour refléter immédiatement les changements (ajout/suppression de bande-annonce), la modale émet un événement `trailerStatusUpdated` à sa fermeture. Les différentes pages (Plex Editor, Search UI) écoutent cet événement et mettent à jour la couleur des boutons correspondants.
- **État et cache** : L'état de la modale (résultats de recherche, pagination) est entièrement réinitialisé à chaque ouverture pour éviter les problèmes de cache et de persistance des données entre les utilisations.
- **Prévisualisation et Métadonnées** : La fonctionnalité d'ajout manuel via un lien YouTube inclut une prévisualisation. Lors du verrouillage (`lock`), le backend récupère les métadonnées complètes de la vidéo (titre, chaîne, miniature) via l'API YouTube pour un affichage enrichi.

#### Points techniques clés

- **Déclenchement** : `window.dispatchEvent(new CustomEvent('openTrailerSearch', { detail: { ... } }));`
- **Écoute** : `window.addEventListener('trailerStatusUpdated', (e) => { ... });`
- **Sélecteurs de boutons** :
  - `.search-trailer-btn` (Page de recherche)
  - `.find-and-play-trailer-btn` (Plex Editor)
  - `.find-trailer-from-map-btn` (Modale de mapping)

### Recherche et Téléchargement

- **Recherche "Intelligente" d'épisodes manquants** : La recherche d'épisodes manquants est optimisée. Plutôt que de chercher chaque épisode individuellement, le système génère des requêtes par saison (`Nom de la série S0X`) pour améliorer l'efficacité et la pertinence des résultats. Le filtrage final par épisode se fait côté client (JavaScript), ce qui allège la charge du serveur et de Prowlarr.
- **Ouverture dans un nouvel onglet** : Les actions de recherche (épisodes manquants, recherche manuelle) depuis l'éditeur Plex ouvrent systématiquement la page de résultats dans un nouvel onglet du navigateur. Cela préserve l'état de la page précédente, permettant un retour fluide au contexte initial.
- **Gestion des erreurs et validation** : Des gardes ont été ajoutées pour gérer les cas où les API externes (comme Prowlarr) ne retournent aucun résultat. Le système renvoie une liste vide avec un statut 200 OK, évitant les crashs et les erreurs 500. L'entrée utilisateur est également validée pour prévenir les injections de données invalides (`null`) qui pourraient faire planter le backend.
- **Filtres de recherche avancés** : La page de recherche dispose de filtres configurables via le fichier `.env` qui permettent d'affiner les résultats par qualité, langue, codec, etc., en se basant sur un système d'alias robustes.

### Éditeur Plex et Gestion des Médias

- **Standardisation des identifiants** : Le système a été unifié pour utiliser exclusivement les identifiants externes (TMDB pour les films, TVDB pour les séries) afin de garantir la cohérence des données, notamment pour la gestion des bandes-annonces.
- **Gestion des Saisons et Épisodes** : La modale de gestion des séries a été enrichie pour afficher un double statut pour chaque saison : le statut de visionnage de Plex et le statut de disponibilité physique des fichiers de Sonarr.
- **Déplacement de fichiers robustes** : La fonctionnalité de déplacement de médias a été fiabilisée grâce à un système de *polling* basé sur le système de fichiers, assurant que l'interface utilisateur ne se met à jour qu'une fois le déplacement physique terminé.
- **Filtres asynchrones** : Les filtres de l'éditeur Plex (utilisateurs, bibliothèques) sont chargés de manière asynchrone. Le code JavaScript gère désormais correctement cette asynchronie en attendant que les données soient disponibles avant de tenter de restaurer les sélections précédentes.

### Interface Utilisateur (UI) et Expérience Utilisateur (UX)

- **Gestion de la session et des données inter-pages** : Pour passer des données à usage unique (comme des requêtes de recherche) entre les pages, le système utilise la session Flask. Une route API dédiée sert les données au JavaScript de la page de destination, puis les supprime immédiatement de la session, évitant ainsi les problèmes de "cache fantôme".
- **Composants globaux réutilisables** : La philosophie est de réutiliser, adapter et étendre les composants existants. Par exemple, la modale de bande-annonce est un composant global, assurant une expérience utilisateur cohérente et une maintenance simplifiée.
- **Désactivation conditionnelle des éléments** : Les éléments interactifs comme les cases à cocher restent toujours activés, même si la ligne est visuellement grisée (par exemple, pour un fichier manquant). Cela garantit que l'utilisateur ne perd jamais le contrôle sur les éléments, même s'ils sont indisponibles.

### Seedbox et Gestion des Torrents

- **Tâches en arrière-plan et contexte applicatif** : Les tâches longues, comme le scan de la seedbox, sont exécutées dans des threads séparés pour ne pas bloquer l'interface. Pour que ces threads puissent accéder aux services de l'application (comme les logs), ils sont exécutés à l'intérieur du contexte de l'application Flask (`with app.app_context():`).
- **Gestion des erreurs Prowlarr** : Le client Prowlarr a été rendu plus robuste. Si une recherche externe échoue ou prend trop de temps, la fonction retourne `None`. Le code appelant doit impérativement vérifier ce retour (`isinstance(result, list)`) avant de tenter d'itérer sur les résultats, prévenant ainsi des crashs de type `TypeError`.

#### Modale d'Ajout de Torrent : Interactions Complexes

La modale d'ajout de torrent (`addTorrentModal`) présente des défis uniques en raison de son interaction avec la modale globale de recherche de bande-annonce. Voici les points d'attention cruciaux :

-   **Gestion du focus entre les modales** : Pour éviter que la modale d'arrière-plan (`addTorrentModal`) ne "capture" le focus du clavier et de la souris, il est impératif de la masquer explicitement (`.hide()`) *avant* d'afficher la modale de bande-annonce par-dessus. Le retour à la modale d'origine est géré automatiquement par le système de `sourceModalId`.
-   **Préservation de l'état** : Le masquage de la modale d'ajout déclenche son événement de réinitialisation, ce qui vide son contenu. Pour préserver l'état (fichier torrent chargé, média sélectionné) lors du retour, un mécanisme de drapeau a été mis en place :
    1.  Un attribut `data-is-returning-from-trailer` est ajouté à `addTorrentModal` avant de la masquer.
    2.  L'écouteur d'événement `show.bs.modal` de cette modale vérifie la présence de ce drapeau. S'il existe, la fonction de réinitialisation est ignorée.
-   **Utilisation des bons identifiants** : Pour la recherche de bande-annonce, il est **critique** d'utiliser l'identifiant externe (TMDB ID pour les films, TVDB ID pour les séries). L'interface doit donc stocker à la fois l'ID interne de Sonarr/Radarr (pour le mapping) et l'ID externe (dans un attribut `data-selected-media-external-id`) pour la recherche de bande-annonce. Le code qui déclenche la recherche doit impérativement utiliser cet ID externe.

### Fonctionnalité d'Archivage Améliorée (Novembre 2025)

- **Objectif** : Créer un historique de visionnage persistant, même après suppression des médias de Plex. Lors de l'archivage, les détails de visionnage d'un utilisateur sont extraits de Plex et sauvegardés dans une base de données locale. Ces informations sont ensuite utilisées pour enrichir les futures recherches.

- **Composants clés** :
  - `app/utils/archive_manager.py` : Un nouveau module qui gère une base de données `instance/archive_database.json`. Il inclut un système de verrouillage de fichier (`.lock`) pour éviter les corruptions lors d'écritures concurrentes. La logique `add_archived_media` est conçue pour mettre à jour l'historique d'un utilisateur existant plutôt que de créer des doublons.
  - `app/utils/plex_client.py` : Refactorisé en une classe `PlexClient` pour gérer proprement les connexions Plex spécifiques à chaque utilisateur, ce qui est crucial pour récupérer l'historique de visionnage correct. Cette classe est capable de générer des URL de posters authentifiées et de construire un objet `watch_history` détaillé (statut global, statut par saison, nombre d'épisodes vus/total).

- **Intégration UI** :
  - **Plex Editor (`/plex/`)** : Si une recherche ne trouve rien dans Plex, le système consulte la base d'archives. Les résultats archivés sont affichés via un template `_archived_media_card.html` qui présente le poster, le résumé et un historique de visionnage formaté (ex: "Saison 1: Vus (10 / 10 ép.)").
  - **Recherche Globale (`/search/`)** : Le `media_info_manager.py` enrichit les résultats de recherche externes (TMDB/TVDB) en vérifiant s'ils existent dans la base d'archives. Si c'est le cas, un badge "Archivé" est ajouté au résultat, avec l'historique de visionnage disponible dans une infobulle (tooltip).

- **État Actuel et Problèmes Rencontrés** :
  - La fonctionnalité de base (sauvegarde et récupération) est implémentée.
  - **Problème 1 (Plex Editor)** : Lors de l'affichage des résultats archivés sur la page `/plex/`, l'affichage est défectueux. Le poster n'apparaît pas et les informations de visionnage sont brutes et mal formatées. De plus, la logique crée des entrées dupliquées pour un même utilisateur au lieu de les mettre à jour.
  - **Problème 2 (Recherche Globale)** : La page de recherche (`/search/`) subit un crash (`TypeError`) lorsqu'elle tente d'enrichir les résultats avec les données d'archives. Cela est dû à une incohérence dans les arguments passés à une fonction du `media_info_manager`.
  - **Cause Racine des bugs (Corrigés en théorie)** :
    - Le `PlexClient` ne construisait pas une URL complète et authentifiée pour le poster. **(Corrigé)**
    - Le `archive_manager` ne comparait pas correctement les `user_id`, provoquant les doublons. **(Corrigé)**
    - Les templates Jinja2 n'étaient pas adaptés pour afficher correctement la nouvelle structure de données de `watch_history`. **(Corrigé)**
    - L'appel de fonction dans `media_info_manager` n'avait pas été mis à jour suite à une refactorisation. **(Corrigé)**
    - Des régressions dans les routes d'archivage (`plex_editor/routes.py`) appelaient des fonctions inexistantes. **(Corrigé)**

- **Prochaines Étapes (Nouvelle Session)** :
  1.  **Priorité 1: Déboguer l'affichage sur la page Plex Editor (`/plex/`)** :
      - Malgré les correctifs, le problème d'affichage (posters, formatage) persiste. Il faut vérifier la transmission des données du backend au frontend et l'interprétation par le template Jinja2 `_archived_media_card.html`. Il est possible qu'un rafraîchissement JavaScript soit nécessaire après l'injection du HTML.
  2.  **Priorité 2: Déboguer la page de Recherche Globale (`/search/`)** :
      - Vérifier que les correctifs ont bien résolu le `TypeError`.
      - S'assurer que le badge "Archivé" et l'infobulle (tooltip) s'affichent correctement et avec les bonnes informations formatées sur les résultats de recherche pertinents.
  3.  **Validation Complète** :
      - Effectuer un test de bout en bout : archiver un nouveau média, puis le rechercher dans les deux interfaces pour confirmer que l'ensemble du flux fonctionne comme prévu.

### Session du 7 Novembre 2025 : Fiabilisation et Préparation de la Synchro de l'Historique Fantôme

- **Objectif initial** : Corriger les bugs d'affichage des médias archivés et explorer la possibilité de synchroniser l'historique des médias supprimés de Plex ("historique fantôme").

- **Réalisations** :
  - **Correction de la logique d'archivage manuelle** : Nous avons pivoté pour corriger la cause racine des bugs d'affichage. La fonction `add_archived_media` dans `archive_manager.py` a été entièrement revue pour :
    - **Empêcher les doublons** : Le système remplace désormais l'entrée d'un utilisateur pour un média donné, au lieu d'en ajouter une nouvelle à chaque archivage.
    - **Enrichissement des métadonnées** : La fonction récupère maintenant des métadonnées riches et persistantes (poster, résumé, année) depuis TMDB (pour les films) et TVDB (pour les séries), garantissant que les informations restent valides même après la suppression du média de Plex.
    - **Standardisation des clés** : Les entrées dans `archive_database.json` utilisent maintenant un format de clé standard (`tv_<id>` ou `movie_<id>`), améliorant la cohérence de la base de données.
    - **Correction de bugs multiples** : Nous avons résolu des `TypeError` dans les routes et des incohérences dans la structure des données de visionnage (`watched_status`).

  - **Préparation du script de synchronisation de l'historique fantôme** :
    - **Création d'une page de test** : Une nouvelle page a été ajoutée à l'URL `/plex/sync_test` avec un template `sync_test.html` et un bouton pour lancer le test.
    - **Implémentation de la logique de scan** : Une nouvelle route, `/plex/run_sync_test`, a été créée. Elle contient la logique principale pour :
      1.  Parcourir l'historique complet de Plex.
      2.  Identifier les éléments "fantômes" (ceux dont la source n'existe plus).
      3.  Extraire l'identifiant externe (TMDB/TVDB) à partir du `guid` de l'entrée d'historique.
      4.  Appeler la fonction fiabilisée `add_archived_media` pour sauvegarder ces médias fantômes dans notre base de données.
    - Le script est conçu pour un test initial : il s'arrête après avoir trouvé et archivé un film et une série.

- **Problème Bloquant : Instabilité du Serveur de Développement** :
  - Un problème majeur et persistant avec le serveur Flask nous a empêchés de tester les nouvelles fonctionnalités.
  - **Symptômes** : Le serveur ne prend pas en compte les modifications de code, même après redémarrage. Les nouvelles routes renvoient systématiquement des erreurs `404 Not Found`, et les routes existantes comme `/login` renvoient des erreurs `405 Method Not Allowed` pour les requêtes `POST`, bien que le code soit correct.
  - **Actions de débogage (sans succès)** :
    - Vérification des blueprints et des préfixes d'URL.
    - Suppression des caches Python (`__pycache__`).
    - Activation du `reloader` de Flask dans `run.py`.
    - Ajout de routes de débogage pour lister toutes les routes de l'application.
  - **Conclusion** : L'environnement de développement est dans un état instable qui rend impossible toute vérification. Ce problème devra être résolu en priorité avant de pouvoir continuer.

- **État Final de la Session** :
  - **Succès** : Après de multiples tentatives, le problème de routage a été résolu. La page de test `/plex/sync_test` est désormais accessible.
  - **Échec** : Le script de synchronisation s'exécute mais ne parvient pas à identifier correctement les "items fantômes". La logique actuelle, qui se base sur une exception `NotFound` et une analyse des `guid`, est inefficace.

- **Prochaines Étapes (Stratégie Recommandée)** :
  1.  **Changer de Stratégie de Débogage** : La tentative de "deviner" la structure des données a échoué. La prochaine session doit se concentrer sur l'obtention de données réelles.
  2.  **Modifier le script de test** : Le script `/plex/run_sync_test` doit être temporairement modifié non pas pour traiter les données, mais pour **collecter et logger** les détails bruts d'un échantillon d'entrées de l'historique (par exemple, les 100 premières). Il faudra logger tous les attributs disponibles pour chaque entrée (`entry.type`, `entry.title`, `entry.guid`, `entry.grandparentGuid`, etc.).
  3.  **Analyser les Logs** : L'utilisateur devra lancer ce script modifié et fournir les logs générés.
  4.  **Adapter la Logique** : En se basant sur l'analyse de ces logs, nous pourrons enfin écrire une condition fiable pour identifier un item comme "fantôme" et savoir quel attribut (`guid`, `grandparentGuid`, etc.) contient l'identifiant externe pertinent.
  5.  **Finaliser le Test** : Une fois la logique de détection corrigée, l'utilisateur pourra valider que le script archive bien un film et une série fantômes.
  6.  **Développer la Fonctionnalité Complète** : Procéder ensuite au développement de la synchronisation complète (scan de tout l'historique, bouton dans l'interface, etc.) et à l'enrichissement des données de visionnage.

### Système de Sauvegarde Automatique (Novembre 2025)

- **Objectif** : Mettre en place un système de sauvegarde robuste et configurable pour tous les fichiers de configuration `.json` situés dans le répertoire `instance/`.

- **Composants clés** :
  - **`app/utils/backup_manager.py`** : Un nouveau module centralisé qui contient toute la logique de sauvegarde :
    - `create_backup()`: Crée une archive `.zip` horodatée de tous les fichiers `.json` du répertoire `instance/` et la stocke dans un nouveau répertoire `backups/` à la racine du projet.
    - `manage_retention()`: Supprime les sauvegardes les plus anciennes pour ne conserver que le nombre de copies défini dans la configuration.
    - `get_backups()`, `restore_backup()`, `delete_backup()`: Fonctions pour lister, restaurer et supprimer des sauvegardes individuelles.
  - **Planificateur de tâches (`APScheduler`)** : Intégré dans `app/__init__.py`, un planificateur de tâches exécute la fonction de sauvegarde automatiquement à des intervalles réguliers (horaire, journalier, hebdomadaire) en fonction de la configuration.

- **Intégration UI** :
  - **Page de Configuration (`/configuration/`)** : Une nouvelle section "Sauvegardes Automatiques" a été ajoutée à la page de configuration. Elle permet à l'utilisateur de :
    - **Configurer le planning** (`BACKUP_SCHEDULE`) via un menu déroulant (Désactivée, Toutes les heures, Tous les jours, Toutes les semaines).
    - **Définir la rétention** (`BACKUP_RETENTION`) en spécifiant le nombre de sauvegardes à conserver.
  - **Gestion des Sauvegardes** : Une section "Gestion des Sauvegardes" a également été ajoutée. Elle affiche un tableau de toutes les sauvegardes existantes et permet de :
    - Lancer une sauvegarde manuelle à tout moment.
    - Restaurer une sauvegarde spécifique, ce qui écrase les fichiers de configuration actuels.
    - Supprimer une sauvegarde obsolète.

- **Configuration via `.env`** :
  - La fonctionnalité est contrôlée par deux nouvelles variables dans le fichier `.env` :
    - `BACKUP_SCHEDULE`: Définit la fréquence des sauvegardes (`disabled`, `hourly`, `daily`, `weekly`).
    - `BACKUP_RETENTION`: Un entier qui détermine le nombre de sauvegardes à conserver.
  - **Note importante** : Les modifications apportées au `BACKUP_SCHEDULE` via l'interface utilisateur ne prennent effet qu'après un redémarrage de l'application, car le planificateur de tâches est initialisé au démarrage.

- **État Actuel** : La fonctionnalité est entièrement implémentée, testée et fonctionnelle.

### Gestion Avancée des Métadonnées et Images Plex (Juin 2025)

- **Objectif** : Améliorer l'interface "Plex Editor" pour permettre l'injection manuelle de métadonnées et, surtout, offrir un moyen de changer facilement les posters et fonds d'écran, palliant l'absence de suppression dans l'API Plex.

- **Réalisations Clés** :
  - **Injection Manuelle des Métadonnées** :
    - Ajout d'un formulaire complet ("Édition Manuelle") dans la modale de détails.
    - Permet de modifier le Titre, Titre Original, Année et Résumé.
    - Support de l'upload local de fichiers (Poster et Background) via un stockage temporaire (`tempfile`) avant envoi à l'API Plex.
    - Implémentation du verrouillage (`lock`) des champs modifiés pour éviter l'écrasement par les agents Plex.

  - **Recherche de Métadonnées (TMDB/TVDB)** :
    - Ajout d'une fonctionnalité "Identifier / Rechercher" permettant de choisir explicitement le fournisseur (TMDB, TVDB) et l'année.
    - Création de la route `/api/metadata_search` pour servir ces résultats.
    - Action "Associer (Fix Match)" qui utilise l'ID externe pour forcer une association correcte via l'agent Plex.

  - **Sélecteur Visuel d'Assets (Visual Asset Selector)** :
    - **Contexte** : La suppression d'un poster uploadé n'est pas possible via l'API `plexapi` actuelle.
    - **Solution** : Création d'une interface à onglets ("Général", "Affiches", "Fonds d'écran").
    - Les onglets "Affiches" et "Fonds d'écran" chargent une grille visuelle de tous les assets disponibles (fournis par les agents ou uploadés).
    - Un clic sur une image la définit comme active (`item.setPoster()` / `item.setArt()`), permettant de changer facilement de visuel sans avoir besoin de supprimer l'ancien.
    - Nouvelle route backend `/api/media_assets/<rating_key>` pour lister ces assets avec des URLs authentifiées.

- **Points Techniques Importants** :
  - **Refresh** : Lors d'un "Reset" (déverrouillage) d'un champ, l'appel `item.refresh()` est désormais systématiquement fait pour forcer la mise à jour immédiate côté Plex.
  - **Upload** : L'upload de fichier utilise `multipart/form-data`. Le backend sauve le fichier temporairement sur disque car `plexapi.uploadPoster` requiert un chemin fichier (ou une URL), pas un flux binaire.
  - **URLs Signées** : Pour afficher les images dans le frontend, les URLs retournées par l'API Plex (`/library/metadata/...`) doivent être signées avec le token (`includeToken=True`).

- **Limitations Connues** :
  - **Suppression d'images** : Il n'y a toujours pas de bouton "Supprimer" pour les images uploadées manuellement, car l'API ne l'expose pas. Le sélecteur visuel est le contournement officiel.
