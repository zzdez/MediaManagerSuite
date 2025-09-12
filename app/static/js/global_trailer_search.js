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
        const resultsContainer = $('#trailer-results-container');
        const loadMoreBtn = $('#load-more-trailers-btn');
        const mediaContext = selectionModal.data(); // Récupère le contexte existant

        if (!query) return;

        // Détermine si on est dans un contexte Plex (avec verrouillage) ou autonome
        const isPlexContext = !!mediaContext.ratingKey;
        const searchTitle = isPlexContext ? mediaContext.title : query;
        const searchYear = isPlexContext ? mediaContext.year : '';
        const searchMediaType = isPlexContext ? mediaContext.mediaType : 'movie';

        // Stocke la nouvelle query pour la pagination autonome
        if (!isPlexContext) {
            selectionModal.data({ 'query': query });
        }

        resultsContainer.empty().html('<div class="text-center"><div class="spinner-border"></div></div>');
        $('#trailer-load-more-container').hide();

        fetch('/api/agent/custom_trailer_search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                title: searchTitle, // Titre original pour le scoring
                year: searchYear,
                media_type: searchMediaType
            })
        })
        .then(response => response.json())
        .then(data => {
            resultsContainer.empty();
            if (data.success && data.results) {
                // Affiche le verrou si on est dans un contexte Plex
                const lockedVideoId = isPlexContext ? mediaContext.locked_video_id : null;
                renderTrailerResults(data.results, { lockedVideoId: lockedVideoId, showLock: isPlexContext });

                // La pagination pour une recherche personnalisée est toujours par pageToken
                if (data.nextPageToken) {
                    loadMoreBtn.data('page-token', data.nextPageToken).data('page', null);
                    $('#trailer-load-more-container').show();
                }
            } else {
                renderTrailerResults([], { showLock: isPlexContext });
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
        const selectionModal = $('#trailer-selection-modal');
        const mediaContext = selectionModal.data(); // Contient ratingKey, title, etc.
        const page = button.data('page');
        const pageToken = button.data('page-token');

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        // Détermine le type de pagination (Plex vs. Autonome)
        if (mediaContext.ratingKey && page) {
            // --- Pagination par numéro de page pour la recherche Plex ---
            fetch('/api/agent/suggest_trailers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...mediaContext, page: page })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success && data.results) {
                    renderTrailerResults(data.results, { lockedVideoId: data.locked_video_id, showLock: true });
                    if (data.has_more) {
                        button.data('page', page + 1); // Incrémente pour le prochain clic
                    } else {
                        $('#trailer-load-more-container').hide();
                    }
                }
            })
            .catch(error => console.error('Erreur chargement page suivante (Plex):', error))
            .finally(() => button.prop('disabled', false).html('Afficher 5 de plus'));

        } else if (pageToken) {
            // --- Pagination par pageToken pour la recherche autonome ---
            const query = mediaContext.query; // Récupère la query stockée
            fetch('/api/agent/custom_trailer_search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: query,
                    title: query,
                    year: '',
                    media_type: 'movie',
                    page_token: pageToken
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success && data.results) {
                    renderTrailerResults(data.results, { showLock: false });
                    if (data.nextPageToken) {
                        button.data('page-token', data.nextPageToken);
                    } else {
                        $('#trailer-load-more-container').hide();
                    }
                }
            })
            .catch(error => console.error('Erreur chargement page suivante (Autonome):', error))
            .finally(() => button.prop('disabled', false).html('Afficher 5 de plus'));
        } else {
             console.error("Erreur de pagination : Contexte invalide (ni page, ni page-token).");
             button.prop('disabled', false).html('Erreur');
        }
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

    // Gère le clic sur le bouton de verrouillage/déverrouillage
    $(document).on('click', '.lock-trailer-btn', function(e) {
        e.stopPropagation();

        const button = $(this);
        const isLocked = button.data('is-locked') === true;
        const videoId = button.data('video-id');
        const selectionModal = $('#trailer-selection-modal');
        const mediaContext = selectionModal.data();

        let endpoint;
        let payload;

        if (mediaContext.ratingKey) {
            // --- Cas 1: Verrouillage permanent pour un item Plex ---
            if (isLocked) {
                // Le déverrouillage ne fonctionne que pour les items Plex
                endpoint = '/api/agent/unlock_trailer';
                payload = { ratingKey: mediaContext.ratingKey, title: mediaContext.title, year: mediaContext.year };
            } else {
                endpoint = '/api/agent/lock_trailer';
                payload = { ratingKey: mediaContext.ratingKey, title: mediaContext.title, year: mediaContext.year, videoId: videoId };
            }
        } else if (mediaContext.media_id) {
            // --- Cas 2: Verrouillage en attente pour un item non-Plex ---
            if (isLocked) {
                // Pas de déverrouillage pour un verrou en attente, on change juste l'UI
                alert("Ce verrouillage est temporaire et sera appliqué lors de l'ajout du média.");
                return;
            }
            endpoint = '/api/agent/pending_lock';
            payload = { media_id: mediaContext.media_id, video_id: videoId };
        } else {
            alert("Erreur: Contexte de verrouillage invalide.");
            return;
        }

        const originalIcon = button.html();
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert(data.message); // Affiche le message de succès
                if (mediaContext.ratingKey) {
                    // Pour un item Plex, on rafraîchit la modale pour voir le changement
                    $(document).trigger('trailerActionSuccess', [mediaContext]);
                } else {
                    // Pour un verrou en attente, on met juste à jour l'UI de ce bouton
                    button.data('is-locked', true).removeClass('btn-outline-warning').addClass('btn-success');
                    button.prop('disabled', false).html(originalIcon);
                }
            } else {
                alert('Erreur: ' + (data.error || "Une erreur inconnue est survenue."));
                button.prop('disabled', false).html(originalIcon);
            }
        })
        .catch(error => {
            console.error('Erreur technique lors du verrouillage:', error);
            alert('Une erreur technique est survenue.');
            button.prop('disabled', false).html(originalIcon);
        });
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
