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
