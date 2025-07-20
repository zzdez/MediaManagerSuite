// Fichier : app/search_ui/static/search_ui/js/search_actions.js
// Version : Architecture Unifiée

$(document).ready(function() {
    console.log("Search actions (UNIFIED ARCHITECTURE) script chargé.");

    const modalEl = $('#sonarrRadarrSearchModal');
    const modalBody = modalEl.find('.modal-body');

    // --- Synchronisation du type de recherche avec le champ caché ---
    $('input[name="search_type"]').on('change', function() {
        $('#search-form-media-type').val($(this).val() === 'sonarr' ? 'tv' : 'movie');
    });

    // --- FONCTION UTILITAIRE POUR AFFICHER LES RÉSULTATS ---
    function displayResults(resultsData, mediaType) {
        const resultsContainer = modalBody.find('#lookup-results-container');
        let itemsHtml = '';
        if (resultsData && resultsData.length > 0) {
            itemsHtml = resultsData.map(item => {
                const bestMatchClass = item.is_best_match ? 'best-match' : '';
                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center ${bestMatchClass}">
                        <span><strong>${item.title}</strong> (${item.year})</span>
                        <button class="btn btn-sm btn-outline-primary enrich-details-btn" data-media-id="${item.tvdbId || item.tmdbId}" data-media-type="${mediaType}">
                            Voir les détails
                        </button>
                    </div>
                `;
            }).join('');
        } else {
            itemsHtml = '<div class="alert alert-info mt-3">Aucun résultat trouvé.</div>';
        }
        resultsContainer.html(`<div class="list-group list-group-flush">${itemsHtml}</div>`);
    }

// =================================================================
    // ### GESTIONNAIRE UNIQUE ET CORRECT POUR LA RECHERCHE PRINCIPALE ###
    // =================================================================
    $('#execute-prowlarr-search-btn').on('click', function() {
        const form = $('#search-form');
        const query = form.find('[name="query"]').val();
        if (!query) {
            alert("Veuillez entrer un terme à rechercher.");
            return;
        }

        const resultsContainer = $('#search-results-container');
        resultsContainer.html('<div class="text-center p-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2">Recherche en cours...</p></div>');

        // Construction du payload COMPLET et CORRECT
        const payload = {
            query: query,
            search_type: form.find('input[name="search_type"]:checked').val(), // Correction ici
            year: form.find('[name="year"]').val(),
            lang: form.find('[name="lang"]').val(),
            quality: $('#filterQuality').val(),
            codec: $('#filterCodec').val(),
            source: $('#filterSource').val()
        };

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


    // --- GESTIONNAIRE PRINCIPAL : OUVRE ET CONSTRUIT LA MODALE ---
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseTitle = button.data('title');
        const mediaType = $('#search-form [name="media_type"]').val();

        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        modalBody.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div></div>');
        new bootstrap.Modal(modalEl[0]).show();

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
                    <h6>Recherche par Titre</h6>
                    <div class="input-group mb-2">
                        <input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}">
                    </div>
                    <div class="text-center text-muted my-2 small">OU</div>
                    <h6>Recherche par ID</h6>
                    <div class="input-group mb-3">
                        <input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}">
                    </div>
                    <button id="unified-search-button" class="btn btn-primary w-100">Rechercher</button>
                    <hr>
                    <div id="lookup-results-container"></div>
                </div>
            `;
            modalBody.html(modalHtml);
            displayResults(data.results, mediaType);
        });
    });

    // --- GESTIONNAIRE DE LA RECHERCHE UNIFIÉE ---
    $('body').on('click', '#unified-search-button', function() {
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

    // --- AUTRES GESTIONNAIRES (Enrichissement, Sélection, etc.) ---
    // Ils devraient continuer à fonctionner car ils sont attachés au 'body'

});
