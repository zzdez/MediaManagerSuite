$(document).ready(function() {
    console.log(">>>>>> SEARCH LOGIC V3 - RECONSTRUCTION <<<<<<");

    // =================================================================
    // ### VARIABLES GLOBALES ET DE CONTEXTE ###
    // =================================================================
    let preSelectedMediaForMapping = null;

    // =================================================================
    // ### SECTION 1 : ONGLET "RECHERCHE PAR MÉDIA" ###
    // =================================================================

    // 1A : Clic sur le bouton "Rechercher le Média"
    $('body').on('click', '#execute-media-search-btn', function() {
        const term = $('#media-search-input').val();
        const mediaType = $('input[name="media_type"]:checked').val();
        if (!term) { alert('Veuillez entrer un titre.'); return; }

        const resultsContainer = $('#media-results-container');
        resultsContainer.html('<div class="text-center p-4"><div class="spinner-border"></div></div>');
        $('#torrent-results-for-media-container').empty();
        preSelectedMediaForMapping = null; // Réinitialiser le contexte

        fetch('/search/api/media/find', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: term, media_type: mediaType })
        })
        .then(response => response.json())
        .then(data => {
            let resultsHtml = '<h5>Résultats de la recherche de média :</h5>';
            if (!data || data.length === 0) {
                resultsHtml += '<div class="alert alert-info">Aucun média trouvé.</div>';
            } else {
                resultsHtml += '<div class="list-group list-group-flush">';
                data.forEach(media => {
                    const mediaId = media.tmdbId || media.tvdb_id || media.id;
                    resultsHtml += `
                        <div class="list-group-item" data-media-id="${mediaId}" data-media-type="${mediaType}" data-title="${media.title}" data-year="${media.year}">
                            <div class="row align-items-center">
                                <div class="col-auto">
                                    <img src="${media.poster_url || 'https://via.placeholder.com/50x75'}" style="width: 50px; height: 75px; object-fit: cover; border-radius: 4px;" alt="Poster"/>
                                </div>
                                <div class="col">
                                    <strong>${media.title}</strong> (${media.year})
                                </div>
                                <div class="col-auto">
                                    <button class="btn btn-sm btn-outline-primary enrich-details-btn">
                                        <i class="fas fa-info-circle"></i> Voir les détails
                                    </button>
                                </div>
                            </div>
                        </div>
                    `;
                });
                resultsHtml += '</div>';
            }
            resultsContainer.html(resultsHtml);
        });
    });

    // 1B : Clic sur le bouton "Voir les détails" (logique partagée)
    $('body').on('click', '.enrich-details-btn', function() {
        const button = $(this);
        const container = button.closest('.list-group-item');
        const originalHtml = container.html();
        const mediaId = container.data('media-id');
        const mediaType = container.data('media-type');

        container.html('<div class="d-flex justify-content-center align-items-center p-3"><div class="spinner-border spinner-border-sm"></div></div>');

        fetch('/search/api/enrich/details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: mediaId, media_type: mediaType })
        })
        .then(response => response.json())
        .then(details => {
            const cardHtml = `
                <div class="card enriched-card">
                    <div class="row g-0">
                        <div class="col-md-2 text-center align-self-center">
                            <img src="${details.poster || '...'}" class="img-fluid rounded" style="max-width: 80px;" alt="Poster">
                        </div>
                        <div class="col-md-10">
                            <div class="card-body py-2">
                                <h6 class="card-title mb-1">${details.title} (${details.year})</h6>
                                <p class="card-text small" style="max-height: 100px; overflow-y: auto;">${details.overview || '...'}</p>
                                <button class="btn btn-sm btn-success search-torrents-for-media-btn">✓ Sélectionner & Chercher</button>
                                <button class="btn btn-sm btn-outline-secondary back-to-list-btn">Retour</button>
                            </div>
                        </div>
                    </div>
                </div>`;
            container.html(cardHtml).data('original-html', originalHtml);
        });
    });

    // 1C : Clic sur le bouton "Retour"
    $('body').on('click', '.back-to-list-btn', function() {
        const container = $(this).closest('.list-group-item');
        container.html(container.data('original-html'));
    });

    // 1D : Clic sur "Sélectionner & Chercher"
    $('body').on('click', '.search-torrents-for-media-btn', function() {
        const container = $(this).closest('.list-group-item');

        preSelectedMediaForMapping = {
            mediaId: container.data('media-id'),
            mediaType: container.data('media-type'),
            title: container.data('title')
        };

        $('#search-form input[name="query"]').val(container.data('title'));
        $('#search-form input[name="year"]').val(container.data('year'));
        new bootstrap.Tab(document.getElementById('torrent-search-tab')).show();
        $('#execute-prowlarr-search-btn').click();
    });

    // =================================================================
    // ### SECTION 2 : ONGLET "RECHERCHE LIBRE" ###
    // =================================================================

    // 2A : La recherche Prowlarr principale (votre code existant, légèrement adapté)
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

    // =================================================================
    // ### SECTION 3 : LOGIQUE DE LA MODALE DE MAPPING ###
    // =================================================================

    // 3A : Clic sur le bouton "& Mapper"
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const modalEl = $('#sonarrRadarrSearchModal');
        const modalBody = modalEl.find('.modal-body');
        const modalTitle = modalEl.find('.modal-title');
        const confirmBtn = modalEl.find('#confirm-add-and-map-btn');

        modalTitle.text(`Mapper : ${button.data('title')}`);
        new bootstrap.Modal(modalEl[0]).show();

        if (preSelectedMediaForMapping) {
            // CAS 1: Pré-mapping automatique !
            modalBody.html('<div class="text-center p-4"><div class="spinner-border"></div><p>Chargement des détails...</p></div>');

            fetch('/search/api/enrich/details', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(preSelectedMediaForMapping)
            })
            .then(response => response.json())
            .then(details => {
                const cardHtml = `
                    <div class="card enriched-card">
                        <div class="row g-0">
                            <div class="col-md-3 text-center align-self-center">
                                <img src="${details.poster || 'https://via.placeholder.com/100x150'}" class="img-fluid rounded" style="max-width: 100px;" alt="Poster">
                            </div>
                            <div class="col-md-9">
                                <div class="card-body">
                                    <h5 class="card-title">${details.title} (${details.year})</h5>
                                    <p class="card-text small" style="max-height: 150px; overflow-y: auto;">${details.overview || 'Synopsis non disponible.'}</p>
                                    <p class="text-success small mt-2"><strong>Ce média a été automatiquement sélectionné.</strong></p>
                                </div>
                            </div>
                        </div>
                    </div>`;
                modalBody.html(cardHtml);

                // The confirm button is for the final download and map action
                confirmBtn.text('Télécharger & Mapper').removeClass('d-none').prop('disabled', false);

                // Store all necessary data on the confirm button for the final step
                confirmBtn.data('media-id', preSelectedMediaForMapping.mediaId);
                confirmBtn.data('media-type', preSelectedMediaForMapping.mediaType);
                confirmBtn.data('release-title', button.data('title'));
                confirmBtn.data('download-link', button.data('download-link'));
                confirmBtn.data('guid', button.data('guid'));
                confirmBtn.data('indexer-id', button.data('indexer-id'));
            });
            preSelectedMediaForMapping = null; // Nettoyer
        } else {
            // CAS 2: Pas de pré-mapping, on lance la recherche manuelle
            const releaseTitle = button.data('title');
            const mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';

            const lookupContent = modalBody.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche des correspondances...</p></div>').find('#initial-lookup-content');
            if (lookupContent.length === 0) {
                modalBody.html('<div id="initial-lookup-content" class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche des correspondances...</p></div>');
            }

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
                        <div class="input-group mb-2"><input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}"></div>
                        <div class="text-center text-muted my-2 small">OU</div>
                        <h6>Recherche manuelle par ID</h6>
                        <div class="input-group mb-3"><input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}"></div>
                        <button id="unified-search-button" class="btn btn-primary w-100 mb-3">Rechercher manuellement</button>
                        <hr>
                        <div id="lookup-results-container"></div>
                    </div>`;
                modalBody.html(modalHtml);
                // Assuming displayResults function exists and works as before
                displayResults(data.results, mediaType);
            });
        }
    });

    // ... (collez ici les autres gestionnaires de la modale : #unified-search-button, la sélection finale, et la confirmation finale)

    function displayResults(resultsData, mediaType) {
        const modalBody = $('#sonarrRadarrSearchModal .modal-body');
        const resultsContainer = modalBody.find('#lookup-results-container');
        let itemsHtml = '';
        if (resultsData && resultsData.length > 0) {
            itemsHtml = resultsData.map(item => {
                const bestMatchClass = item.is_best_match ? 'best-match' : '';
                const externalId = mediaType === 'tv' ? item.tvdbId : item.tmdbId;
                const mediaExists = item.id && item.id > 0;
                const buttonHtml = mediaExists ?
                    `<button class="btn btn-sm btn-outline-primary enrich-details-btn"
                             data-media-id="${externalId}"
                             data-media-type="${mediaType}">
                        Voir les détails
                     </button>` :
                    `<button class="btn btn-sm btn-outline-success add-and-enrich-btn"
                             data-ext-id="${externalId}"
                             data-title="${item.title}"
                             data-year="${item.year}"
                             data-media-type="${mediaType}">
                        Ajouter & Voir les détails
                     </button>`;
                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center ${bestMatchClass}" data-result-item>
                        <div>
                            <strong>${item.title}</strong> (${item.year})
                            ${!mediaExists ? '<span class="badge bg-info ms-2">Nouveau</span>' : ''}
                        </div>
                        ${buttonHtml}
                    </div>
                `;
            }).join('');
        } else {
            itemsHtml = '<div class="alert alert-info mt-3">Aucun résultat trouvé. Essayez une recherche manuelle.</div>';
        }
        resultsContainer.html(`<div class="list-group list-group-flush">${itemsHtml}</div>`);
    }

    $('body').on('click', '#sonarrRadarrSearchModal .add-and-enrich-btn', function() {
        const button = $(this);
        const mediaType = button.data('media-type');
        const instanceType = mediaType === 'tv' ? 'sonarr' : 'radarr';
        const externalId = button.data('ext-id');
        const title = button.data('title');
        const modalBody = $('#sonarrRadarrSearchModal .modal-body');
        const optionsContainer = modalBody.find('#add-item-options-container');
        const lookupContainer = modalBody.find('#initial-lookup-content');
        const finalButton = $('#confirm-add-and-map-btn');
        const detailsContainer = optionsContainer.find('#new-media-details-container');

        optionsContainer.data('external-id', externalId);
        optionsContainer.data('media-type', mediaType);
        optionsContainer.data('title', title);

        lookupContainer.hide();
        optionsContainer.removeClass('d-none');
        finalButton.removeClass('d-none').text('Ajouter, Télécharger & Mapper');
        detailsContainer.html('<div class="d-flex justify-content-center align-items-center p-3"><div class="spinner-border spinner-border-sm"></div><span class="ms-2">Chargement...</span></div>');
        optionsContainer.find('select').empty().prop('disabled', true).html('<option>Chargement...</option>');
        optionsContainer.find('#add-item-error-container').empty();

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
                            <div class="col-md-3"><img src="${details.poster}" class="img-fluid rounded-start" alt="Poster"></div>
                            <div class="col-md-9"><div class="card-body">
                                <h5 class="card-title">${details.title} (${details.year})</h5>
                                <p class="card-text small">${details.overview || ''}</p>
                            </div></div>
                        </div>
                    </div>`;
                detailsContainer.html(enrichedHtml);
            }

            const [rootFolders, qualityProfiles] = options;
            const rootFolderSelect = $('#root-folder-select');
            if (rootFolders && rootFolders.length > 0) {
                rootFolders.forEach(folder => rootFolderSelect.append(new Option(folder.path, folder.id)));
                rootFolderSelect.prop('disabled', false);
            }

            const qualityProfileSelect = $('#quality-profile-select');
            if (qualityProfiles && qualityProfiles.length > 0) {
                qualityProfiles.forEach(profile => qualityProfileSelect.append(new Option(profile.name, profile.id)));
                qualityProfileSelect.prop('disabled', false);
            }
        }).catch(error => {
            optionsContainer.find('#add-item-error-container').text("Erreur de récupération des options.");
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
        const modalBody = $('#sonarrRadarrSearchModal .modal-body');
        const optionsContainer = modalBody.find('#add-item-options-container');
        const errorContainer = optionsContainer.find('#add-item-error-container');

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Traitement...');
        if (errorContainer) errorContainer.empty();

        // This is a new "add then map" flow
        if (optionsContainer.length > 0 && optionsContainer.data('external-id')) {
            const releaseDetails = $('#sonarrRadarrSearchModal').data('release-details');
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
            .then(response => response.ok ? response.json() : response.json().then(err => Promise.reject(err)))
            .then(data => {
                if (data.error || !data.new_media_id) throw new Error(data.error || "L'ID du nouveau média n'a pas été retourné.");
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
                const modalInstance = bootstrap.Modal.getInstance(document.getElementById('sonarrRadarrSearchModal'));
                if (data.status === 'success') {
                    if (modalInstance) modalInstance.hide();
                    alert("Succès ! Le média a été ajouté et la release a été envoyée au téléchargement.");
                } else {
                    throw new Error(data.message || "Erreur lors de l'envoi au téléchargement.");
                }
            })
            .catch(error => {
                if (errorContainer) errorContainer.text(error.message || "Une erreur inconnue est survenue.");
                button.prop('disabled', false).text('Ajouter, Télécharger & Mapper');
            });
        } else {
            // This is a direct "map to existing" flow (e.g., from pre-mapping)
            const finalPayload = {
                releaseName: button.data('release-title'),
                downloadLink: button.data('download-link'),
                guid: button.data('guid'),
                indexerId: button.data('indexer-id'),
                instanceType: button.data('media-type'),
                mediaId: button.data('media-id')
            };
            fetch('/search/download-and-map', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(finalPayload)
            })
            .then(response => response.json())
            .then(data => {
                const modalInstance = bootstrap.Modal.getInstance(document.getElementById('sonarrRadarrSearchModal'));
                if (data.status === 'success') {
                    if (modalInstance) modalInstance.hide();
                    alert("Succès ! La release a été envoyée au téléchargement et sera mappée.");
                } else {
                    throw new Error(data.message || "Erreur lors de l'envoi au téléchargement.");
                }
            })
            .catch(error => {
                alert("Erreur: " + error.message);
                button.prop('disabled', false).text('Télécharger & Mapper');
            });
        }
    });
});
