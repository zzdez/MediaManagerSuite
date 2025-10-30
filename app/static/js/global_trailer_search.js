// Fichier : app/static/js/global_trailer_search.js
// Nouvelle version simplifiée utilisant le TrailerManager et les API unifiées.

/**
 * Affiche les résultats de la recherche de bande-annonce dans le conteneur.
 * @param {Array} results - La liste des vidéos YouTube à afficher.
 * @param {Object} options - Options d'affichage.
 * @param {Object|null} options.lockedVideoData - Les données de la vidéo actuellement verrouillée.
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
        // Si verrouillé: bouton vert (état actuel) avec icone "unlock" (action possible).
        // Si non verrouillé: bouton rouge (action possible) avec icone "lock".
        const btnClass = isLocked ? 'btn-success' : 'btn-outline-danger';
        const btnTitle = isLocked ? 'Déverrouiller cette bande-annonce' : 'Verrouiller cette bande-annonce';
        const iconClass = isLocked ? 'bi-unlock-fill' : 'bi-lock-fill';

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
 * Fonction centrale pour récupérer et afficher les bandes-annonces.
 * @param {string} mediaType - 'tmdb' ou 'tvdb'.
 * @param {string} externalId - L'ID du média.
 * @param {string} title - Le titre du média.
 * @param {string|null} year - L'année du média.
 * @param {string|null} pageToken - Le token pour la pagination.
 * @param {boolean} forceRefresh - Si true, ignore le cache du backend.
 */
function fetchAndRenderTrailers(mediaType, externalId, title, year = null, pageToken = null, forceRefresh = false) {
    const resultsContainer = $('#trailer-results-container');
    const loadMoreContainer = $('#trailer-load-more-container');
    const loadMoreBtn = $('#load-more-trailers-btn');
    const selectionModal = $('#trailer-selection-modal');

    selectionModal.data({ mediaType, externalId, title, year });

    if (!pageToken) {
        resultsContainer.html('<div class="text-center"><div class="spinner-border"></div></div>');
    }
    loadMoreContainer.hide();

    let apiUrl = `/api/agent/get_trailer_info?media_type=${mediaType}&external_id=${externalId}&title=${encodeURIComponent(title)}`;
    if (year) apiUrl += `&year=${year}`;
    if (pageToken) apiUrl += `&page_token=${pageToken}`;
    if (forceRefresh) apiUrl += `&force_refresh=true`;

    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            if (!pageToken) resultsContainer.empty();

            if (data.status === 'locked') {
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
    // Gère le clic sur "Afficher plus"
    $(document).on('click', '#load-more-trailers-btn', function() {
        const button = $(this);
        const selectionModal = $('#trailer-selection-modal');
        const { mediaType, externalId, title, year } = selectionModal.data();
        const pageToken = button.data('page-token');

        if (!mediaType || !externalId || !pageToken || !title) return;

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');
        fetchAndRenderTrailers(mediaType, externalId, title, year, pageToken, false);
    });

    // Gère la recherche personnalisée dans la modale
    $(document).on('click', '#trailer-custom-search-btn', function() {
        const selectionModal = $('#trailer-selection-modal');
        let { mediaType, externalId, year } = selectionModal.data();
        const newTitle = $('#trailer-custom-search-input').val().trim();

        if (!mediaType || !externalId || !newTitle) {
            alert("Le nouveau titre ne peut pas être vide.");
            return;
        }
        fetchAndRenderTrailers(mediaType, externalId, newTitle, year, null, true);
    });

    // Gère le clic sur le bouton pour effacer le cache
    $(document).on('click', '#clear-trailer-cache-btn', function() {
        const button = $(this);
        const selectionModal = $('#trailer-selection-modal');
        const { mediaType, externalId } = selectionModal.data();

        if (!mediaType || !externalId) return;

        if (!confirm("Êtes-vous sûr de vouloir effacer tous les résultats de recherche et le verrouillage pour ce média ?")) {
            return;
        }

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        fetch('/api/agent/clear_trailer_cache', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_type: mediaType, external_id: externalId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                toastr.success("Cache effacé.");
                $('#trailer-results-container').html('<p class="text-center text-muted">Les résultats ont été effacés. Vous pouvez lancer une nouvelle recherche.</p>');
                $('#trailer-load-more-container').hide();
            } else {
                toastr.error('Erreur: ' + (data.message || 'Une erreur inconnue est survenue.'));
            }
        })
        .catch(error => {
            console.error('Erreur technique lors de l_effacement du cache:', error);
            toastr.error('Une erreur technique est survenue.');
        })
        .finally(() => {
            button.prop('disabled', false).html('<i class="bi bi-trash"></i>');
        });
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
            video_data: videoData
        };
        if (isLocked) delete payload.video_data;

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                fetchAndRenderTrailers(mediaType, externalId, title, year);
            } else {
                alert('Erreur: ' + (data.message || 'Une erreur inconnue est survenue.'));
                const iconClass = isLocked ? 'bi-unlock-fill' : 'bi-lock-fill';
                button.prop('disabled', false).html(`<i class="bi ${iconClass}"></i>`);
            }
        })
        .catch(error => {
            console.error('Erreur technique lors du (dé)verrouillage:', error);
            alert('Une erreur technique est survenue.');
            const iconClass = isLocked ? 'bi-unlock-fill' : 'bi-lock-fill';
            button.prop('disabled', false).html(`<i class="bi ${iconClass}"></i>`);
        });
    });

    // --- LOGIQUE POUR L'AJOUT MANUEL ---
    $(document).on('click', '#toggle-manual-trailer-btn', function() {
        $('#manual-trailer-input-container').slideToggle();
    });

    $(document).on('click', '#preview-manual-trailer-btn', function() {
        const url = $('#manual-trailer-url-input').val().trim();
        if (!url) return;

        const videoIdMatch = url.match(/(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})/);
        const videoId = videoIdMatch ? videoIdMatch[1] : null;

        if (!videoId) {
            alert("URL YouTube invalide. Veuillez coller l'URL complète de la vidéo.");
            return;
        }

        const button = $(this);
        const resultsContainer = $('#trailer-results-container');
        const originalButtonHtml = button.html();
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        fetch(`/api/agent/get_youtube_video_details?video_id=${videoId}`)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    resultsContainer.empty();
                    const result = data.details;
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
                            <button class="btn btn-sm btn-outline-danger lock-trailer-btn" title="Verrouiller cette bande-annonce"
                                    data-video-id="${result.videoId}"
                                    data-is-locked="false"
                                    data-video-title="${result.title}"
                                    data-video-thumbnail="${result.thumbnail}"
                                    data-video-channel="${result.channel}">
                                <i class="bi bi-lock-fill"></i> Verrouiller
                            </button>
                        </div>
                    `;
                    resultsContainer.html(resultHtml);
                } else {
                    alert('Erreur: ' + (data.message || 'Impossible de récupérer les détails de la vidéo.'));
                }
            })
            .catch(error => {
                console.error("Erreur lors de la prévisualisation manuelle:", error);
                alert("Une erreur de communication est survenue.");
            })
            .finally(() => {
                button.prop('disabled', false).html(originalButtonHtml);
            });
    });

    // --- LE RESTE DU FICHIER (LECTEUR VIDÉO, DÉCLENCHEURS GLOBAUX, MODALE AUTONOME) ---
    // (Cette partie reste inchangée)

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

    $('#trailer-modal').on('hidden.bs.modal', function () {
        const playerModal = $(this);
        playerModal.find('.modal-body').empty();
        const sourceModalId = playerModal.data('source-modal');
        if (sourceModalId) {
            const sourceModal = bootstrap.Modal.getInstance(document.getElementById(sourceModalId));
            if (sourceModal) sourceModal.show();
            playerModal.removeData('source-modal');
        }
    });

    $(document).on('openTrailerSearch', function(event, { mediaType, externalId, title, year, sourceModalId }) {
        const selectionModal = $('#trailer-selection-modal');
        const modalInstance = bootstrap.Modal.getOrCreateInstance(selectionModal[0]);

        if (sourceModalId) selectionModal.data('source-modal-id', sourceModalId);

        $('#trailer-results-container').empty();
        $('#trailer-load-more-container').hide();
        $('#trailer-selection-modal-label').text(`Bande-annonce pour : ${title}`);

        fetchAndRenderTrailers(mediaType, externalId, title, year);
        modalInstance.show();
    });

    $('#trailer-selection-modal').on('hidden.bs.modal', function () {
        const selectionModal = $(this);
        const sourceModalId = selectionModal.data('source-modal-id');
        if (sourceModalId) {
            const sourceModalEl = document.getElementById(sourceModalId);
            const sourceModalInstance = bootstrap.Modal.getInstance(sourceModalEl);
            if (sourceModalInstance) sourceModalInstance.show();
            selectionModal.removeData('source-modal-id');
        }
    });

    $('#standalone-trailer-search-btn').on('click', function(e) {
        e.preventDefault();
        const searchModal = new bootstrap.Modal(document.getElementById('standalone-trailer-search-modal'));
        searchModal.show();
    });

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
        .then(data => renderStandaloneResults(data, mediaType))
        .catch(error => {
            console.error('Erreur lors de la recherche de média autonome:', error);
            resultsContainer.html('<p class="text-danger">Erreur de communication.</p>');
        });
    });

    function renderStandaloneResults(results, mediaType) {
        const resultsContainer = $('#standalone-trailer-search-results-container');
        resultsContainer.empty();

        if (!results || results.length === 0) {
            resultsContainer.html('<p class="text-muted text-center">Aucun résultat trouvé.</p>');
            return;
        }

        const TMDB_POSTER_BASE_URL = 'https://image.tmdb.org/t/p/w185';
        const listGroup = $('<div class="list-group list-group-flush"></div>');

        results.forEach(item => {
            const posterUrl = (mediaType === 'movie' && item.poster)
                ? `${TMDB_POSTER_BASE_URL}${item.poster}`
                : (item.poster || 'https://via.placeholder.com/185x278.png?text=Affiche+non+disponible');

            let trailerBtnClass = 'btn-outline-danger';
            if (item.trailer_status === 'LOCKED') trailerBtnClass = 'btn-outline-success';
            else if (item.trailer_status === 'UNLOCKED') trailerBtnClass = 'btn-outline-primary';

            const placeholderId = `dashboard-placeholder-${mediaType}-${item.id}`;

            const itemHtml = `
                <div class="list-group-item bg-dark text-white p-3">
                    <div class="row g-3">
                        <div class="col-3">
                            <img src="${posterUrl}" class="img-fluid rounded" alt="Poster de ${item.title}">
                        </div>
                        <div class="col-9 d-flex flex-column">
                            <div>
                                <h6 class="mb-1">${item.title} <span class="text-white-50">(${item.year || 'N/A'})</span></h6>
                                <p class="mb-2 small text-white-50" style="max-height: 80px; overflow-y: auto;">
                                    ${item.overview ? item.overview.substring(0, 150) + (item.overview.length > 150 ? '...' : '') : 'Pas de synopsis.'}
                                </p>
                            </div>
                            <div id="${placeholderId}" class="mt-auto mb-2 dashboard-container">
                                <div class="text-center text-muted small"><div class="spinner-border spinner-border-sm"></div></div>
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

        results.forEach(item => {
            const placeholderId = `dashboard-placeholder-${mediaType}-${item.id}`;
            fetchAndRenderDashboard(placeholderId, mediaType, item.id);
        });
    }

    function fetchAndRenderDashboard(placeholderId, mediaType, externalId) {
        const placeholder = $(`#${placeholderId}`);
        fetch(`/api/agent/media/details/${mediaType}/${externalId}`)
            .then(response => {
                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                return response.json();
            })
            .then(data => {
                if (data.status === 'success') {
                    placeholder.html(formatDashboard(data.details, mediaType));
                } else {
                    placeholder.html('<p class="text-warning small text-center mb-0">Détails indisponibles.</p>');
                }
            })
            .catch(error => {
                console.error('Error fetching dashboard:', error);
                placeholder.html('<p class="text-danger small text-center mb-0">Erreur.</p>');
            });
    }

    function formatDashboard(details, mediaType) {
        let content = '<ul class="list-unstyled mb-0 small text-white-50">';
        const prod = details.production_status;
        if (prod && prod.status) {
            let statusText = prod.status === 'Ended' ? 'Terminée' : (prod.status === 'Returning Series' ? 'En cours' : prod.status);
            let badgeClass = prod.status === 'Ended' ? 'bg-danger' : 'bg-success';
            content += `<li><strong>Statut:</strong> <span class="badge ${badgeClass}">${statusText}</span>`;
            if (mediaType === 'tv' && prod.total_seasons) {
                content += ` <small>(${prod.total_seasons} S / ${prod.total_episodes} Ep)</small>`;
            }
            content += `</li>`;
        }
        const arr = mediaType === 'tv' ? details.sonarr_status : details.radarr_status;
        if (arr && arr.present) {
            let arrName = mediaType === 'tv' ? 'Sonarr' : 'Radarr';
            let fileInfo = '';
            if (mediaType === 'tv') fileInfo = `(${arr.episodes_file_count}/${arr.episodes_count} fichiers)`;
            else if (arr.has_file) fileInfo = '(avec fichier)';
            content += `<li><strong>${arrName}:</strong> <span class="text-success">Présent</span> <small class="text-muted">${fileInfo}</small></li>`;
        }
        const plex = details.plex_status;
        if (plex && plex.present) {
            let plexText = `<strong>Plex:</strong> <span class="text-info">Présent</span>`;
            if (plex.physical_presence) {
                let watchStatus = [];
                if (plex.is_watched) watchStatus.push('Vu Intégralement');
                else if (plex.watched_episodes && plex.watched_episodes !== '0/0') watchStatus.push(`Vus: ${plex.watched_episodes}`);
                if (plex.seen_via_tag) watchStatus.push('Archivé');
                if (watchStatus.length > 0) plexText += ` <small class="text-warning">(${watchStatus.join(', ')})</small>`;
            } else {
                plexText += ' <small class="text-muted">(métadonnées)</small>';
            }
            content += `<li>${plexText}</li>`;
        }
        content += '</ul>';
        return content;
    }

    $(document).on('click', '.open-trailer-search-from-standalone', function() {
        const data = $(this).data();
        const standaloneModalEl = document.getElementById('standalone-trailer-search-modal');
        const standaloneModalInstance = bootstrap.Modal.getInstance(standaloneModalEl);
        if (standaloneModalInstance) standaloneModalInstance.hide();

        $(document).trigger('openTrailerSearch', {
            mediaType: data.mediaType,
            externalId: data.externalId,
            title: data.title,
            year: data.year,
            sourceModalId: 'standalone-trailer-search-modal'
        });
    });
});
