// Fichier : app/static/js/global_trailer_search.js

$(document).ready(function() {
    const trailerSearchModal = new bootstrap.Modal(document.getElementById('trailer-search-modal'));
    let currentMediaType = null;
    let currentExternalId = null;
    let currentTitle = null;
    let currentYear = null;
    let nextPageToken = null;

    // --- FONCTIONS UTILITAIRES ---
    function renderTrailerResults(results, append = false) {
        const container = $('#trailer-results-container');
        if (!append) container.empty();

        if (results.length === 0 && !append) {
            container.html('<p class="text-center text-muted">Aucun résultat trouvé.</p>');
            return;
        }

        results.forEach(item => {
            const resultHtml = `
                <div class="trailer-result-item d-flex align-items-center justify-content-between mb-2 p-2 rounded" style="background-color: #343a40;">
                    <div class="d-flex align-items-center" style="cursor: pointer;" onclick="playTrailer('${item.video_id}', '${item.title.replace(/'/g, "\\'")}')">
                        <img src="${item.thumbnail}" width="120" class="me-3 rounded">
                        <div>
                            <p class="mb-0 text-white font-weight-bold">${item.title}</p>
                            <small class="text-muted">${item.channel}</small>
                        </div>
                    </div>
                    <button class="btn btn-sm btn-outline-success lock-trailer-btn" title="Verrouiller cette bande-annonce"
                            data-video-id="${item.video_id}"
                            data-video-title="${item.title}"
                            data-video-thumbnail="${item.thumbnail}"
                            data-video-channel="${item.channel}">
                        <i class="bi bi-lock-fill"></i>
                    </button>
                </div>`;
            container.append(resultHtml);
        });
    }

    function showSpinner(inContainer = false) {
        const spinner = '<div class="text-center my-3"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div></div>';
        if (inContainer) $('#trailer-results-container').html(spinner);
        else $('#trailer-results-container').append(spinner);
    }

    // --- LOGIQUE DE RECHERCHE ---
    function searchTrailers(query, forceRefresh = false, token = null) {
        if (!currentMediaType || !currentExternalId) return;

        showSpinner(!token);
        $('#load-more-trailers-btn').hide();

        let url = `/api/agent/get_trailer_info?media_type=${currentMediaType}&external_id=${currentExternalId}&force_refresh=${forceRefresh}`;
        if (query) url += `&query=${encodeURIComponent(query)}`;
        if (token) url += `&page_token=${token}`;

        fetch(url)
            .then(response => {
                if (!response.ok) {
                    return response.text().then(text => { throw new Error('Réponse du serveur non valide: ' + text) });
                }
                return response.json();
            })
            .then(data => {
                if (!token) $('#trailer-results-container').empty();
                else $('#trailer-results-container .spinner-border').parent().remove();

                if (data.status === 'locked' && data.locked_video_data) {
                     $('#trailer-results-container').html('<p class="text-center text-success">Une bande-annonce est déjà verrouillée pour ce média.</p>');
                } else if (data.search_results) {
                    renderTrailerResults(data.search_results, !!token);
                    nextPageToken = data.next_page_token;
                    if (nextPageToken) $('#load-more-trailers-btn').show();
                } else {
                     $('#trailer-results-container').html(`<p class="text-center text-warning">${data.message || 'Aucun résultat ou erreur.'}</p>`);
                }
            })
            .catch(error => {
                console.error('Erreur de recherche de bande-annonce:', error);
                $('#trailer-results-container').html('<p class="text-center text-danger">Erreur de communication.</p>');
            });
    }

    // --- ÉVÉNEMENTS GLOBAUX ---
    $(document).on('openTrailerSearch', function(event, data) {
        currentMediaType = data.mediaType;
        currentExternalId = data.externalId;
        currentTitle = data.title;
        currentYear = data.year;

        $('#trailerSearchModalLabel').text(`Bande-annonce pour : ${currentTitle}`);
        $('#trailer-search-input').val('');
        $('#manual-trailer-preview').hide();
        $('#manual-trailer-url').val('');

        searchTrailers(`${currentTitle} ${currentYear || ''} trailer`);
        trailerSearchModal.show();
    });

    // --- ÉVÉNEMENTS DE LA MODALE ---
    $('#trailer-search-button').on('click', function() {
        const query = $('#trailer-search-input').val().trim();
        if (query) searchTrailers(query, true);
    });

    $('#load-more-trailers-btn').on('click', function() {
        const query = $('#trailer-search-input').val().trim();
        if (nextPageToken) searchTrailers(query || `${currentTitle} ${currentYear || ''} trailer`, false, nextPageToken);
    });

    $('#clear-trailer-cache-btn').on('click', function() {
        if (!confirm("Êtes-vous sûr de vouloir effacer les résultats de recherche pour ce média ?")) return;

        fetch(`/api/agent/clear_trailer_cache/${currentMediaType}/${currentExternalId}`, { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'Cache cleared') {
                    toastr.success('Résultats effacés. Une nouvelle recherche sera effectuée.');
                    $('#trailer-results-container').empty();
                    searchTrailers(`${currentTitle} ${currentYear || ''} trailer`, true);
                } else {
                    toastr.error(data.message || 'Erreur lors du nettoyage du cache.');
                }
            });
    });

    // Verrouiller une bande-annonce (depuis les résultats)
    $('#trailer-results-container').on('click', '.lock-trailer-btn', function() {
        const videoData = {
            videoId: $(this).data('video-id'),
            title: $(this).data('video-title'),
            thumbnail: $(this).data('video-thumbnail'),
            channel: $(this).data('video-channel')
        };
        lockTrailer(videoData);
    });

    // Logique d'ajout manuel
    $('#add-manual-trailer-btn').on('click', function() {
        const url = $('#manual-trailer-url').val().trim();
        if (!url) return;

        fetch(`/api/agent/get_youtube_video_details?url=${encodeURIComponent(url)}`)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    $('#manual-trailer-preview').html(`<p class="text-danger">${data.error}</p>`).show();
                } else {
                    const previewHtml = `
                        <div class="d-flex align-items-center">
                            <img src="${data.thumbnail}" width="80" class="me-2 rounded">
                            <p class="mb-0 flex-grow-1">${data.title}</p>
                            <button class="btn btn-sm btn-success" id="lock-manual-trailer-btn" data-video-id="${data.videoId}" data-video-title="${data.title}" data-video-thumbnail="${data.thumbnail}" data-video-channel="${data.channel}">
                                <i class="bi bi-lock-fill"></i> Verrouiller
                            </button>
                        </div>`;
                    $('#manual-trailer-preview').html(previewHtml).show();
                }
            });
    });

    // Verrouiller une bande-annonce (depuis l'aperçu manuel)
    $('#manual-trailer-preview').on('click', '#lock-manual-trailer-btn', function() {
        const videoData = {
            videoId: $(this).data('video-id'),
            title: $(this).data('video-title'),
            thumbnail: $(this).data('video-thumbnail'),
            channel: $(this).data('video-channel')
        };
        lockTrailer(videoData);
    });

    function lockTrailer(videoData) {
        fetch(`/api/agent/lock_trailer/${currentMediaType}/${currentExternalId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ video_data: videoData })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'Trailer locked') {
                toastr.success('Bande-annonce verrouillée !');
                trailerSearchModal.hide();
                // Optionnel : rafraîchir l'icône du bouton qui a ouvert la modale
                 $(`.trailer-btn[data-trailer-id-key='${currentMediaType}_${currentExternalId}']`)
                    .removeClass('btn-danger btn-info')
                    .addClass('btn-success');
            } else {
                toastr.error(data.message || 'Erreur lors du verrouillage.');
            }
        });
    }

    // Ouvre la recherche autonome depuis le menu latéral
    $('#standalone-trailer-search-btn').on('click', function(e) {
        e.preventDefault();
        // Le HTML de cette modale existe déjà dans layout.html
        new bootstrap.Modal(document.getElementById('standalone-trailer-search-modal')).show();
    });

    // Gère la soumission du formulaire de recherche autonome
    $('#standalone-trailer-search-form').on('submit', function(e) {
        e.preventDefault();
        const query = $('#standalone-trailer-search-input').val().trim();
        const mediaType = $('input[name="standalone_media_type"]:checked').val();
        const resultsContainer = $('#standalone-trailer-search-results-container');
        if (!query) return;

        resultsContainer.html('<div class="text-center my-3"><div class="spinner-border"></div></div>');

        fetch(`/api/media/search?query=${encodeURIComponent(query)}&media_type=${mediaType}`)
            .then(response => response.json())
            .then(results => {
                resultsContainer.empty();
                if (results.length === 0) {
                    resultsContainer.html('<p class="text-center text-muted">Aucun résultat.</p>');
                    return;
                }
                results.forEach(item => {
                    const poster = item.poster_path ? `https://image.tmdb.org/t/p/w92${item.poster_path}` : 'https://via.placeholder.com/92x138.png?text=N/A';
                    const resultHtml = `
                        <div class="list-group-item bg-transparent text-white d-flex justify-content-between align-items-center">
                            <div class="d-flex align-items-center">
                                <img src="${poster}" class="me-3 rounded">
                                <div>
                                    <strong>${item.title}</strong> (${item.year})
                                </div>
                            </div>
                            <button class="btn btn-sm btn-outline-info open-trailer-search-from-standalone"
                                data-media-type="${mediaType}"
                                data-external-id="${item.external_ids.tmdb || item.external_ids.tvdb}"
                                data-title="${item.title}"
                                data-year="${item.year}">
                                <i class="bi bi-film"></i> Chercher BA
                            </button>
                        </div>`;
                    resultsContainer.append(resultHtml);
                });
            });
    });

     // Gère le clic pour ouvrir la recherche de BA depuis la recherche autonome
    $(document).on('click', '.open-trailer-search-from-standalone', function() {
        const data = $(this).data();
        $(document).trigger('openTrailerSearch', {
            mediaType: data.mediaType,
            externalId: data.externalId,
            title: data.title,
            year: data.year
        });
        bootstrap.Modal.getInstance(document.getElementById('standalone-trailer-search-modal')).hide();
    });

});

function playTrailer(videoId, title) {
    const playerModal = new bootstrap.Modal(document.getElementById('trailer-modal'));
    $('#trailerModalLabel').text('Bande-Annonce: ' + title);
    $('#trailer-modal .modal-body').html(`<div class="ratio ratio-16x9"><iframe src="https://www.youtube.com/embed/${videoId}?autoplay=1" allow="autoplay; encrypted-media" allowfullscreen></iframe></div>`);

    // Empêche la modale de recherche de se fermer en arrière-plan
    const searchModalEl = document.getElementById('trailer-search-modal');
    if (searchModalEl.classList.contains('show')) {
        $(searchModalEl).css('opacity', 0);
    }

    $('#trailer-modal').on('hidden.bs.modal', function () {
        $(this).find('.modal-body').empty(); // Vide l'iframe pour arrêter la vidéo
        if (searchModalEl.classList.contains('show')) {
            $(searchModalEl).css('opacity', 1);
        }
    });

    playerModal.show();
}
