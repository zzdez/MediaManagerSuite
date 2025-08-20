// Fichier : app/static/js/search_logic.js (Version avec Pré-Mapping Intégré)

$(document).ready(function() {
    console.log(">>>>>> SCRIPT UNIFIÉ 'search_logic.js' CHARGÉ (V3 - Pre-Mapping) <<<<<<");

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
                                <button class="btn btn-sm btn-outline-info" disabled>
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
        console.log("Contexte de pré-mapping réinitialisé par la recherche de média.");

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

    $('#media-results-container').on('click', '.search-torrents-btn', function() {
        const resultIndex = $(this).data('result-index');
        const mediaData = mediaSearchResults[resultIndex];
        const mediaType = $(this).closest('[data-media-type]').data('media-type');

        window.currentMediaContext = { ...mediaData, media_type: mediaType };
        console.log("Contexte média défini pour le pré-mapping :", window.currentMediaContext);

        $('#search-form input[name="query"]').val(mediaData.title);
        if (mediaType === 'movie') {
            $('#search_type_radarr').prop('checked', true);
        } else {
            $('#search_type_sonarr').prop('checked', true);
        }

        const freeSearchTab = new bootstrap.Tab($('#torrent-search-tab')[0]);
        freeSearchTab.show();

        const form = $('#search-form');
        const payload = {
            query: mediaData.title, // Utilise le titre exact du média
            search_type: form.find('[name="search_type"]:checked').val(),
            year: form.find('[name="year"]').val(),
            lang: form.find('[name="lang"]').val(),
            quality: $('#filterQuality').val(),
            codec: $('#filterCodec').val(),
            source: $('#filterSource').val()
        };

        executeProwlarrSearch(payload); // Appel direct de la fonction partagée
    });

    // =================================================================
    // ### BLOC 2 : RECHERCHE LIBRE (PROWLARR) ET STATUT ###
    // =================================================================

    function executeProwlarrSearch(payload) {
        const resultsContainer = $('#search-results-container');
        resultsContainer.html('<div class="text-center p-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2">Recherche en cours...</p></div>');

        console.log("Payload de recherche Prowlarr envoyé :", payload);
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
    }

    // Gestionnaire pour la RECHERCHE LIBRE (initiée par l'utilisateur)
    $('body').on('click', '#execute-prowlarr-search-btn', function() {
        console.log("Recherche libre manuelle initiée. Réinitialisation du contexte.");
        window.currentMediaContext = null; // Contexte effacé car c'est une nouvelle recherche manuelle

        const form = $('#search-form');
        const payload = {
            query: form.find('[name="query"]').val(),
            search_type: form.find('[name="search_type"]:checked').val(),
            year: form.find('[name="year"]').val(),
            lang: form.find('[name="lang"]').val(),
            quality: $('#filterQuality').val(),
            codec: $('#filterCodec').val(),
            source: $('#filterSource').val()
        };

        if (!payload.query) {
            alert("Veuillez entrer un terme à rechercher.");
            return;
        }

        executeProwlarrSearch(payload); // Appel de la fonction partagée
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
        finalButton.removeClass('d-none');
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
        }).catch(error => {
            console.error("Erreur lors de la récupération des données pour l'ajout:", error);
            optionsContainer.find('#add-item-error-container').text("Une erreur critique est survenue. Veuillez vérifier les logs.");
        });
    }

function executeFinalMapping(payload) {
    console.log("Exécution du mapping final avec le payload :", payload);

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
            // --- DÉBUT DE LA LOGIQUE D'AIGUILLAGE ---
            const context = window.currentMediaContext;
            console.log("FLUX PRÉ-MAPPING : Contexte trouvé. Vérification de l'existence...", context);

            // On utilise la route de vérification de l'existence du média
            fetch('/search/api/media/check_existence', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ media_id: context.id, media_type: context.media_type })
            })
            .then(res => res.json())
            .then(existenceData => {
                const releaseDetails = modalEl.data('release-details');

                if (existenceData.exists) {
                    // OUI : Le média existe, on mappe directement
                    console.log("FLUX PRÉ-MAPPING (EXISTANT) : Média trouvé dans *Arr. Mapping direct.");
                    const finalPayload = {
                        releaseName: releaseDetails.title,
                        downloadLink: releaseDetails.downloadLink,
                        guid: releaseDetails.guid,
                        indexerId: releaseDetails.indexerId,
                        instanceType: context.media_type,
                        mediaId: context.id // On envoie l'ID externe (TVDB/TMDb)
                    };
                    executeFinalMapping(finalPayload);

                    const modalInstance = bootstrap.Modal.getInstance(modalEl[0]);
                    if(modalInstance) modalInstance.hide();

                } else {
                    // NON : Le média est nouveau, on affiche la vue d'ajout
                    console.log("FLUX PRÉ-MAPPING (NOUVEAU) : Média non trouvé. Affichage de la vue d'ajout.");
                    populateAndShowAddItemView(context);
                }
            })
            .catch(error => {
                console.error("Erreur lors de la vérification de l'existence du média:", error);
                alert("Une erreur est survenue lors de la communication avec le serveur.");
            });
            // --- FIN DE LA LOGIQUE D'AIGUILLAGE ---

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

    $('body').on('click', '#confirm-add-and-map-btn', function() {
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
});
