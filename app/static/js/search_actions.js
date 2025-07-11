$(document).ready(function() {
    console.log("Search actions script loaded.");

    // --- [1] Logique pour le bouton "Télécharger & Mapper" (Ouvre la modale) ---
    // Commenting out the old jQuery-based handler for .download-and-map-btn
    /*
    $('body').on('click', '.download-and-map-btn', function(e) {
        e.preventDefault();
        console.log("Bouton '& Mapper' cliqué !");
        
        const modalElement = $('#sonarrRadarrSearchModal');
        
        // --- New logic to check status and determine actionType ---
        const listItem = $(this).closest('li.list-group-item');
        const statusCell = listItem.find('.status-cell');
        let statusTextRaw = '';
        let actionType = 'add_then_map'; // Default action

        if (statusCell.length > 0) {
            if (statusCell.find('.check-status-btn').length > 0) {
                statusTextRaw = 'NOT_LOADED';
                // For NOT_LOADED, default to 'add_then_map'. User searches in modal.
                // If found & monitored, backend handles. If not found, modal should ideally offer add.
            } else {
                statusTextRaw = statusCell.text().trim().toLowerCase();
                if (statusTextRaw.includes('manquant (surveillé)') || statusTextRaw.includes('déjà présent')) {
                    actionType = 'map_existing';
                }
                // Other statuses (non surveillé, non trouvé, erreur, indéterminé) use default 'add_then_map'
            }
        } else {
            console.warn("Could not find status cell for item. Defaulting to 'add_then_map'.");
            actionType = 'add_then_map';
        }
        console.log("[Handler 1] Action type determined:", actionType, "based on status:", statusTextRaw);
        modalElement.data('actionType', actionType); // Store actionType for use by other handlers or modal logic
        // --- End of new status check logic ---

        // Stocker les données Prowlarr sur la modale (existing logic, slightly adjusted variable names for clarity)
        const prowlarrReleaseTitle = $(this).data('release-title');
        const prowlarrDownloadLink = $(this).data('download-link');
        const prowlarrGuid = $(this).data('guid');
        const prowlarrIndexerId = $(this).data('indexer-id');
        const prefillQuery = $(this).data('parsed-title') || prowlarrReleaseTitle; // Use parsed-title (now result.title) or fallback to release title

        console.log("[Handler 1] Storing Prowlarr data on modal: releaseTitle=", prowlarrReleaseTitle, ", downloadLink=", prowlarrDownloadLink, ", guid=", prowlarrGuid, ", indexerId=", prowlarrIndexerId);
        modalElement.data('releaseTitle', prowlarrReleaseTitle); // This is the Prowlarr release title
        modalElement.data('downloadLink', prowlarrDownloadLink);
        modalElement.data('guid', prowlarrGuid);
        modalElement.data('indexerId', prowlarrIndexerId);
        
        // Pré-remplir le champ de recherche dans la modale
        modalElement.find('#sonarrRadarrQuery').val(prefillQuery);
        
        // Réinitialiser le titre de la modale et les résultats de recherche précédents
        modalElement.find('#sonarrRadarrModalLabel').text(`Mapper : ${prowlarrReleaseTitle}`);
        modalElement.find('#prowlarrModalSearchResults').empty().html('<p class="text-muted text-center">Effectuez une recherche pour trouver un média à associer.</p>');
        
        modalElement.modal('show');
    });
    */
    // END OF MODIFIED HANDLER [1]

    // --- Nouvelle logique pour la modale de mapping intelligent (JavaScript natif) ---
    document.addEventListener('DOMContentLoaded', function() {
        // L'ancien écouteur direct sur document.body pour .download-and-map-btn a été supprimé.

        const resultsContainer = document.getElementById('search-results-container');

        if (resultsContainer) {
            resultsContainer.addEventListener('click', function(event) {
                const mapButton = event.target.closest('.download-and-map-btn');

                if (mapButton) {
                    event.preventDefault();

                    const releaseTitle = mapButton.dataset.releaseTitle; // Corrected: was mapButton.dataset.title
                    const guid = mapButton.dataset.guid;
                    const downloadLink = mapButton.dataset.downloadLink;
                    const indexerId = mapButton.dataset.indexerId;

                    console.log("Delegated .download-and-map-btn clicked. Release:", releaseTitle, "GUID:", guid);

                    const modalEl = document.getElementById('intelligent-mapping-modal');
                    if (!modalEl) {
                        console.error("La modale #intelligent-mapping-modal n'a pas été trouvée !");
                        return;
                    }
                    // Utiliser getOrCreateInstance pour être sûr, même si la modale devrait toujours exister.
                    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                    const loader = document.getElementById('mapping-modal-loader');
                    const content = document.getElementById('mapping-modal-content');
                    const confirmBtn = document.getElementById('confirm-map-btn');

                    // Réinitialiser l'état du bouton de confirmation
                    confirmBtn.disabled = false;

                    loader.style.display = 'block';
                    content.classList.add('d-none');
                    content.innerHTML = ''; // Vider le contenu précédent
                    modal.show();

                    // Stocker les infos Prowlarr sur le bouton de confirmation pour l'étape finale
                    confirmBtn.dataset.guid = guid;
                    confirmBtn.dataset.downloadLink = downloadLink;
                    confirmBtn.dataset.indexerId = indexerId;
                    confirmBtn.dataset.releaseTitle = releaseTitle;

                    fetch("/search/api/prepare_mapping_details", { // URL en dur
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ title: releaseTitle })
                    })
                    .then(response => {
                        if (!response.ok) {
                            return response.json().then(errData => {
                                throw new Error(errData.error || `Erreur HTTP ${response.status}`);
                            }).catch(() => {
                                throw new Error(`Erreur HTTP ${response.status}`);
                            });
                        }
                        return response.json();
                    })
                    .then(data => {
                        if (data.error) {
                            throw new Error(data.error);
                        }

                        const yearDisplay = data.year ? `(${data.year})` : '';
                        const overviewDisplay = data.overview || 'Synopsis non disponible.';
                        const posterHtml = data.remotePoster ? `<img src="${data.remotePoster}" class="img-fluid rounded mb-3" style="max-height: 400px; object-fit: contain;">` : '<p class="text-muted">Aucune jaquette disponible.</p>';

                        content.innerHTML = `
                            <p>La release <code>${releaseTitle}</code> sera mappée avec le média suivant :</p>
                            <div class="row">
                                <div class="col-md-4 text-center">${posterHtml}</div>
                                <div class="col-md-8">
                                    <h4>${data.title || 'Titre inconnu'} ${yearDisplay}</h4>
                                    <p class="text-muted small" style="max-height: 250px; overflow-y: auto;">${overviewDisplay}</p>
                                    ${data.id ? '' : '<p class="text-warning small">Note: Ce média n\'est pas encore dans Sonarr/Radarr. Le mapping l\'ajoutera.</p>'}
                                </div>
                            </div>
                        `;

                        confirmBtn.dataset.arrId = data.id; // Peut être null
                        confirmBtn.dataset.mediaType = data.media_type;

                        loader.style.display = 'none';
                        content.classList.remove('d-none');
                    })
                    .catch(error => {
                        console.error("Erreur lors de la préparation du mapping:", error);
                        content.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
                        loader.style.display = 'none';
                        content.classList.remove('d-none');
                        confirmBtn.disabled = true;
                    });
                }
            });
        } else {
            console.warn("Le conteneur #search-results-container n'a pas été trouvé. L'écouteur d'événements pour .download-and-map-btn ne sera pas actif.");
        }

        // Nouvel écouteur pour le bouton de confirmation final dans la modale intelligente
        const confirmMapButton = document.getElementById('confirm-map-btn');
        if (confirmMapButton) {
            confirmMapButton.addEventListener('click', function() {
                const guid = this.dataset.guid;
                const arrId = this.dataset.arrId; // Peut être "null" (string) ou null (object) si non défini.
                const downloadLink = this.dataset.downloadLink;
                const indexerId = this.dataset.indexerId;
                const releaseTitle = this.dataset.releaseTitle;
                const mediaType = this.dataset.mediaType; // 'movie' or 'episode'

                // Convertir arrId en null si c'est la string "null" ou undefined, sinon en int si c'est un nombre valide
                let finalArrId = null;
                if (arrId && arrId !== "null" && arrId !== "undefined") {
                    const parsedId = parseInt(arrId, 10);
                    if (!isNaN(parsedId)) {
                        finalArrId = parsedId;
                    }
                }

                console.log(`Lancement du mapping pour GUID: ${guid} avec l'ID Sonarr/Radarr: ${finalArrId} (Type: ${mediaType})`);
                console.log(`Infos Prowlarr: Release='${releaseTitle}', Link='${downloadLink}', Indexer='${indexerId}'`);

                // TODO: Ici, appeler la VRAIE route de téléchargement et mapping
                // Exemple: fetch('/search/download-and-map', { ... })
                // en utilisant les données stockées: guid, finalArrId, releaseTitle, downloadLink, indexerId, mediaType
                // Le backend /search/download-and-map devra être adapté pour utiliser ces informations.
                // Si finalArrId est null, le backend devra comprendre qu'il s'agit d'un nouvel ajout basé sur releaseTitle (et peut-être guid pour l'ID externe).

                alert(`Simulation: Mapping pour GUID: ${guid}, ArrID: ${finalArrId}, Type: ${mediaType}. Vérifiez la console.`);

                const modal = bootstrap.Modal.getInstance(document.getElementById('intelligent-mapping-modal'));
                if (modal) {
                    modal.hide();
                }
            });
        } else {
            console.error("Le bouton #confirm-map-btn n'a pas été trouvé !");
        }
    });
    // --- Fin de la nouvelle logique pour la modale de mapping intelligent ---

    // --- [2] Logique pour le bouton "Rechercher" DANS la modale ---
    $('body').on('click', '#executeSonarrRadarrSearch', function(e) {
        console.log("Recherche dans la modale DÉCLENCHÉE !");
        
        const query = $('#sonarrRadarrQuery').val();
        const mediaTypeInput = $('input[name="mapInstanceType"]:checked');
        const mediaType = mediaTypeInput.val();
        const mediaTypeLabel = mediaTypeInput.next('label').text() || mediaType; // For display
        const resultsContainer = $('#prowlarrModalSearchResults');

        const modalElement = $('#sonarrRadarrSearchModal'); // Get the modal
        const currentActionType = modalElement.data('actionType');
        const originalProwlarrTitle = modalElement.data('releaseTitle');
        const originalProwlarrGuid = modalElement.data('guid');
        const originalProwlarrDownloadLink = modalElement.data('downloadLink');
        const originalProwlarrIndexerId = modalElement.data('indexerId');

        if (!query) {
            resultsContainer.html('<p class="text-danger text-center">Veuillez entrer un terme de recherche.</p>');
            return;
        }

        resultsContainer.html('<div class="d-flex justify-content-center align-items-center"><div class="spinner-border text-info" role="status"></div><strong class="ms-2">Recherche...</strong></div>');

        $.ajax({
            url: '/search/api/search-arr', // This endpoint searches Sonarr/Radarr
            type: 'GET',
            data: { query: query, type: mediaType },
            success: function(data) {
                resultsContainer.empty();
                console.log(`[Handler 2 AJAX Success] ActionType: ${currentActionType}, Media Type: ${mediaType}`);
                if (data && data.length > 0) {
                    const list = $('<div class="list-group"></div>');
                    data.forEach(function(item) {
                        const year = item.year || '';
                        const title = item.title || 'Titre inconnu';
                        // id is Sonarr/Radarr internal ID if exists, otherwise it might be an external id like tvdbId/tmdbId from a lookup
                        const id = item.id || item.tvdbId || item.tmdbId;
                        const isExistingInArr = !!item.id; // True if Sonarr/Radarr internal ID exists

                        // Display more info about the item
                        let itemDetails = `<strong>${title}</strong> (${year})`;
                        if(isExistingInArr) {
                            itemDetails += `<br><small class="text-success">Déjà dans ${mediaTypeLabel} (ID: ${id})</small>`;
                        } else {
                            itemDetails += `<br><small class="text-primary">Non trouvé dans ${mediaTypeLabel} (ID Externe: ${id})</small>`;
                        }
                        // TODO: Add more details like monitored status if available from search_arr_proxy

                        const itemHtml = `
                            <button type="button" class="list-group-item list-group-item-action map-select-item-btn"
                                    data-media-id="${id}"
                                    data-media-title="${title.replace(/"/g, '&quot;')}" 
                                    data-instance-type="${mediaType}" 
                                    data-year="${year}"
                                    data-is-existing-in-arr="${isExistingInArr}">
                                ${itemDetails}
                            </button>`;
                        list.append(itemHtml);
                    });
                    resultsContainer.append(list);
                } else { // No results found in Sonarr/Radarr for the query
                    if (currentActionType === 'add_then_map' && originalProwlarrTitle) {
                        resultsContainer.html(`
                            <p class="text-warning text-center mt-3">Aucun média existant trouvé dans ${mediaTypeLabel} pour "${query}".</p>
                            <div class="text-center mt-3">
                                <p>Voulez-vous tenter d'ajouter <strong>"${originalProwlarrTitle}"</strong> à ${mediaTypeLabel} et de le télécharger ?</p>
                                <button class="btn btn-info btn-sm directly-add-prowlarr-item-btn"
                                        data-prowlarr-title="${originalProwlarrTitle.replace(/"/g, '&quot;')}"
                                        data-prowlarr-guid="${originalProwlarrGuid}"
                                        data-prowlarr-downloadlink="${originalProwlarrDownloadLink}"
                                        data-prowlarr-indexerid="${originalProwlarrIndexerId}"
                                        data-arr-type="${mediaType}">
                                    <i class="fas fa-plus-circle"></i> Oui, ajouter et télécharger
                                </button>
                            </div>
                        `);
                    } else {
                        resultsContainer.html('<p class="text-warning text-center">Aucun résultat trouvé.</p>');
                    }
                }
            },
            error: function(jqXHR) {
                const errorMsg = jqXHR.responseJSON ? jqXHR.responseJSON.error : "Erreur de communication.";
                resultsContainer.html(`<p class="text-danger text-center">Erreur: ${errorMsg}</p>`);
            }
        });
    });

    // --- [3] Logique pour le clic sur un résultat DANS la modale (.map-select-item-btn) ---
    $('body').on('click', '.map-select-item-btn', function(e) {
        e.stopPropagation();
        
        const button = $(this);
        const mediaId = button.data('media-id'); // Sonarr/Radarr ID or external ID if not in Arr
        const mediaType = button.data('instance-type');
        const mediaTitle = button.data('media-title'); // Title from Sonarr/Radarr item
        // const mediaYear = button.data('year'); // Available if needed
        // const isExistingInArr = button.data('is-existing-in-arr'); // Boolean: true if item.id was present

        const modal = $('#sonarrRadarrSearchModal');
        const releaseTitle = modal.data('releaseTitle'); // Original Prowlarr release title
        const downloadLink = modal.data('downloadLink');
        const guid = modal.data('guid');
        const indexerId = modal.data('indexerId');
        const actionType = modal.data('actionType'); // 'map_existing' or 'add_then_map'

        console.log(`[Handler 3] Clicked map-select. Media ID: ${mediaId}, ActionType: ${actionType}, Prowlarr Release: ${releaseTitle}`);

        if (!mediaId || !mediaType || !releaseTitle || !downloadLink || !guid || !indexerId) {
            alert("Erreur critique : information essentielle manquante pour le mapping.");
            console.error("[Handler 3] Missing data check failed:", { mediaId, mediaType, releaseTitle, downloadLink, guid, indexerId, actionType });
            return;
        }
    
        button.closest('.list-group').find('.map-select-item-btn').prop('disabled', true);
        button.html('<span class="spinner-border spinner-border-sm" role="status"></span> Lancement...');

        fetch('/search/download-and-map', { // Backend needs to handle 'add_then_map'
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                releaseName: releaseTitle, // Prowlarr release name
                downloadLink: downloadLink,
                indexerId: indexerId,
                guid: guid,
                instanceType: mediaType, // sonarr or radarr
                mediaId: mediaId,        // Sonarr/Radarr internal ID, or external (TVDB/TMDB) ID if not in Arr yet
                actionType: actionType   // 'map_existing' or 'add_then_map'
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert(data.message);
                modal.modal('hide');
            } else {
                alert('Erreur: ' + data.message);
                button.closest('.list-group').find('.map-select-item-btn').prop('disabled', false);
                button.html(`<strong>${mediaTitle}</strong> (${mediaYear})`); // Restaurer le texte
            }
        })
        .catch(error => {
            console.error('Erreur Fetch:', error);
            alert('Erreur de communication avec le serveur.');
            button.closest('.list-group').find('.map-select-item-btn').prop('disabled', false);
            // Restore button text carefully, as its content is now complex HTML
            // For simplicity, just re-enable. The modal will likely be closed or re-searched.
            // button.html(`<strong>${mediaTitle}</strong> (${mediaYear})`); // Original line, might be complex
        });
    });

    // --- [New Handler] Logique pour le bouton ".directly-add-prowlarr-item-btn" ---
    $('body').on('click', '.directly-add-prowlarr-item-btn', function() {
        const button = $(this);
        const releaseTitle = button.data('prowlarr-title');
        const guid = button.data('prowlarr-guid');
        const downloadLink = button.data('prowlarr-downloadlink');
        const indexerId = button.data('prowlarr-indexerid');
        const instanceType = button.data('arr-type'); // 'sonarr' or 'radarr'

        console.log(`[Directly Add Handler] Adding: ${releaseTitle}, Type: ${instanceType}`);
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status"></span> Ajout en cours...');

        fetch('/search/download-and-map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                releaseName: releaseTitle,
                downloadLink: downloadLink,
                indexerId: indexerId,
                guid: guid,
                instanceType: instanceType,
                mediaId: 'NEW_ITEM_FROM_PROWLARR', // Special flag for backend
                actionType: 'add_then_map'
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert(data.message);
                $('#sonarrRadarrSearchModal').modal('hide');
            } else {
                alert('Erreur: ' + data.message);
                button.prop('disabled', false).html('<i class="fas fa-plus-circle"></i> Oui, ajouter et télécharger');
            }
        })
        .catch(error => {
            console.error('Erreur Fetch for directly-add:', error);
            alert('Erreur de communication avec le serveur.');
            button.prop('disabled', false).html('<i class="fas fa-plus-circle"></i> Oui, ajouter et télécharger');
        });
    });

    // --- [4] Logique pour le bouton "Vérifier Statut" ---
    document.addEventListener('click', function(event) {
        if (event.target.classList.contains('check-status-btn')) {
            const button = event.target;
            const statusCell = button.closest('.status-cell'); // Find the parent cell
            const spinner = statusCell.querySelector('.spinner-border');

            const guid = button.dataset.guid;
            const title = button.dataset.title;

            button.classList.add('d-none');
            spinner.classList.remove('d-none');

            // Assuming the blueprint is mounted at /search, so the URL is /search/check_media_status
            // This matches the pattern of other fetch/ajax calls in this file.
            fetch("/search/check_media_status", {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    // If CSRF protection is enabled and needed for POST requests,
                    // a CSRF token would need to be included in headers.
                    // For example, get it from a meta tag or a hidden input if available.
                    // 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').getAttribute('content')
                },
                body: JSON.stringify({ guid: guid, title: title })
            })
            .then(response => {
                if (!response.ok) {
                    // Try to parse error a bit better if it's JSON
                    return response.json().then(errData => {
                        throw new Error(errData.text || `HTTP error ${response.status}`);
                    }).catch(() => {
                        // If not JSON, throw generic error
                        throw new Error(`HTTP error ${response.status}`);
                    });
                }
                return response.json();
            })
            .then(data => {
                if (data.text && data.status_class) {
                    statusCell.innerHTML = `<span class="${data.status_class}">${data.text}</span>`;
                } else {
                    // Fallback if data is not as expected
                    statusCell.innerHTML = `<span class="text-warning">Réponse invalide</span>`;
                }
            })
            .catch(error => {
                console.error("Erreur de vérification du statut:", error);
                statusCell.innerHTML = `<span class="text-danger">Erreur: ${error.message || 'Communication'}</span>`;
            });
        }
    });
});
