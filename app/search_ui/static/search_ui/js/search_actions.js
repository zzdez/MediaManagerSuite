// Fichier : app/search_ui/static/search_ui/js/search_actions.js
// Version : Architecture Unifiée

$(document).ready(function() {
    console.log("Search actions (UNIFIED ARCHITECTURE) script chargé.");

    const modalEl = $('#sonarrRadarrSearchModal');
    const modalBody = modalEl.find('.modal-body');

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
    $('body').on('click', '#execute-prowlarr-search-btn', function() {
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
            search_type: form.find('[name="search_type"]:checked').val(), // La clé du problème
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

// --- DÉBUT DU NOUVEAU BLOC POUR LA RECHERCHE PAR MÉDIA ---

// Étape 1: Le clic sur le bouton "Rechercher le Média"
$('body').on('click', '#execute-media-search-btn', function() {
    const term = $('#media-search-input').val();
    const mediaType = $('input[name="media_type"]:checked').val();
    if (!term) { alert('Veuillez entrer un titre.'); return; }

    const resultsContainer = $('#media-results-container');
    resultsContainer.html('<div class="text-center p-4"><div class="spinner-border"></div></div>');
    $('#torrent-results-for-media-container').empty(); // Vider les anciens résultats de torrents

    fetch('/api/media/find', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ term: term, media_type: mediaType })
    })
    .then(response => response.json())
    .then(data => {
        let resultsHtml = '<h5>Résultats de la recherche de média :</h5><div class="list-group">';
        if (!data || data.length === 0) {
            resultsHtml += '<div class="list-group-item">Aucun média trouvé.</div>';
        } else {
            data.forEach(media => {
                const posterUrl = media.poster_url || media.poster || 'https://via.placeholder.com/50x75';
                resultsHtml += `
                    <div class="list-group-item">
                        <div class="row align-items-center">
                            <div class="col-auto">
                                <img src="${posterUrl}" style="width: 50px;"/>
                            </div>
                            <div class="col">
                                <strong>${media.title}</strong> (${media.year})
                            </div>
                            <div class="col-auto">
                                <button class="btn btn-sm btn-primary search-torrents-for-media-btn" data-title="${media.title}" data-year="${media.year}">
                                    <i class="fas fa-search"></i> Chercher les Torrents
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            });
        }
        resultsHtml += '</div>';
        resultsContainer.html(resultsHtml);
    });
});

// Étape 2: Le clic sur le bouton "Chercher les Torrents"
$('body').on('click', '.search-torrents-for-media-btn', function() {
    const title = $(this).data('title');
    const year = $(this).data('year');
    const torrentResultsContainer = $('#torrent-results-for-media-container');

    // On simule un clic sur le bouton de l'autre onglet après avoir rempli les champs
    $('#search-form input[name="query"]').val(title);
    $('#search-form input[name="year"]').val(year);

    // On fait défiler jusqu'aux résultats et on lance la recherche
    $('html, body').animate({ scrollTop: torrentResultsContainer.offset().top - 20 }, 500);

    // **RÉUTILISATION INTELLIGENTE**
    // On déclenche manuellement le clic sur le bouton de recherche de l'onglet existant
    // Mais on doit d'abord cloner et rediriger les résultats
    const originalContainer = $('#search-results-container');
    originalContainer.html(''); // Vider le conteneur original pour éviter les doublons
    $('#execute-prowlarr-search-btn').click(); // Déclenche la recherche existante

    // Rediriger les résultats
    const observer = new MutationObserver(function(mutations, me) {
        if (originalContainer.html().length > 0) {
            torrentResultsContainer.html(originalContainer.html());
            originalContainer.html(''); // Nettoyer après
            me.disconnect(); // Arrêter d'observer
        }
    });
    observer.observe(originalContainer[0], { childList: true, subtree: true });
});

// --- FIN DU NOUVEAU BLOC ---
});
