// Fichier : app/static/js/global_trailer_search.js
// Nouvelle version simplifiée utilisant le TrailerManager et les API unifiées.

/**
 * Affiche les résultats de la recherche de bande-annonce dans le conteneur.
 * @param {Array} results - La liste des vidéos YouTube à afficher.
 *param {Object} options - Options d'affichage.
 * @param {string|null} options.lockedVideoId - L'ID de la vidéo actuellement verrouillée.
 */
function renderTrailerResults(results, options = {}) {
    const { lockedVideoData = null } = options;
    const resultsContainer = $('#trailer-results-container');
    const lockedVideoId = lockedVideoData ? lockedVideoData.videoId : null;

    if (!results || results.length === 0) {
        resultsContainer.html('<p class="text-center text-muted">Aucun résultat trouvé.</p>');
        return;
    }

    results.forEach(result => {
        const isLocked = result.videoId === lockedVideoId;
        const btnClass = isLocked ? 'btn-danger' : 'btn-outline-secondary';
        const btnTitle = isLocked ? 'Déverrouiller cette bande-annonce' : 'Verrouiller cette bande-annonce';
        const iconClass = isLocked ? 'bi-lock-fill' : 'bi-unlock-fill'; // Correct: lock-fill for locked state

        const resultHtml = `
            <div class="trailer-result-item d-flex align-items-center justify-content-between mb-2 p-2 rounded" style="background-color: #343a40;">
                <div class="play-trailer-area d-flex align-items-center" style="cursor: pointer; flex-grow: 1;"
                     data-video-id="${result.videoId}" data-video-title="${result.title}">
                    <img src="${result.thumbnail}" width="120" class="me-3 rounded">
                    <div>
                        <p class="mb-0 text-white font-weight-bold">${result.title}</p>
                        <small class="text-muted">${result.channel}</small>
                    </div>
                </div>
                <button class="btn btn-sm ${btnClass} lock-trailer-btn" title="${btnTitle}"
                        data-video-id="${result.videoId}"
                        data-is-locked="${isLocked}"
                        data-video-title="${result.title}"
                        data-video-thumbnail="${result.thumbnail}"
                        data-video-channel="${result.channel}">
                    <i class="bi ${iconClass}"></i>
                </button>
            </div>
        `;
        resultsContainer.append(resultHtml);
    });
}

/**
 * Affiche les détails enrichis du média (statuts Plex, Sonarr, etc.).
 * @param {Object} details - L'objet contenant les détails du média.
 */
function renderMediaDetails(details) {
    const placeholder = $('#media-details-placeholder');
    if (!placeholder.length) return;

    let content = '<ul class="list-unstyled mb-0 small text-white-50">';

    // Statut de Production (TMDB)
    if (details.production_status && details.production_status.status) {
        let statusText = details.production_status.status;
        let badgeClass = 'bg-secondary';
        if (statusText === 'Ended') { statusText = 'Terminée'; badgeClass = 'bg-danger'; }
        else if (statusText === 'Returning Series' || statusText === 'In Production') { statusText = 'En cours'; badgeClass = 'bg-success'; }
        else if (statusText === 'Released') { statusText = 'Sorti'; badgeClass = 'bg-info text-dark'; }
        content += `<li><strong>Statut:</strong> <span class="badge ${badgeClass}">${statusText}</span></li>`;
    }

    // Statut Radarr
    if (details.radarr_status && details.radarr_status.present) {
        let status = `<strong>Radarr:</strong> <span class="text-success">Présent</span>`;
        if (details.radarr_status.has_file) status += ' <small class="text-muted">(avec fichier)</small>';
        content += `<li>${status}</li>`;
    }

    // Statut Sonarr
    if (details.sonarr_status && details.sonarr_status.present) {
        let status = `<strong>Sonarr:</strong> <span class="text-success">Présente</span>`;
        if (details.sonarr_status.has_file) status += ' <small class="text-muted">(avec fichiers)</small>';
        content += `<li>${status}</li>`;
    }

    // Statut Plex
    if (details.plex_status && details.plex_status.present) {
        let plexText = '<strong>Plex:</strong> <span class="text-info">Présent</span>';
        if (details.plex_status.physical_presence) plexText += ' <small class="text-muted">(physiquement)</small>';
        else plexText += ' <small class="text-muted">(métadonnées seules)</small>';

        let watchStatus = [];
        if (details.plex_status.is_watched) watchStatus.push('Vu');
        if (details.plex_status.seen_via_tag) watchStatus.push('Archivé');
        if (details.plex_status.watched_episodes && details.plex_status.watched_episodes !== '0/0') {
             watchStatus.push(`Vus: ${details.plex_status.watched_episodes}`);
        }
        if (watchStatus.length > 0) plexText += ` <span class="text-warning">(${watchStatus.join(', ')})</span>`;
        content += `<li>${plexText}</li>`;
    } else if (details.plex_status) {
        content += `<li><strong>Plex:</strong> <span class="text-muted">Absent</span></li>`;
    }

    content += '</ul>';
    placeholder.html(content);
}

function fetchMediaDetails(mediaType, externalId) {
    const placeholder = $('#media-details-placeholder');
    placeholder.html('<div class="text-center text-muted small"><div class="spinner-border spinner-border-sm me-2"></div>Chargement des détails...</div>');

    fetch(`/api/agent/media/details/${mediaType}/${externalId}`)
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') renderMediaDetails(data.details);
            else placeholder.html('<p class="text-warning small text-center">Détails indisponibles.</p>');
        })
        .catch(error => {
            console.error('Error fetching media details:', error);
            placeholder.html('<p class="text-danger small text-center">Erreur de communication.</p>');
        });
}

/**
 * Fonction centrale pour récupérer et afficher les bandes-annonces.
 * @param {string} mediaType - 'tmdb' ou 'tvdb'.
 * @param {string} externalId - L'ID du média.
 * @param {string} title - Le titre du média.
 * @param {string|null} year - L'année du média.
 * @param {string|null} pageToken - Le token pour la pagination.
 */
function fetchAndRenderTrailers(mediaType, externalId, title, year = null, pageToken = null) {
    const resultsContainer = $('#trailer-results-container');
    const loadMoreContainer = $('#trailer-load-more-container');
    const loadMoreBtn = $('#load-more-trailers-btn');
    const selectionModal = $('#trailer-selection-modal');

    // Stocke le contexte pour les actions futures (verrouillage, pagination)
    selectionModal.data({ mediaType, externalId, title, year });

    // --- AJOUT : Récupération des détails du média ---
    // On nettoie l'ancien placeholder et on en crée un nouveau.
    // Cela garantit que les détails sont rafraîchis à chaque ouverture.
    $('#media-details-placeholder').remove();
    const detailsPlaceholder = $('<div id="media-details-placeholder" class="mb-3 p-3 rounded" style="background-color: #212529;"></div>');
    resultsContainer.before(detailsPlaceholder);
    fetchMediaDetails(mediaType, externalId);
    // --- FIN DE L'AJOUT ---

    // Affiche un spinner seulement pour la première charge
    if (!pageToken) {
        resultsContainer.html('<div class="text-center"><div class="spinner-border"></div></div>');
    }
    loadMoreContainer.hide();

    let apiUrl = `/api/agent/get_trailer_info?media_type=${mediaType}&external_id=${externalId}&title=${encodeURIComponent(title)}`;
    if (year) {
        apiUrl += `&year=${year}`;
    }
    if (pageToken) {
        apiUrl += `&page_token=${pageToken}`;
    }

    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            // Efface le contenu seulement pour la première page
            if (!pageToken) {
                resultsContainer.empty();
            }

            if (data.status === 'locked') {
                // Si c'est verrouillé, on affiche juste les données de la vidéo verrouillée
                renderTrailerResults([data.locked_video_data], { lockedVideoData: data.locked_video_data });
            } else if (data.status === 'success' && data.results) {
                renderTrailerResults(data.results, { lockedVideoData: null });
                if (data.next_page_token) {
                    loadMoreBtn.data('page-token', data.next_page_token);
                    loadMoreContainer.show();
                }
            } else {
                resultsContainer.html(`<p class="text-danger text-center">${data.message || 'Une erreur est survenue.'}</p>`);
            }
        })
        .catch(error => {
            console.error('Erreur lors de la récupération des bandes-annonces:', error);
            resultsContainer.html('<p class="text-danger text-center">Une erreur de communication est survenue.</p>');
        })
        .finally(() => {
            loadMoreBtn.prop('disabled', false).html('Afficher plus');
        });
}

$(document).ready(function() {
    // --- GESTIONNAIRES D'ÉVÉNEMENTS GLOBAUX ---

    // Gère le clic sur "Afficher plus"
    $(document).on('click', '#load-more-trailers-btn', function() {
        const button = $(this);
        const selectionModal = $('#trailer-selection-modal');
        const { mediaType, externalId } = selectionModal.data();
        const pageToken = button.data('page-token');

        if (!mediaType || !externalId || !pageToken) return;

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');
        fetchAndRenderTrailers(mediaType, externalId, pageToken);
    });

    // Gère le clic sur le bouton de verrouillage/déverrouillage
    $(document).on('click', '.lock-trailer-btn', function(e) {
        e.stopPropagation();

        const button = $(this);
        const isLocked = button.data('is-locked') === true;
        const selectionModal = $('#trailer-selection-modal');
        const { mediaType, externalId, title, year } = selectionModal.data();

        if (!mediaType || !externalId) return;

        const videoData = {
            videoId: button.data('video-id'),
            title: button.data('video-title'),
            thumbnail: button.data('video-thumbnail'),
            channel: button.data('video-channel')
        };

        if (!videoData.videoId) return;

        const endpoint = isLocked ? '/api/agent/unlock_trailer' : '/api/agent/lock_trailer';
        const payload = {
            media_type: mediaType,
            external_id: externalId,
            video_data: videoData // On envoie l'objet complet
        };

        // Pour le déverrouillage, seul media_type et external_id sont nécessaires
        if (isLocked) {
            delete payload.video_data;
        }

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // Rafraîchit toute la modale pour obtenir le nouvel état du backend
                fetchAndRenderTrailers(mediaType, externalId, title, year);
            } else {
                alert('Erreur: ' + (data.message || 'Une erreur inconnue est survenue.'));
                button.prop('disabled', false).html(`<i class="bi ${isLocked ? 'bi-unlock-fill' : 'bi-lock-fill'}"></i>`);
            }
        })
        .catch(error => {
            console.error('Erreur technique lors du (dé)verrouillage:', error);
            alert('Une erreur technique est survenue.');
            button.prop('disabled', false).html(`<i class="bi ${isLocked ? 'bi-unlock-fill' : 'bi-lock-fill'}"></i>`);
        });
    });

    // Gère le clic pour jouer une vidéo
    $(document).on('click', '.play-trailer-area', function() {
        const videoId = $(this).data('video-id');
        const videoTitle = $(this).data('video-title');
        const selectionModal = $('#trailer-selection-modal');
        const playerModal = $('#trailer-modal');

        if (!videoId) return;

        bootstrap.Modal.getInstance(selectionModal[0]).hide();
        playerModal.data('source-modal', 'trailer-selection-modal');

        $('#trailerModalLabel').text('Bande-Annonce: ' + videoTitle);
        playerModal.find('.modal-body').html(`<div class="ratio ratio-16x9"><iframe src="https://www.youtube.com/embed/${videoId}?autoplay=1&cc_lang=fr&cc_load_policy=1" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>`);
        bootstrap.Modal.getOrCreateInstance(playerModal[0]).show();
    });

    // Gère la fermeture du lecteur vidéo
    $('#trailer-modal').on('hidden.bs.modal', function () {
        const playerModal = $(this);
        playerModal.find('.modal-body').empty();
        const sourceModalId = playerModal.data('source-modal');
        if (sourceModalId) {
            const sourceModal = bootstrap.Modal.getInstance(document.getElementById(sourceModalId));
            if (sourceModal) {
                sourceModal.show();
            }
            playerModal.removeData('source-modal');
        }
    });

    // Déclencheur global pour ouvrir la modale de recherche de BA
    $(document).on('openTrailerSearch', function(event, { mediaType, externalId, title, year, sourceModalId }) {
        const selectionModal = $('#trailer-selection-modal');
        const modalInstance = bootstrap.Modal.getOrCreateInstance(selectionModal[0]);

        // Stocke l'ID de la modale source pour y revenir plus tard
        if (sourceModalId) {
            selectionModal.data('source-modal-id', sourceModalId);
        }

        // Nettoyage de l'état précédent
        $('#trailer-results-container').empty();
        $('#trailer-load-more-container').hide();
        $('#trailer-selection-modal-label').text(`Bande-annonce pour : ${title}`);

        // Lance la recherche
        fetchAndRenderTrailers(mediaType, externalId, title, year);

        modalInstance.show();
    });

    // --- GESTION DU MENU LATÉRAL "BANDES-ANNONCES" (NOUVELLE VERSION) ---

    // Gère la fermeture de la modale de sélection pour potentiellement rouvrir la modale source
    $('#trailer-selection-modal').on('hidden.bs.modal', function () {
        const selectionModal = $(this);
        const sourceModalId = selectionModal.data('source-modal-id');

        if (sourceModalId) {
            const sourceModalEl = document.getElementById(sourceModalId);
            const sourceModalInstance = bootstrap.Modal.getInstance(sourceModalEl);
            if (sourceModalInstance) {
                sourceModalInstance.show();
            }
            // Nettoie la donnée pour éviter les réouvertures non désirées
            selectionModal.removeData('source-modal-id');
        }
    });

    // Ouvre la nouvelle modale de recherche autonome
    $('#standalone-trailer-search-btn').on('click', function(e) {
        e.preventDefault();
        const searchModal = new bootstrap.Modal(document.getElementById('standalone-trailer-search-modal'));
        searchModal.show();
    });

    // Gère la soumission du formulaire de recherche dans la modale
    $('#standalone-trailer-search-form').on('submit', function(e) {
        e.preventDefault();
        const query = $('#standalone-trailer-search-input').val().trim();
        const mediaType = $('input[name="standalone_media_type"]:checked').val();
        const resultsContainer = $('#standalone-trailer-search-results-container');

        if (!query) {
            resultsContainer.html('<div class="alert alert-warning">Veuillez entrer un titre.</div>');
            return;
        }

        resultsContainer.html('<div class="text-center"><div class="spinner-border"></div></div>');

        fetch(`/search/api/media/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query, media_type: mediaType })
        })
        .then(response => response.json())
        .then(data => {
            renderStandaloneResults(data, mediaType);
        })
        .catch(error => {
            console.error('Erreur lors de la recherche de média autonome:', error);
            resultsContainer.html('<p class="text-danger">Erreur de communication.</p>');
        });
    });

    // Affiche les résultats dans la modale de recherche autonome (version enrichie)
    function renderStandaloneResults(results, mediaType) {
        const resultsContainer = $('#standalone-trailer-search-results-container');
        resultsContainer.empty();

        if (!results || results.length === 0) {
            resultsContainer.html('<p class="text-muted text-center">Aucun résultat trouvé.</p>');
            return;
        }

        // Base URL for TMDB posters, necessary for movies.
        const TMDB_POSTER_BASE_URL = 'https://image.tmdb.org/t/p/w185';

        const listGroup = $('<div class="list-group list-group-flush"></div>');
        results.forEach(item => {
            // Build poster URL with the same logic as the main search page
            const posterUrl = mediaType === 'movie' && item.poster
                ? `${TMDB_POSTER_BASE_URL}${item.poster}`
                : (item.poster || 'https://via.placeholder.com/185x278.png?text=Affiche+non+disponible');

            // Determine button class based on trailer status
            let trailerBtnClass = 'btn-outline-danger';
            if (item.trailer_status === 'LOCKED') {
                trailerBtnClass = 'btn-outline-success';
            } else if (item.trailer_status === 'UNLOCKED') {
                trailerBtnClass = 'btn-outline-primary';
            }

            // New enriched HTML structure inspired by renderMediaResults
            const itemHtml = `
                <div class="list-group-item bg-dark text-white p-3">
                    <div class="row g-3">
                        <div class="col-3">
                            <img src="${posterUrl}" class="img-fluid rounded" alt="Poster de ${item.title}">
                        </div>
                        <div class="col-9 d-flex flex-column">
                            <div>
                                <h6 class="mb-1">${item.title} <span class="text-white-50">(${item.year || 'N/A'})</span></h6>
                                <p class="mb-2 small text-white-50" style="max-height: 100px; overflow-y: auto;">
                                    ${item.overview ? item.overview.substring(0, 150) + (item.overview.length > 150 ? '...' : '') : 'Pas de synopsis disponible.'}
                                </p>
                            </div>
                            <div class="mt-auto">
                                 <button class="btn btn-sm ${trailerBtnClass} open-trailer-search-from-standalone"
                                        data-media-type="${mediaType}"
                                        data-external-id="${item.id}"
                                        data-title="${item.title}"
                                        data-year="${item.year || ''}">
                                    <i class="bi bi-film"></i> Voir les bandes-annonces
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            listGroup.append(itemHtml);
        });
        resultsContainer.append(listGroup);
    }

    // Gère le clic sur un bouton de trailer DANS la modale de recherche autonome
    $(document).on('click', '.open-trailer-search-from-standalone', function() {
        const data = $(this).data();

        // On cache la modale de recherche avant d'ouvrir la suivante
        const standaloneModalEl = document.getElementById('standalone-trailer-search-modal');
        const standaloneModalInstance = bootstrap.Modal.getInstance(standaloneModalEl);
        if (standaloneModalInstance) {
            standaloneModalInstance.hide();
        }

        // On déclenche l'événement global en passant l'ID de la modale source pour pouvoir y revenir
        $(document).trigger('openTrailerSearch', {
            mediaType: data.mediaType,
            externalId: data.externalId,
            title: data.title,
            year: data.year,
            sourceModalId: 'standalone-trailer-search-modal'
        });
    });
});