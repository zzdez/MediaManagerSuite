// Fichier : app/static/js/global_trailer_search.js
// Contient toute la logique partagée pour la recherche de bandes-annonces.

/**
 * Ajoute les résultats de la recherche de bande-annonce à la modale.
 * @param {Array} results - La liste des résultats à afficher.
 * @param {Object} options - Options d'affichage.
 * @param {string|null} options.lockedVideoId - L'ID de la vidéo actuellement verrouillée.
 * @param {boolean} options.showLock - Si vrai, affiche le bouton de verrouillage.
 */
function renderTrailerResults(results, options = {}) {
    const { lockedVideoId = null, showLock = false } = options;
    const resultsContainer = $('#trailer-results-container');

    if ((!results || results.length === 0) && resultsContainer.is(':empty')) {
        resultsContainer.html('<p class="text-center text-muted">Aucun résultat trouvé.</p>');
        return;
    }

    results.forEach(result => {
        const isLocked = result.videoId === lockedVideoId;
        const btnClass = isLocked ? 'btn-success' : 'btn-outline-warning';
        const btnTitle = isLocked ? 'Déverrouiller cette bande-annonce' : 'Verrouiller cette bande-annonce';

        const lockButtonHtml = showLock ? `
            <button class="btn btn-sm ${btnClass} lock-trailer-btn ms-3" title="${btnTitle}"
                    data-video-id="${result.videoId}"
                    data-is-locked="${isLocked}">
                <i class="bi bi-lock-fill"></i>
            </button>
        ` : '';

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
                ${lockButtonHtml}
            </div>
        `;
        resultsContainer.append(resultHtml);
    });
}


$(document).ready(function() {
    // --- GESTIONNAIRES D'ÉVÉNEMENTS GLOBAUX ---

    // Ouvre la modale pour une recherche autonome (sans contexte)
    $(document).on('click', '#standalone-trailer-search-btn', function(e) {
        e.preventDefault();
        const selectionModal = $('#trailer-selection-modal');
        selectionModal.removeData('ratingKey').removeData('title').removeData('year').removeData('mediaType');
        $('#trailer-results-container').empty();
        $('#trailer-custom-search-input').val('');
        $('#trailer-load-more-container').hide();
        bootstrap.Modal.getOrCreateInstance(selectionModal[0]).show();
    });

    // Gère la recherche personnalisée depuis la barre de recherche de la modale
    $(document).on('click', '#trailer-custom-search-btn', function() {
        const selectionModal = $('#trailer-selection-modal');
        const query = $('#trailer-custom-search-input').val().trim();
        let mediaContext = selectionModal.data();
        const resultsContainer = $('#trailer-results-container');

        if (!query) return;

        let searchTitle = mediaContext.title;
        let searchYear = mediaContext.year;
        let searchMediaType = mediaContext.mediaType;

        // Si pas de contexte (recherche autonome), on utilise la requête comme titre
        if (!searchTitle) {
            searchTitle = query;
            searchYear = '';
            searchMediaType = 'movie'; // Default
        }

        resultsContainer.empty().html('<div class="text-center"><div class="spinner-border"></div></div>');
        $('#trailer-load-more-container').hide();

        fetch('/api/agent/custom_trailer_search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                title: searchTitle,
                year: searchYear,
                media_type: searchMediaType
            })
        })
        .then(response => response.json())
        .then(data => {
            const showLock = !!mediaContext.ratingKey;
            const lockedVideoId = showLock ? resultsContainer.find('.lock-trailer-btn[data-is-locked="true"]').data('video-id') : null;

            resultsContainer.empty(); // Vider avant d'afficher les nouveaux résultats
            if (data.success && data.results) {
                renderTrailerResults(data.results, { lockedVideoId, showLock });
            } else {
                renderTrailerResults([], { lockedVideoId, showLock });
            }
        })
        .catch(error => {
            console.error('Erreur de recherche personnalisée:', error);
            resultsContainer.html('<p class="text-danger text-center">Une erreur est survenue.</p>');
        });
    });

    // Gère le clic sur "Afficher plus"
    $(document).on('click', '#load-more-trailers-btn', function() {
        const button = $(this);
        const pageToken = button.data('page-token');
        const query = button.data('query');
        const selectionModal = $('#trailer-selection-modal');
        const mediaContext = selectionModal.data();
        const showLock = !!mediaContext.ratingKey;
        const lockedVideoId = showLock ? $('#trailer-results-container .lock-trailer-btn[data-is-locked="true"]').data('video-id') : null;

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        fetch('/api/agent/suggest_trailers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, page_token: pageToken })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success && data.results) {
                renderTrailerResults(data.results, { lockedVideoId, showLock }); // append
                if (data.nextPageToken) {
                    button.data('page-token', data.nextPageToken);
                } else {
                    $('#trailer-load-more-container').hide();
                }
            }
        })
        .catch(error => console.error('Erreur chargement page suivante:', error))
        .finally(() => button.prop('disabled', false).html('Afficher 5 de plus'));
    });

    // Gère le clic pour jouer une vidéo
    $(document).on('click', '.play-trailer-area', function() {
        const videoId = $(this).data('video-id');
        const videoTitle = $(this).data('video-title');
        const selectionModal = $('#trailer-selection-modal');
        const playerModal = $('#trailer-modal');

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
            const sourceModal = new bootstrap.Modal(document.getElementById(sourceModalId));
            sourceModal.show();
            playerModal.removeData('source-modal');
        }
    });
});
