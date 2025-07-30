// Fichier : app/static/js/search_logic.js (Version avec event delegation corrigée)

$(document).ready(function() {
    console.log(">>>>>> SCRIPT UNIFIÉ 'search_logic.js' CHARGÉ (Recherche + Modale + Enrichissement V2) <<<<<<");

    const modalEl = $('#sonarrRadarrSearchModal');
    const modalBody = modalEl.find('.modal-body');

    // =================================================================
    // ### PARTIE 1 : GESTIONNAIRE DE RECHERCHE PRINCIPALE (PROWLARR) ###
    // (Ce code est correct et inchangé)
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

    // ### NOUVEAU BLOC : GESTIONNAIRE POUR "VÉRIFIER STATUT" (CORRECTIF BUG) ###
    $('body').on('click', '.check-status-btn', function() {
        const button = $(this);
        const guid = button.data('guid');
        const title = button.data('title'); // Récupéré pour un éventuel logging
        const statusContainer = button.parent(); // Le div qui contient le bouton et le spinner

        // Désactiver le bouton et afficher le spinner
        button.addClass('d-none'); // On cache le bouton
        statusContainer.find('.spinner-border').removeClass('d-none'); // On montre le spinner

        fetch('/search/check_media_status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ guid: guid, title: title })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`Erreur réseau: ${response.statusText}`);
            }
            return response.json();
        })
        .then(data => {
            let statusHtml = '';
            if (data.error) {
                statusHtml = `<span class="text-danger small">${data.error}</span>`;
            } else {
                statusHtml = `<span class="text-success small"><strong>Statut :</strong> ${data.status}</span>`;
            }
            // On remplace tout le contenu du conteneur (bouton et spinner) par le statut
            statusContainer.html(statusHtml);
        })
        .catch(error => {
            console.error('Erreur lors de la vérification du statut:', error);
            // En cas d'erreur, on remet le bouton pour que l'utilisateur puisse réessayer
            statusContainer.html(`<span class="text-danger small">Erreur.</span>`);
            setTimeout(() => {
                button.removeClass('d-none');
                statusContainer.find('.spinner-border').addClass('d-none');
                statusContainer.html(button); // Rétablit le bouton
            }, 2000);
        });
    });


    // =================================================================
    // ### PARTIE 2 : LOGIQUE DE LA MODALE "& MAPPER" ###
    // (Section avec les corrections d'event delegation)
    // =================================================================

    function displayResults(resultsData, mediaType) {
        const resultsContainer = modalBody.find('#lookup-results-container');
        let itemsHtml = '';
        if (resultsData && resultsData.length > 0) {
            itemsHtml = resultsData.map(item => {
                const bestMatchClass = item.is_best_match ? 'best-match' : '';
                const externalId = mediaType === 'tv' ? item.tvdbId : item.tmdbId;

                // On vérifie si le média existe déjà dans la librairie (id > 0)
                const mediaExists = item.id && item.id > 0;

                const buttonHtml = mediaExists ?
                    // Média EXISTANT : bouton standard pour enrichir les détails.
                    // IMPORTANT : data-media-id doit être l'ID EXTERNE pour l'appel d'enrichissement.
                    `<button class="btn btn-sm btn-outline-primary enrich-details-btn"
                             data-media-id="${externalId}"
                             data-media-type="${mediaType}">
                        Voir les détails
                     </button>` :
                    // NOUVEAU média : bouton pour l'ajouter.
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

    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        // On stocke les informations essentielles de la release directement sur l'élément de la modale
        modalEl.data('release-details', {
            title: button.data('title'),
            downloadLink: button.data('download-link'),
            guid: button.data('guid'),
            indexerId: button.data('indexer-id')
        });
        const releaseTitle = button.data('title');
        const mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';

        // --- Préparation de la modale ---
        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        // On s'assure que la vue d'ajout est cachée et que la vue de recherche est visible
        modalBody.find('#add-item-options-container').addClass('d-none');
        modalEl.find('#confirm-add-and-map-btn').addClass('d-none');
        // On affiche le conteneur du contenu de recherche et on y met un spinner
        const lookupContent = modalBody.find('#initial-lookup-content').removeClass('d-none').show();
        lookupContent.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche des correspondances...</p></div>');

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
    });

    // ### NOUVEAU BLOC : GESTIONNAIRE POUR "AJOUTER & VOIR LES DÉTAILS" ###
    $('body').on('click', '#sonarrRadarrSearchModal .add-and-enrich-btn', function() {
        const button = $(this);
        const mediaType = button.data('media-type'); // 'tv' or 'movie'
        const instanceType = mediaType === 'tv' ? 'sonarr' : 'radarr';
        const externalId = button.data('ext-id');
        const title = button.data('title'); // Récupérer le titre

        const optionsContainer = modalBody.find('#add-item-options-container');
        const lookupContainer = modalBody.find('#initial-lookup-content');
        const finalButton = modalEl.find('#confirm-add-and-map-btn');
        const detailsContainer = optionsContainer.find('#new-media-details-container');

        // Stocker les données nécessaires pour l'étape finale
        optionsContainer.data('external-id', externalId);
        optionsContainer.data('media-type', mediaType);
        optionsContainer.data('title', title); // Stocker le titre

        // Transition de l'interface
        lookupContainer.hide();
        optionsContainer.removeClass('d-none');
        finalButton.removeClass('d-none');
        detailsContainer.html('<div class="d-flex justify-content-center align-items-center p-3"><div class="spinner-border spinner-border-sm"></div><span class="ms-2">Chargement des détails...</span></div>');
        optionsContainer.find('select').empty().prop('disabled', true).html('<option>Chargement...</option>');
        optionsContainer.find('#add-item-error-container').empty();
        optionsContainer.find('#language-profile-select').parent().toggle(instanceType === 'sonarr');

        // --- Début des appels API parallèles ---

        // 1. Appel pour les détails enrichis (poster, synopsis...)
        const enrichPromise = fetch('/search/api/enrich/details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: externalId, media_type: mediaType, is_new: true })
        }).then(res => res.ok ? res.json() : Promise.reject('enrichDetails'));

        // 2. Appels pour les options d'ajout (dossiers, profils...)
        let rootFolderUrl, qualityProfileUrl;
        if (instanceType === 'radarr') {
            rootFolderUrl = '/seedbox/api/get-radarr-rootfolders';
            qualityProfileUrl = '/seedbox/api/get-radarr-qualityprofiles';
        } else {
            rootFolderUrl = '/seedbox/api/get-sonarr-rootfolders';
            qualityProfileUrl = '/seedbox/api/get-sonarr-qualityprofiles';
        }

        const optionsPromise = Promise.all([
            fetch(rootFolderUrl).then(res => res.ok ? res.json() : Promise.reject('rootFolders')),
            fetch(qualityProfileUrl).then(res => res.ok ? res.json() : Promise.reject('qualityProfiles'))
        ]);

        // --- Traitement des résultats des appels ---

        Promise.all([enrichPromise, optionsPromise]).then(([details, options]) => {
            // Traiter les détails enrichis
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

            // Traiter les options d'ajout
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
    });

    // ### NOUVEAU BLOC : GESTIONNAIRE POUR LE BOUTON "RETOUR À LA LISTE" ###
    $('body').on('click', '#sonarrRadarrSearchModal .back-to-lookup-btn', function() {
        const releaseDetails = modalEl.data('release-details');
        if (!releaseDetails) {
            console.error("Impossible de revenir en arrière : les détails de la release sont introuvables.");
            return;
        }

        // On réutilise la logique de la fonction 'download-and-map-btn' pour relancer le lookup
        const releaseTitle = releaseDetails.title;
        const mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';

        // --- Préparation de la modale pour la vue de recherche ---
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

    // ### CORRECTION : L'écouteur est maintenant attaché à 'body', comme les autres ###
    $('body').on('click', '#confirm-add-and-map-btn', function() {
        const button = $(this);
        const optionsContainer = modalBody.find('#add-item-options-container');
        const errorContainer = optionsContainer.find('#add-item-error-container');

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Ajout en cours...');
        errorContainer.empty();

        // 1. Récupérer toutes les données nécessaires
        const releaseDetails = modalEl.data('release-details');
        const mediaType = optionsContainer.data('media-type');
        const instanceType = mediaType === 'tv' ? 'sonarr' : 'radarr';

        const addPayload = {
            app_type: instanceType,
            external_id: optionsContainer.data('external-id'),
            title: optionsContainer.data('title'),
            root_folder_path: $('#root-folder-select').val(),
            quality_profile_id: $('#quality-profile-select').val(),
            searchForMovie: $('#search-on-add-check').is(':checked')
        };

        console.log("Payload d'ajout:", addPayload);

        // 2. Appeler l'API pour ajouter le média et récupérer son ID interne
        fetch('/seedbox/api/add-arr-item-and-get-id', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(addPayload)
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => Promise.reject(err));
            }
            return response.json();
        })
        .then(data => {
            if (data.error || !data.new_media_id) {
                throw new Error(data.error || "L'ID du nouveau média n'a pas été retourné.");
            }

            console.log(`Média ajouté avec succès. Nouvel ID interne : ${data.new_media_id}`);
            button.html('<span class="spinner-border spinner-border-sm"></span> Envoi au téléchargement...');

            // 3. Préparer et lancer le téléchargement et le mapping avec le nouvel ID
            const finalPayload = {
                releaseName: releaseDetails.title,
                downloadLink: releaseDetails.downloadLink,
                guid: releaseDetails.guid,
                indexerId: releaseDetails.indexerId,
                instanceType: mediaType,
                mediaId: data.new_media_id // Utilisation du nouvel ID
            };

            console.log("Payload de mapping final (nouveau média):", finalPayload);
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
            console.error("Erreur dans le workflow d'ajout final:", error);
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
                        <div class="col-md-3">
                            <img src="${details.poster}" class="img-fluid rounded-start" alt="Poster">
                        </div>
                        <div class="col-md-9">
                            <div class="card-body">
                                <h5 class="card-title">${details.title} (${details.year})</h5>
                                <p class="card-text small"><strong>Statut:</strong> ${details.status}</p>
                                <p class="card-text small" style="max-height: 150px; overflow-y: auto;">${details.overview || 'Synopsis non disponible.'}</p>
                                <button class="btn btn-sm btn-primary confirm-mapping-btn me-2" data-media-id="${details.id}">Choisir ce média</button>
                                <button class="btn btn-sm btn-secondary back-to-lookup-btn">Retour à la liste</button>
                            </div>
                        </div>
                    </div>
                </div>`;
            container.removeClass('list-group-item d-flex justify-content-between align-items-center').html(enrichedHtml);
        })
        .catch(err => {
            container.html('<div class="text-danger">Erreur de communication.</div>');
            console.error("Erreur d'enrichissement:", err);
        });
    });
    // ### NOUVEAU BLOC : GESTIONNAIRE POUR "CHOISIR CE MEDIA" ###
    $('body').on('click', '#sonarrRadarrSearchModal .confirm-mapping-btn', function() {
        const button = $(this);
        const selectedMediaId = button.data('media-id');
        const mediaType = button.closest('[data-media-type]').data('media-type');
        
        // On récupère les détails de la release que nous avons stockés à l'étape 1
        const releaseDetails = modalEl.data('release-details');

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Confirmation...');

        const finalPayload = {
            releaseName: releaseDetails.title,
            downloadLink: releaseDetails.downloadLink,
            guid: releaseDetails.guid,
            indexerId: releaseDetails.indexerId,
            instanceType: mediaType, // 'tv' or 'movie'
            mediaId: selectedMediaId
        };

        console.log("Envoi du payload de mapping final :", finalPayload);

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
