// Fichier : app/static/js/global_trailer_search.js
// Nouvelle version simplifiée utilisant le TrailerManager et les API unifiées.

/**
 * Affiche les résultats de la recherche de bande-annonce dans le conteneur.
 * @param {Array} results - La liste des vidéos YouTube à afficher.
 *param {Object} options - Options d'affichage.
 * @param {string|null} options.lockedVideoId - L'ID de la vidéo actuellement verrouillée.
 */
function renderTrailerResults(results, options = {}) {
    const { lockedVideoId = null } = options;
    const resultsContainer = $('#trailer-results-container');

    if (!results || results.length === 0) {
        resultsContainer.html('<p class="text-center text-muted">Aucun résultat trouvé.</p>');
        return;
    }

    results.forEach(result => {
        const isLocked = result.videoId === lockedVideoId;
        const btnClass = isLocked ? 'btn-success' : 'btn-outline-secondary';
        const btnTitle = isLocked ? 'Déverrouiller cette bande-annonce' : 'Verrouiller cette bande-annonce';

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
                        data-is-locked="${isLocked}">
                    <i class="bi ${isLocked ? 'bi-unlock-fill' : 'bi-lock-fill'}"></i>
                </button>
            </div>
        `;
        resultsContainer.append(resultHtml);
    });
}

/**
 * Fonction centrale pour récupérer et afficher les bandes-annonces.
 * @param {string} mediaType - 'tmdb' ou 'tvdb'.
 * @param {string} externalId - L'ID du média.
 * @param {string|null} pageToken - Le token pour la pagination.
 */
function fetchAndRenderTrailers(mediaType, externalId, pageToken = null) {
    const resultsContainer = $('#trailer-results-container');
    const loadMoreContainer = $('#trailer-load-more-container');
    const loadMoreBtn = $('#load-more-trailers-btn');
    const selectionModal = $('#trailer-selection-modal');

    // Stocke le contexte pour les actions futures (verrouillage, pagination)
    selectionModal.data({ mediaType, externalId });

    // Affiche un spinner seulement pour la première charge
    if (!pageToken) {
        resultsContainer.html('<div class="text-center"><div class="spinner-border"></div></div>');
    }
    loadMoreContainer.hide();

    let apiUrl = `/api/agent/get_trailer_info?media_type=${mediaType}&external_id=${externalId}`;
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
                // Si c'est verrouillé, on affiche juste la vidéo verrouillée
                const lockedVideo = { videoId: data.locked_video_id, title: 'Bande-annonce verrouillée', thumbnail: '/static/img/locked_trailer_placeholder.png', channel: '' };
                renderTrailerResults([lockedVideo], { lockedVideoId: data.locked_video_id });
            } else if (data.status === 'success' && data.results) {
                renderTrailerResults(data.results, { lockedVideoId: null });
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
        const videoId = button.data('video-id');
        const selectionModal = $('#trailer-selection-modal');
        const { mediaType, externalId } = selectionModal.data();

        if (!mediaType || !externalId || !videoId) return;

        const endpoint = isLocked ? '/api/agent/unlock_trailer' : '/api/agent/lock_trailer';
        const payload = { media_type: mediaType, external_id: externalId, video_id: videoId };

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
                fetchAndRenderTrailers(mediaType, externalId);
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
    $(document).on('openTrailerSearch', function(event, { mediaType, externalId, title }) {
        const selectionModal = $('#trailer-selection-modal');
        const modalInstance = bootstrap.Modal.getOrCreateInstance(selectionModal[0]);

        // Nettoyage de l'état précédent
        $('#trailer-results-container').empty();
        $('#trailer-load-more-container').hide();
        $('#trailer-selection-modal-label').text(`Bande-annonce pour : ${title}`);

        // Lance la recherche
        fetchAndRenderTrailers(mediaType, externalId);

        modalInstance.show();
    });
});