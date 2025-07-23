// Fichier : app/static/js/search_logic.js (Version unifiée + Enrichissement)

$(document).ready(function() {
    console.log(">>>>>> SCRIPT UNIFIÉ 'search_logic.js' CHARGÉ (Recherche + Modale + Enrichissement) <<<<<<");

    const modalEl = $('#sonarrRadarrSearchModal');
    const modalBody = modalEl.find('.modal-body');

    // (Le code de la recherche principale reste identique)
    $('body').on('click', '#execute-prowlarr-search-btn', function() {
        const form = $('#search-form');
        const query = form.find('[name="query"]').val();
        if (!query) {
            alert("Veuillez entrer un terme à rechercher.");
            return;
        }
        const resultsContainer = $('#search-results-container');
        resultsContainer.html('<div class="text-center p-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2">Recherche en cours...</p></div>');
        const payload = {
            query: query,
            search_type: $('input[name="search_type"]:checked').val(),
            year: form.find('[name="year"]').val(),
            lang: form.find('[name="lang"]').val(),
            quality: $('#filterQuality').val(),
            codec: $('#filterCodec').val(),
            source: $('#filterSource').val()
        };
        console.log("Payload de recherche principale envoyé :", payload);
        fetch('/search/api/prowlarr/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => {
            if (!response.ok) throw new Error(`Erreur réseau: ${response.statusText}`);
            return response.json();
        })
        .then(data => {
            if (data.error) {
                resultsContainer.html(`<div class="alert alert-danger">${data.error}</div>`);
                return;
            }
            if (!data || data.length === 0) {
                resultsContainer.html('<div class="alert alert-info mt-3">Aucun résultat trouvé pour cette recherche avec les filtres actuels.</div>');
                return;
            }
            let resultsHtml = `<hr><h4 class="mb-3">Résultats pour "${payload.query}" (${data.length})</h4><ul class="list-group">`;
            data.forEach(result => {
                const sizeInGB = (result.size / 1024**3).toFixed(2);
                const seedersClass = result.seeders > 0 ? 'text-success' : 'text-danger';
                resultsHtml += `
                    <li class="list-group-item d-flex justify-content-between align-items-center flex-wrap">
                        <div class="me-auto" style="flex-basis: 60%; min-width: 300px;">
                            <strong>${result.title}</strong><br>
                            <small class="text-muted">
                                Indexer: ${result.indexer} | Taille: ${sizeInGB} GB | Seeders: <span class="${seedersClass}">${result.seeders}</span>
                            </small>
                        </div>
                        <div class="p-2" style="min-width: 150px; text-align: center;">
                            <button class="btn btn-sm btn-outline-info check-status-btn" data-guid="${result.guid}" data-title="${result.title}">Vérifier Statut</button>
                            <div class="spinner-border spinner-border-sm d-none" role="status"></div>
                        </div>
                        <div class="p-2">
                            <a href="#" class="btn btn-sm btn-success download-and-map-btn"
                               data-title="${result.title}" data-download-link="${result.downloadUrl}" data-guid="${result.guid}" data-indexer-id="${result.indexerId}">
                                <i class="fas fa-cogs"></i> & Mapper
                            </a>
                        </div>
                    </li>`;
            });
            resultsHtml += '</ul>';
            resultsContainer.html(resultsHtml);
        })
        .catch(error => {
            console.error("Erreur lors de la recherche Prowlarr:", error);
            resultsContainer.html(`<div class="alert alert-danger">Une erreur est survenue: ${error.message}</div>`);
        });
    });

    // (Le code d'ouverture de la modale reste identique)
    function displayResults(resultsData, mediaType) {
        const resultsContainer = modalBody.find('#lookup-results-container');
        let itemsHtml = '';
        if (resultsData && resultsData.length > 0) {
            itemsHtml = resultsData.map(item => {
                const bestMatchClass = item.is_best_match ? 'best-match' : '';
                const itemID = mediaType === 'tv' ? item.tvdbId : item.tmdbId;
                return `
                    <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center ${bestMatchClass}" data-result-item>
                        <span><strong>${item.title}</strong> (${item.year})</span>
                        <button class="btn btn-sm btn-outline-primary enrich-details-btn" data-media-id="${itemID}" data-media-type="${mediaType}">
                            Voir les détails
                        </button>
                    </div>
                `;
            }).join('');
        } else {
            itemsHtml = '<div class="alert alert-info mt-3">Aucun résultat trouvé. Essayez une recherche manuelle.</div>';
        }
        resultsContainer.html(`<div class="list-group list-group-flush">${itemsHtml}</div>`);
    }

    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseTitle = button.data('title');
        const mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';
        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        modalBody.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche des correspondances...</p></div>');
        new bootstrap.Modal(modalEl[0]).show();
        console.log(`Lookup pour: "${releaseTitle}", Type: "${mediaType}"`);
        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: releaseTitle, media_type: mediaType })
        })
        .then(response => response.json())
        .then(data => {
            const idPlaceholder = mediaType === 'tv' ? 'ID TVDB...' : 'ID TMDb...';
            const modalHtml = `
                <div data-media-type="${mediaType}">
                    <p class="text-muted small">Le meilleur résultat est surligné. Si ce n'est pas le bon, utilisez la recherche manuelle.</p>
                    <h6>Recherche manuelle par Titre</h6>
                    <div class="input-group mb-2">
                        <input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}">
                    </div>
                    <div class="text-center text-muted my-2 small">OU</div>
                    <h6>Recherche manuelle par ID</h6>
                    <div class="input-group mb-3">
                        <input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}">
                    </div>
                    <button id="unified-search-button" class="btn btn-primary w-100 mb-3">Rechercher manuellement</button>
                    <hr>
                    <div id="lookup-results-container"></div>
                </div>
            `;
            modalBody.html(modalHtml);
            displayResults(data.results, mediaType);
        });
    });

    modalBody.on('click', '#unified-search-button', function() {
        const button = $(this);
        const mediaType = button.closest('[data-media-type]').data('media-type');
        const titleQuery = $('#manual-search-input').val();
        const idQuery = $('#manual-id-input').val();
        let payload = { media_type: mediaType };
        if (idQuery) {
            payload.media_id = idQuery;
        } else if (titleQuery) {
            payload.term = titleQuery;
        } else {
            alert("Veuillez entrer un titre ou un ID.");
            return;
        }
        const resultsContainer = modalBody.find('#lookup-results-container');
        resultsContainer.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div></div>');
        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            displayResults(data.results, mediaType);
        });
    });

    // =================================================================
    // ### NOUVEAU GESTIONNAIRE : ENRICHISSEMENT DES DÉTAILS ###
    // =================================================================
    modalBody.on('click', '.enrich-details-btn', function() {
        const button = $(this);
        const container = button.closest('[data-result-item]');
        const mediaId = button.data('media-id');
        const mediaType = button.data('media-type');

        container.html('<div class="d-flex justify-content-center align-items-center p-3"><div class="spinner-border spinner-border-sm"></div></div>');

        fetch('/search/api/enrich/details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: mediaId, media_type: mediaType })
        })
        .then(response => response.json())
        .then(details => {
            if (details.error) {
                container.html(`<div class="text-danger">${details.error}</div>`);
                return;
            }
            const enrichedHtml = `
                <div class="card bg-dark text-white">
                    <div class="row g-0">
                        <div class="col-md-3">
                            <img src="${details.poster}" class="img-fluid rounded-start" alt="Poster">
                        </div>
                        <div class="col-md-9">
                            <div class="card-body">
                                <h5 class="card-title">${details.title} (${details.year})</h5>
                                <p class="card-text_small" style="font-size: 0.8rem;"><strong>Statut:</strong> ${details.status}</p>
                                <p class="card-text" style="max-height: 150px; overflow-y: auto;">${details.overview || 'Synopsis non disponible.'}</p>
                                <button class="btn btn-sm btn-primary confirm-mapping-btn" data-media-id="${details.id}">Choisir ce média</button>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            container.removeClass('list-group-item-action').html(enrichedHtml);
        })
        .catch(err => {
            container.html('<div class="text-danger">Erreur de communication.</div>');
            console.error("Erreur d'enrichissement:", err);
        });
    });
});
