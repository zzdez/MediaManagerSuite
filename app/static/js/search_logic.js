// Fichier : app/static/js/search_logic.js

$(document).ready(function() {
    // CONTEXTE GLOBAL POUR LE PRE-MAPPING
    window.currentMediaContext = null;

    const modalEl = $('#sonarrRadarrSearchModal');
    const modalBody = modalEl.find('.modal-body');
    const TMDB_POSTER_BASE_URL = 'https://image.tmdb.org/t/p/w185';
    const searchPageContainer = $('#search-page-container');
    const mediaSearchUrl = searchPageContainer.data('media-search-url');

    // =================================================================
    // ### BLOC 1 : RECHERCHE DE MÉDIAS (FILMS/SÉRIES) - NOUVELLE IMPLEMENTATION ###
    // =================================================================

    let mediaSearchResults = [];

    function renderMediaResults(results, mediaType) {
        const resultsContainer = $('#media-results-container');
        resultsContainer.empty();

        if (!results || results.length === 0) {
            resultsContainer.html('<p class="mt-3">Aucun résultat trouvé.</p>');
            return;
        }

        const listGroup = $('<div class="list-group"></div>');
        results.forEach((item, index) => {
            const posterUrl = mediaType === 'movie' && item.poster
                ? `${TMDB_POSTER_BASE_URL}${item.poster}`
                : (item.poster || 'https://via.placeholder.com/185x278.png?text=No+Poster');

            const cardHtml = `
                <div class="list-group-item list-group-item-action" data-media-type="${mediaType}">
                    <div class="row g-3">
                        <div class="col-md-2 col-sm-3">
                            <img src="${posterUrl}" class="img-fluid rounded" alt="Poster de ${item.title}">
                        </div>
                        <div class="col-md-10 col-sm-9">
                            <h5 class="mb-1">${item.title} <span class="text-muted">(${item.year || 'N/A'})</span></h5>
                            <p class="mb-1 small">${item.overview ? item.overview.substring(0, 280) + (item.overview.length > 280 ? '...' : '') : 'Pas de synopsis disponible.'}</p>
                            <div class="mt-2">
                                <button class="btn btn-sm btn-outline-info search-trailer-btn"
                                        data-title="${item.title}"
                                        data-year="${item.year || ''}"
                                        data-media-type="${mediaType}">
                                    <i class="fas fa-video"></i> Bande-annonce
                                </button>
                                <button class="btn btn-sm btn-primary search-torrents-btn" data-result-index="${index}">
                                    <i class="fas fa-download"></i> Chercher les Torrents
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
            listGroup.append(cardHtml);
        });
        resultsContainer.append(listGroup);
    }

    function performMediaSearch() {
        window.currentMediaContext = null;

        const query = $('#media-search-input').val().trim();
        const mediaType = $('input[name="media_type"]:checked').val();
        const resultsContainer = $('#media-results-container');

        if (!query) {
            resultsContainer.html('<div class="alert alert-warning">Veuillez entrer un titre à rechercher.</div>');
            return;
        }

        resultsContainer.html('<div class="text-center p-5"><div class="spinner-border text-primary" role="status"></div></div>');

        if (!mediaSearchUrl) {
            resultsContainer.html('<div class="alert alert-danger">Erreur de configuration: URL de recherche de média non trouvée.</div>');
            return;
        }

        fetch(mediaSearchUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query, media_type: mediaType })
        })
        .then(response => {
            if (!response.ok) return response.json().then(err => { throw new Error(err.error || `Erreur HTTP ${response.status}`) });
            return response.json();
        })
        .then(data => {
            if (data.error) {
                resultsContainer.html(`<div class="alert alert-danger">${data.error}</div>`);
                return;
            }
            mediaSearchResults = data;
            renderMediaResults(data, mediaType);
        })
        .catch(error => {
            console.error('Erreur lors de la recherche de média:', error);
            resultsContainer.html(`<div class="alert alert-danger">Une erreur est survenue: ${error.message}</div>`);
        });
    }

    $('#execute-media-search-btn').on('click', performMediaSearch);
    $('#media-search-input').on('keypress', function(e) {
        if (e.which == 13) { e.preventDefault(); performMediaSearch(); }
    });

    // --- GESTION DES BANDES-ANNONCES DE LA PAGE DE RECHERCHE ---
    $('#media-results-container').on('click', '.search-trailer-btn', function() {
        const button = $(this);
        const title = button.data('title');
        const year = button.data('year');
        const mediaType = button.data('media-type');

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        const selectionModal = $('#trailer-selection-modal');
        $('#trailer-results-container').empty();
        $('#trailer-load-more-container').hide();

        // Stocke le contexte pour la recherche personnalisée (sans ratingKey)
        selectionModal.data({ 'title': title, 'year': year, 'mediaType': mediaType });

        bootstrap.Modal.getOrCreateInstance(selectionModal[0]).show();

        fetch('/api/agent/suggest_trailers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, year, media_type: mediaType })
        })
        .then(response => response.ok ? response.json() : response.json().then(err => Promise.reject(err)))
        .then(data => {
            if (data.success && data.results && data.results.length > 0) {
                // Utilise la fonction globale, sans afficher le verrou
                renderTrailerResults(data.results, { showLock: false });

                const loadMoreBtn = $('#load-more-trailers-btn');
                if (data.nextPageToken) {
                    loadMoreBtn.data('page-token', data.nextPageToken).data('query', data.query);
                    $('#trailer-load-more-container').show();
                }
            } else {
                renderTrailerResults([], { showLock: false });
            }
        })
        .catch(error => {
            console.error('Erreur lors de la recherche de la bande-annonce:', error);
            alert(`Une erreur technique est survenue : ${error.message || 'Erreur inconnue'}`);
            bootstrap.Modal.getInstance(selectionModal[0])?.hide();
        })
        .finally(() => {
            button.prop('disabled', false).html('<i class="fas fa-video"></i> Bande-annonce');
        });
    });

    $('#media-results-container').on('click', '.search-torrents-btn', function() {
        resetFilters(); // Réinitialiser les filtres pour la nouvelle recherche
        const resultIndex = $(this).data('result-index');
        const mediaData = mediaSearchResults[resultIndex];
        const mediaType = $(this).closest('[data-media-type]').data('media-type'); // 'movie' ou 'tv'

        window.currentMediaContext = { ...mediaData, media_type: mediaType };

        // Pré-remplir le champ de recherche de l'autre onglet
        $('#search-form input[name="query"]').val(mediaData.title);

        // Basculer vers l'onglet de recherche libre
        const freeSearchTab = new bootstrap.Tab($('#torrent-search-tab')[0]);
        freeSearchTab.show();

        const payload = {
            query: mediaData.title,
            search_type: mediaType === 'movie' ? 'radarr' : 'sonarr'
        };

        executeProwlarrSearch(payload); // Appel direct de la fonction partagée
    });

    // =================================================================
    // ### BLOC 2 : RECHERCHE LIBRE (PROWLARR) ET STATUT ###
    // =================================================================

    function updateFilterVisibility() {
        const searchType = $('input[name="search_type"]:checked').val();

        // Filtres spécifiques aux séries
        const seriesOnlyFilters = $('#filterSeason, #filterEpisode');
        // Filtre spécifique aux films
        const movieOnlyFilters = $('#filterYear');
        // Le filtre "Type de Pack" est maintenant toujours visible
        // const packTypeFilter = $('#filterPackType');

        if (searchType === 'sonarr') { // Séries
            seriesOnlyFilters.closest('.col-md-3, .col-md-2').show();
            movieOnlyFilters.closest('.col-md-2').hide();
        } else { // 'radarr' pour les Films
            seriesOnlyFilters.closest('.col-md-3, .col-md-2').hide();
            movieOnlyFilters.closest('.col-md-2').show();
        }
    }

    let prowlarrResultsCache = []; // Cache pour les résultats actuels

    function populateFilters(results, filterOptions) {
        // Helper to populate a select dropdown
        const populateSelect = (selector, options) => {
            const select = $(selector);
            select.html('<option value="" selected>Tous</option>');
            if (options && options.length > 0) {
                select.append(options.sort().map(opt => `<option value="${opt}">${opt}</option>`).join(''));
            }
        };

        // Populate from configured lists
        populateSelect('#filterQuality', filterOptions.quality);
        populateSelect('#filterCodec', filterOptions.codec);
        populateSelect('#filterSource', filterOptions.source);
        populateSelect('#filterReleaseGroup', filterOptions.release_group);

        // Populate languages dynamically from results
        const languages = new Set();
        results.forEach(result => {
            if (result.language) {
                String(result.language).split(',').forEach(l => {
                    const lang = l.trim();
                    if(lang) languages.add(lang);
                });
            }
        });
        populateSelect('#filterLang', [...languages]);
    }

    function resetFilters() {
        $('#filterPackType, #filterQuality, #filterCodec, #filterSource, #filterLang, #filterReleaseGroup').val('');
        $('#filterYear, #filterSeason, #filterEpisode').val('');
        // Déclencher un changement pour que la liste se mette à jour et affiche tout
        applyClientSideFilters();
    }

    function applyClientSideFilters() {
        const activeFilters = {
            quality: ($('#filterQuality').val() || '').toLowerCase(),
            lang: ($('#filterLang').val() || '').toLowerCase(),
            source: ($('#filterSource').val() || '').toLowerCase(),
            codec: ($('#filterCodec').val() || '').toLowerCase(),
            releaseGroup: ($('#filterReleaseGroup').val() || '').toLowerCase(),
            year: ($('#filterYear').val() || ''),
            packType: ($('#filterPackType').val() || ''),
            season: ($('#filterSeason').val() || ''),
            episode: ($('#filterEpisode').val() || '')
        };

        let visibleCount = 0;
        $('.release-item').each(function() {
            const item = $(this);
            const data = item.data('parsed') || {}; // LIRE L'OBJET DE DONNÉES

            let show = true;

            // Filtres sur les chaînes de caractères
            if (activeFilters.quality && (data.quality || '').toLowerCase() !== activeFilters.quality) show = false;
            if (activeFilters.source && (data.source || '').toLowerCase() !== activeFilters.source) show = false;
            if (activeFilters.codec && (data.codec || '').toLowerCase() !== activeFilters.codec) show = false;
            if (activeFilters.releaseGroup && (data.release_group || '').toLowerCase() !== activeFilters.releaseGroup) show = false;
            if (activeFilters.lang && !(data.language || '').toLowerCase().includes(activeFilters.lang)) show = false;

            // Filtres sur les nombres
            if (activeFilters.year && data.year != activeFilters.year) show = false;
            if (activeFilters.season && data.season != activeFilters.season) show = false;
            if (activeFilters.episode && data.episode != activeFilters.episode) show = false;

            // Filtre intelligent "Type de Pack"
            if (activeFilters.packType) {
                if (activeFilters.packType === 'episode' && !data.is_episode) show = false;
                if (activeFilters.packType === 'season' && !data.is_season_pack) show = false;
                if (activeFilters.packType === 'collection' && !data.is_collection) show = false;
                // Le filtre "special" peut être combiné, donc on ne l'exclut pas des autres types
                if (activeFilters.packType === 'special' && !data.is_special) show = false;
            }

            // Appliquer le résultat
            item.toggleClass('d-none', !show);
            if (show) visibleCount++;
        });

        // Mettre à jour le compteur
        $('#results-count').text(visibleCount);
    }


    function executeProwlarrSearch(payload) {
        const resultsContainer = $('#search-results-container');
        resultsContainer.html('<div class="text-center p-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2">Recherche en cours...</p></div>');

        $('#advancedFilters').find('select, input').prop('disabled', true);

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
            // Correction: Utiliser un fallback `{}` pour éviter les erreurs si filter_options est manquant.
            const results = data.results || [];
            const filterOptions = data.filter_options || {};
            prowlarrResultsCache = results;

            if (data.error) {
                resultsContainer.html(`<div class="alert alert-danger">${data.error}</div>`);
                return;
            }

            if (results.length === 0) {
                resultsContainer.html('<div class="alert alert-info mt-3">Aucun résultat trouvé.</div>');
                $('#advancedFilters').collapse('hide');
                return;
            }

            populateFilters(results, filterOptions);

            resultsContainer.empty();
            const header = $(`<hr><h4 class="mb-3">Résultats pour "${payload.query}" (<span id="results-count">${results.length}</span> / <span>${results.length}</span>)</h4>`);
            resultsContainer.append(header);

            const listGroup = $('<ul class="list-group"></ul>');
            results.forEach(result => {
                const sizeInGB = (result.size / 1024**3).toFixed(2);
                const seedersClass = result.seeders > 0 ? 'text-success' : 'text-danger';

                const itemContentHtml = `
                    <div class="me-auto" style="flex-basis: 60%; min-width: 300px;">
                        <strong></strong>
                        <br>
                        <small class="text-muted">
                            Indexer: ${result.indexer} | Taille: ${sizeInGB} GB | Seeders: <span class="${seedersClass}">${result.seeders}</span>
                        </small>
                    </div>
                    <div class="p-2" style="min-width: 150px; text-align: center;">
                        <button class="btn btn-sm btn-outline-info check-status-btn">Vérifier Statut</button>
                        <div class="spinner-border spinner-border-sm d-none" role="status"></div>
                    </div>
                    <div class="p-2">
                        <a href="#" class="btn btn-sm btn-success download-and-map-btn">
                            <i class="fas fa-cogs"></i> & Mapper
                        </a>
                    </div>`;

                const listItem = $(`<li class="list-group-item d-flex justify-content-between align-items-center flex-wrap release-item"></li>`);
                listItem.html(itemContentHtml);

                listItem.data('parsed', result);

                listItem.find('strong').text(result.title);
                listItem.find('.check-status-btn').attr({ 'data-guid': result.guid, 'data-title': result.title });
                listItem.find('.download-and-map-btn').attr({
                    'data-title': result.title,
                    'data-download-link': result.downloadUrl,
                    'data-guid': result.guid,
                    'data-indexer-id': result.indexerId
                });

                listGroup.append(listItem);
            });
            resultsContainer.append(listGroup);

            // Correction: Appliquer le filtre par défaut APRÈS le rendu des résultats
            const langSelect = $('#filterLang');
            if (langSelect.find('option[value="fr"]').length > 0) {
                langSelect.val('fr');
            }
            applyClientSideFilters();

            $('#advancedFilters').find('select, input').prop('disabled', false);
            $('#advancedFilters').collapse('show');
        })
        .catch(error => {
            console.error("Erreur lors de la recherche Prowlarr:", error);
            resultsContainer.html(`<div class="alert alert-danger">Une erreur est survenue: ${error.message}</div>`);
        });
    }

    $('#advancedFilters').on('change', 'select, input', function() {
        applyClientSideFilters();
    });

    $('body').on('click', '#execute-prowlarr-search-btn', function() {
        window.currentMediaContext = null;
        resetFilters();

        const form = $('#search-form');
        const payload = {
            query: form.find('[name="query"]').val(),
            search_type: form.find('[name="search_type"]:checked').val()
        };

        if (!payload.query) {
            alert("Veuillez entrer un terme à rechercher.");
            return;
        }

        executeProwlarrSearch(payload);
    });

    $('body').on('click', '.check-status-btn', function() {
        const button = $(this);
        const guid = button.data('guid');
        const title = button.data('title');
        const statusContainer = button.parent();
        button.addClass('d-none');
        statusContainer.find('.spinner-border').removeClass('d-none');
        fetch('/search/check_media_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guid: guid, title: title })
        })
        .then(response => {
            if (!response.ok) { throw new Error(`Erreur réseau: ${response.statusText}`); }
            return response.json();
        })
        .then(data => {
            let statusHtml = '';
            if (data.error) { statusHtml = `<span class="text-danger small">${data.error}</span>`; }
            else { statusHtml = `<span class="text-success small"><strong>Statut :</strong> ${data.status}</span>`; }
            statusContainer.html(statusHtml);
        })
        .catch(error => {
            console.error('Erreur lors de la vérification du statut:', error);
            statusContainer.html(`<span class="text-danger small">Erreur.</span>`);
            setTimeout(() => {
                button.removeClass('d-none');
                statusContainer.find('.spinner-border').addClass('d-none');
                statusContainer.html(button);
            }, 2000);
        });
    });

    // =================================================================
    // ### BLOC 3 : LOGIQUE DE LA MODALE "& MAPPER" ###
    // =================================================================

    function displayResults(resultsData, mediaType) {
        const resultsContainer = modalBody.find('#lookup-results-container');
        let itemsHtml = '';
        if (resultsData && resultsData.length > 0) {
            itemsHtml = resultsData.map(item => {
                const bestMatchClass = item.is_best_match ? 'best-match' : '';
                const externalId = mediaType === 'tv' ? item.tvdbId : item.tmdbId;
                const mediaExists = item.id && item.id > 0;
                const buttonHtml = mediaExists ?
                    `<button class="btn btn-sm btn-outline-primary enrich-details-btn" data-media-id="${externalId}" data-media-type="${mediaType}">Voir les détails</button>` :
                    `<button class="btn btn-sm btn-outline-success add-and-enrich-btn" data-ext-id="${externalId}" data-title="${item.title}" data-year="${item.year}" data-media-type="${mediaType}">Ajouter & Voir les détails</button>`;
                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center ${bestMatchClass}" data-result-item>
                        <div><strong>${item.title}</strong> (${item.year})${!mediaExists ? '<span class="badge bg-info ms-2">Nouveau</span>' : ''}</div>
                        ${buttonHtml}
                    </div>`;
            }).join('');
        } else {
            itemsHtml = '<div class="alert alert-info mt-3">Aucun résultat trouvé. Essayez une recherche manuelle.</div>';
        }
        resultsContainer.html(`<div class="list-group list-group-flush">${itemsHtml}</div>`);
    }

    function populateAndShowAddItemView(mediaData) {
        const mediaType = mediaData.media_type;
        const instanceType = mediaType === 'tv' ? 'sonarr' : 'radarr';
        const externalId = mediaData.id;
        const title = mediaData.title;

        const optionsContainer = modalBody.find('#add-item-options-container');
        const lookupContainer = modalBody.find('#initial-lookup-content');
        const finalButton = modalEl.find('#confirm-add-and-map-btn');
        const detailsContainer = optionsContainer.find('#new-media-details-container');

        optionsContainer.data({ 'external-id': externalId, 'media-type': mediaType, 'title': title });
        lookupContainer.hide();
        optionsContainer.removeClass('d-none');
        finalButton.removeClass('d-none').prop('disabled', true); // On désactive le bouton par défaut
        detailsContainer.html('<div class="d-flex justify-content-center align-items-center p-3"><div class="spinner-border spinner-border-sm"></div><span class="ms-2">Chargement des détails...</span></div>');
        optionsContainer.find('select').empty().prop('disabled', true).html('<option>Chargement...</option>');
        optionsContainer.find('#add-item-error-container').empty();
        optionsContainer.find('#language-profile-select').parent().toggle(instanceType === 'sonarr');

        const enrichPromise = fetch('/search/api/enrich/details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: externalId, media_type: mediaType, is_new: true })
        }).then(res => res.ok ? res.json() : Promise.reject('enrichDetails'));

        let rootFolderUrl = instanceType === 'radarr' ? '/seedbox/api/get-radarr-rootfolders' : '/seedbox/api/get-sonarr-rootfolders';
        let qualityProfileUrl = instanceType === 'radarr' ? '/seedbox/api/get-radarr-qualityprofiles' : '/seedbox/api/get-sonarr-qualityprofiles';

        const optionsPromise = Promise.all([
            fetch(rootFolderUrl).then(res => res.ok ? res.json() : Promise.reject('rootFolders')),
            fetch(qualityProfileUrl).then(res => res.ok ? res.json() : Promise.reject('qualityProfiles'))
        ]);

        Promise.all([enrichPromise, optionsPromise]).then(([details, options]) => {
            if (details.error) {
                detailsContainer.html(`<div class="text-danger">${details.error}</div>`);
            } else {
                const enrichedHtml = `
                    <div class="card bg-dark text-white">
                        <div class="row g-0">
                            <div class="col-md-3">
                                <img src="${details.poster}" class="img-fluid rounded-start" alt="Poster">
                            </div>
                            <div class="col-md-9">
                                <div class="card-body">
                                    <h5 class="card-title">${details.title} (${details.year})</h5>
                                    <p class="card-text small"><strong>Statut:</strong> ${details.status}</p>
                                    <p class="card-text small" style="max-height: 100px; overflow-y: auto;">${details.overview || 'Synopsis non disponible.'}</p>
                                <button class="btn btn-sm btn-secondary back-to-lookup-btn mt-2">Retour à la liste</button>
                                </div>
                            </div>
                        </div>
                    </div>`;
                detailsContainer.html(enrichedHtml);
            }
            const [rootFolders, qualityProfiles] = options;
            const rootFolderSelect = $('#root-folder-select').empty();
            if (rootFolders && rootFolders.length > 0) {
                rootFolders.forEach(folder => rootFolderSelect.append(new Option(folder.path, folder.id)));
                rootFolderSelect.prop('disabled', false);
            } else {
                rootFolderSelect.html('<option>Aucun dossier trouvé</option>');
            }
            const qualityProfileSelect = $('#quality-profile-select').empty();
            if (qualityProfiles && qualityProfiles.length > 0) {
                qualityProfiles.forEach(profile => qualityProfileSelect.append(new Option(profile.name, profile.id)));
                qualityProfileSelect.prop('disabled', false);
            } else {
                qualityProfileSelect.html('<option>Aucun profil trouvé</option>');
            }

            if ($('#root-folder-select').val() && $('#quality-profile-select').val()) {
                finalButton.prop('disabled', false);
            }
        }).catch(error => {
            console.error("Erreur lors de la récupération des données pour l'ajout:", error);
            optionsContainer.find('#add-item-error-container').text("Une erreur critique est survenue. Veuillez vérifier les logs.");
        });
    }

function executeFinalMapping(payload) {

    const modalInstance = bootstrap.Modal.getInstance(modalEl[0]);
    if (modalInstance) {
        modalBody.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Envoi au téléchargement...</p></div>');
    }

    fetch('/search/download-and-map', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            if(modalInstance) modalInstance.hide();
            alert("Succès ! La release a été envoyée au téléchargement et sera mappée.");
        } else {
            if(modalInstance) {
                modalBody.html(`<div class="alert alert-danger">${data.message || 'Une erreur inconnue est survenue.'}</div>`);
            } else {
                alert("Erreur : " + (data.message || 'Une erreur inconnue est survenue.'));
            }
        }
    })
    .catch(error => {
        console.error("Erreur lors du mapping final:", error);
        if(modalInstance) {
            modalBody.html(`<div class="alert alert-danger">Une erreur de communication est survenue.</div>`);
        } else {
            alert("Une erreur de communication est survenue.");
        }
    });
}

    $('body').off('click', '.download-and-map-btn').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseDetails = {
            title: button.data('title'),
            downloadLink: button.data('download-link'),
            guid: button.data('guid'),
            indexerId: button.data('indexer-id')
        };
        modalEl.data('release-details', releaseDetails);
        modalEl.find('.modal-title').text(`Mapper : ${releaseDetails.title}`);
        new bootstrap.Modal(modalEl[0]).show();

        if (window.currentMediaContext) {
            const context = window.currentMediaContext;
            console.log("FLUX PRÉ-MAPPING : Contexte trouvé. Vérification de l'existence...", context);

            fetch('/search/api/media/check_existence', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ media_id: context.id, media_type: context.media_type })
            })
            .then(res => res.json())
            .then(existenceData => {
                const releaseDetails = modalEl.data('release-details');

                if (existenceData.exists) {
                    console.log("FLUX PRÉ-MAPPING (EXISTANT) : Média trouvé dans *Arr. Mapping direct.");
                    const finalPayload = {
                        releaseName: releaseDetails.title,
                        downloadLink: releaseDetails.downloadLink,
                        guid: releaseDetails.guid,
                        indexerId: releaseDetails.indexerId,
                        instanceType: context.media_type,
                        mediaId: context.id
                    };
                    executeFinalMapping(finalPayload);

                    const modalInstance = bootstrap.Modal.getInstance(modalEl[0]);
                    if(modalInstance) modalInstance.hide();

                } else {
                    console.log("FLUX PRÉ-MAPPING (NOUVEAU) : Média non trouvé. Affichage de la vue d'ajout.");
                    populateAndShowAddItemView(context);
                }
            })
            .catch(error => {
                console.error("Erreur lors de la vérification de l'existence du média:", error);
                alert("Une erreur est survenue lors de la communication avec le serveur.");
            });

        } else {
            console.log("FLUX CLASSIQUE : Aucun contexte, lancement du lookup.");
            const mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';
            modalBody.find('#add-item-options-container').addClass('d-none');
            modalEl.find('#confirm-add-and-map-btn').addClass('d-none');
            const lookupContent = modalBody.find('#initial-lookup-content').removeClass('d-none').show();
            lookupContent.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche des correspondances...</p></div>');
            fetch('/search/api/search/lookup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ term: releaseDetails.title, media_type: mediaType })
            })
            .then(response => response.json())
            .then(data => {
                const idPlaceholder = mediaType === 'tv' ? 'ID TVDB...' : 'ID TMDb...';
                const modalHtml = `
                    <div data-media-type="${mediaType}">
                        <p class="text-muted small">Le meilleur résultat est surligné. Si ce n'est pas le bon, utilisez la recherche manuelle.</p>
                        <h6>Recherche manuelle par Titre</h6>
                        <div class="input-group mb-2"><input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}"></div>
                        <div class="text-center text-muted my-2 small">OU</div>
                        <h6>Recherche manuelle par ID</h6>
                        <div class="input-group mb-3"><input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}"></div>
                        <button id="unified-search-button" class="btn btn-primary w-100 mb-3">Rechercher manuellement</button>
                        <hr>
                        <div id="lookup-results-container"></div>
                    </div>`;
                lookupContent.html(modalHtml);
                displayResults(data.results, mediaType);
            });
        }
    });

    $('body').on('click', '#sonarrRadarrSearchModal .add-and-enrich-btn', function() {
        populateAndShowAddItemView({
            media_type: $(this).data('media-type'),
            id: $(this).data('ext-id'),
            title: $(this).data('title'),
            year: $(this).data('year')
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal .back-to-lookup-btn', function() {
        const releaseDetails = modalEl.data('release-details');
        if (!releaseDetails) { return; }
        const releaseTitle = releaseDetails.title;
        const mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';
        modalBody.find('#add-item-options-container').addClass('d-none');
        modalEl.find('#confirm-add-and-map-btn').addClass('d-none');
        const lookupContent = modalBody.find('#initial-lookup-content').removeClass('d-none').show();
        lookupContent.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Retour à la liste...</p></div>');
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
                    <p class="text-muted small">Le meilleur résultat est surligné.</p>
                    <h6>Recherche manuelle par Titre</h6>
                    <div class="input-group mb-2"><input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}"></div>
                    <div class="text-center text-muted my-2 small">OU</div>
                    <h6>Recherche manuelle par ID</h6>
                    <div class="input-group mb-3"><input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}"></div>
                    <button id="unified-search-button" class="btn btn-primary w-100 mb-3">Rechercher manuellement</button>
                    <hr>
                    <div id="lookup-results-container"></div>
                </div>`;
            lookupContent.html(modalHtml);
            displayResults(data.results, mediaType);
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal #unified-search-button', function() {
        const button = $(this);
        const mediaType = button.closest('[data-media-type]').data('media-type');
        const titleQuery = $('#manual-search-input').val();
        const idQuery = $('#manual-id-input').val();
        let payload = { media_type: mediaType };
        if (idQuery) { payload.media_id = idQuery; }
        else if (titleQuery) { payload.term = titleQuery; }
        else { alert("Veuillez entrer un titre ou un ID."); return; }
        const resultsContainer = $('#lookup-results-container');
        resultsContainer.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div></div>');
        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => { displayResults(data.results, mediaType); });
    });

    $('body').on('change', '#root-folder-select, #quality-profile-select', function() {
        const rootFolder = $('#root-folder-select').val();
        const qualityProfile = $('#quality-profile-select').val();
        const finalButton = $('#confirm-add-and-map-btn');

        if (rootFolder && qualityProfile) {
            finalButton.prop('disabled', false);
        } else {
            finalButton.prop('disabled', true);
        }
    });

    $('body').off('click', '#confirm-add-and-map-btn').on('click', '#confirm-add-and-map-btn', function() {
        const button = $(this);
        const optionsContainer = modalBody.find('#add-item-options-container');
        const errorContainer = optionsContainer.find('#add-item-error-container');
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Ajout en cours...');
        errorContainer.empty();
        const releaseDetails = modalEl.data('release-details');
        const mediaType = optionsContainer.data('media-type');
        const instanceType = mediaType === 'tv' ? 'sonarr' : 'radarr';
        const addPayload = {
            app_type: instanceType,
            external_id: optionsContainer.data('external-id'),
            title: optionsContainer.data('title'),
            root_folder_path: $('#root-folder-select').find('option:selected').text(),
            quality_profile_id: $('#quality-profile-select').val(),
            searchForMovie: $('#search-on-add-check').is(':checked')
        };
        fetch('/seedbox/api/add-arr-item-and-get-id', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(addPayload)
        })
        .then(response => {
            if (!response.ok) { return response.json().then(err => Promise.reject(err)); }
            return response.json();
        })
        .then(data => {
            if (data.error || !data.new_media_id) { throw new Error(data.error || "L'ID du nouveau média n'a pas été retourné."); }
            button.html('<span class="spinner-border spinner-border-sm"></span> Envoi au téléchargement...');
            const finalPayload = {
                releaseName: releaseDetails.title,
                downloadLink: releaseDetails.downloadLink,
                guid: releaseDetails.guid,
                indexerId: releaseDetails.indexerId,
                instanceType: mediaType,
                mediaId: data.new_media_id
            };
            return fetch('/search/download-and-map', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(finalPayload)
            });
        })
        .then(response => response.json())
        .then(data => {
            const modalInstance = bootstrap.Modal.getInstance(modalEl[0]);
            if (data.status === 'success') {
                if(modalInstance) modalInstance.hide();
                alert("Succès ! Le média a été ajouté et la release a été envoyée au téléchargement.");
            } else {
                throw new Error(data.message || "Erreur lors de l'envoi au téléchargement.");
            }
        })
        .catch(error => {
            const errorMessage = error.message || "Une erreur inconnue est survenue.";
            errorContainer.text(errorMessage);
            button.prop('disabled', false).text('Ajouter, Télécharger & Mapper');
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal .enrich-details-btn', function() {
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
                        <div class="col-md-3"><img src="${details.poster}" class="img-fluid rounded-start" alt="Poster"></div>
                        <div class="col-md-9"><div class="card-body">
                            <h5 class="card-title">${details.title} (${details.year})</h5>
                            <p class="card-text small"><strong>Statut:</strong> ${details.status}</p>
                            <p class="card-text small" style="max-height: 150px; overflow-y: auto;">${details.overview || 'Synopsis non disponible.'}</p>
                            <button class="btn btn-sm btn-primary confirm-mapping-btn me-2" data-media-id="${details.id}">Choisir ce média</button>
                            <button class="btn btn-sm btn-secondary back-to-lookup-btn">Retour à la liste</button>
                        </div></div>
                    </div>
                </div>`;
            container.removeClass('list-group-item d-flex justify-content-between align-items-center').html(enrichedHtml);
        })
        .catch(err => {
            container.html('<div class="text-danger">Erreur de communication.</div>');
            console.error("Erreur d'enrichissement:", err);
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal .confirm-mapping-btn', function() {
        const button = $(this);
        const selectedMediaId = button.data('media-id');
        const mediaType = button.closest('[data-media-type]').data('media-type');
        const releaseDetails = modalEl.data('release-details');
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Confirmation...');
        const finalPayload = {
            releaseName: releaseDetails.title,
            downloadLink: releaseDetails.downloadLink,
            guid: releaseDetails.guid,
            indexerId: releaseDetails.indexerId,
            instanceType: mediaType,
            mediaId: selectedMediaId
        };
        fetch('/search/download-and-map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(finalPayload)
        })
        .then(response => response.json())
        .then(data => {
            const modalInstance = bootstrap.Modal.getInstance(modalEl[0]);
            if (data.status === 'success') {
                if(modalInstance) modalInstance.hide();
                alert("Succès ! La release a été envoyée au téléchargement et sera mappée.");
            } else {
                alert("Erreur : " + data.message);
                button.prop('disabled', false).text('Choisir ce média');
            }
        })
        .catch(error => {
            console.error("Erreur lors du mapping final:", error);
            alert("Une erreur de communication est survenue.");
            button.prop('disabled', false).text('Choisir ce média');
        });
    });

    // Gestion de la visibilité des filtres intelligents
    $('input[name="search_type"]').on('change', updateFilterVisibility);

    // Appel initial pour définir le bon état au chargement de la page
    updateFilterVisibility();
});
