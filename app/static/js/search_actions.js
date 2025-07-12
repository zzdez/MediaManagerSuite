$(document).ready(function() {
    console.log("Search actions script loaded.");

    // --- [1] Logique pour le bouton "Télécharger & Mapper" (Ouvre la modale) ---
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
    // END OF MODIFIED HANDLER [1]

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
                    data.forEach(function(item) {
                        const year = item.year || '';
                        const title = item.title || 'Titre inconnu';
                        const overview = item.overview || 'Synopsis non disponible.';
                        const posterUrl = item.poster || 'https://via.placeholder.com/200x300.png?text=No+Poster'; // Image par défaut

                        let statusBadge = '';
                        if (mediaType === 'sonarr') { // Les badges de statut sont plus pertinents pour les séries
                            if (item.status === 'ended') {
                                statusBadge = '<span class="badge bg-danger ms-2">Terminé</span>';
                            } else if (item.status === 'continuing') {
                                statusBadge = '<span class="badge bg-success ms-2">En cours</span>';
                            }
                        }

                        let addedBadge = item.isAdded ? '<span class="badge bg-info ms-2">Déjà Ajouté</span>' : '';

                        let seasonsInfo = '';
                        if (mediaType === 'sonarr' && item.seasons !== 'N/A') {
                            seasonsInfo = `<small class="text-info">Saisons: ${item.seasons}</small>`;
                        }

                        const itemHtml = `
                            <button type="button" class="list-group-item list-group-item-action map-select-item-btn"
                                    data-media-id="${item.id}"
                                    data-media-title="${title.replace(/"/g, '&quot;')}"
                                    data-instance-type="${mediaType}"
                                    data-year="${year}"
                                    data-is-existing-in-arr="${item.isAdded}">
                                <div class="row g-2 align-items-center">
                                    <div class="col-md-2 text-center">
                                        <img src="${posterUrl}" class="img-fluid rounded" style="max-height: 150px;">
                                    </div>
                                    <div class="col-md-10">
                                        <h6 class="mb-1">${title} (${year})${statusBadge}${addedBadge}</h6>
                                        ${
                                            (() => {
                                                let alternateTitleHtml = '';
                                                const mainTitle = item.title || '';

                                                if (item.alternate_titles && item.alternate_titles.length > 0) {
                                                    // Recherche spécifiquement le titre français et anglais
                                                    const frenchTitleObj = item.alternate_titles.find(alt => alt.lang === 'french');
                                                    const englishTitleObj = item.alternate_titles.find(alt => alt.lang === 'english');

                                                    let displayTitles = [];

                                                    // Logique pour déterminer quel titre afficher
                                                    if (frenchTitleObj && frenchTitleObj.title.toLowerCase() !== mainTitle.toLowerCase()) {
                                                        displayTitles.push(`<i>Titre Français: ${frenchTitleObj.title}</i>`);
                                                    }

                                                    if (englishTitleObj && englishTitleObj.title.toLowerCase() !== mainTitle.toLowerCase()) {
                                                        // Évite d'afficher le titre anglais s'il est le même que le titre français déjà trouvé
                                                        if (!frenchTitleObj || englishTitleObj.title.toLowerCase() !== frenchTitleObj.title.toLowerCase()) {
                                                            displayTitles.push(`<i>Titre Original: ${englishTitleObj.title}</i>`);
                                                        }
                                                    }

                                                    if(displayTitles.length > 0) {
                                                        alternateTitleHtml = `<small class="d-block text-info">${displayTitles.join(' | ')}</small>`;
                                                    }
                                                }
                                                return alternateTitleHtml;
                                            })()
                                        }
                                        <p class="mb-1 small text-muted modal-synopsis" title="Survolez pour lire la suite">
                                            ${overview}
                                        </p>
                                        ${seasonsInfo}
                                    </div>
                                </div>
                            </button>`;
                        resultsContainer.append(itemHtml);
                    });
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

    // --- [4] Logique pour le bouton "Vérifier Statut" (converti en jQuery delegation) ---
    $('body').on('click', '.check-status-btn', function() {
        const button = $(this);
        const statusCell = button.closest('.status-cell');
        const spinner = statusCell.find('.spinner-border');

        const guid = button.data('guid');
        const title = button.data('title');

        button.addClass('d-none');
        spinner.removeClass('d-none');

        fetch("/search/check_media_status", {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ guid: guid, title: title })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(errData => {
                    throw new Error(errData.text || `HTTP error ${response.status}`);
                }).catch(() => {
                    throw new Error(`HTTP error ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.text && data.status_class) {
                statusCell.html(`<span class="${data.status_class}">${data.text}</span>`);
            } else {
                statusCell.html(`<span class="text-warning">Réponse invalide</span>`);
            }
        })
        .catch(error => {
            console.error("Erreur de vérification du statut:", error);
            statusCell.html(`<span class="text-danger">Erreur: ${error.message || 'Communication'}</span>`);
        });
    });
});
