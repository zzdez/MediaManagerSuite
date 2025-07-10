$(document).ready(function() {
    console.log("Search actions script loaded.");

    // --- [1] Logique pour le bouton "Télécharger & Mapper" (Ouvre la modale) ---
    // RESTORED
    $('body').on('click', '.download-and-map-btn', function(e) {
        e.preventDefault();
        console.log("Bouton 'Télécharger & Mapper' cliqué !");
        
        const modalElement = $('#sonarrRadarrSearchModal'); // Use jQuery selector
        
        // Stocker les données sur la modale pour les retrouver plus tard
        const releaseTitleToStore = $(this).data('release-title');
        const downloadLinkToStore = $(this).data('download-link');
        const guidToStore = $(this).data('guid');
        const indexerIdToStore = $(this).data('indexer-id');

        console.log("[Handler 1] Storing on modal: releaseTitle =", releaseTitleToStore, ", downloadLink =", downloadLinkToStore, ", guid =", guidToStore, ", indexerId =", indexerIdToStore);
        modalElement.data('releaseTitle', releaseTitleToStore);
        modalElement.data('downloadLink', downloadLinkToStore);
        modalElement.data('guid', guidToStore);
        modalElement.data('indexerId', indexerIdToStore);
        // Verification log immediately after storing
        console.log("[Handler 1] Data stored: releaseTitle on modal is now", modalElement.data('releaseTitle'),
                    ", downloadLink on modal is now", modalElement.data('downloadLink'),
                    ", guid on modal is now", modalElement.data('guid'),
                    ", indexerId on modal is now", modalElement.data('indexerId'));
        
        // Pré-remplir le champ de recherche
        modalElement.find('#sonarrRadarrQuery').val($(this).data('parsed-title') || '');
        
        // Réinitialiser les résultats et le titre
        modalElement.find('#sonarrRadarrModalLabel').text(`Mapper : ${$(this).data('release-title')}`);
        // IMPORTANT: The HTML for sonarrRadarrSearchModal must have its results div ID changed to 'prowlarrModalSearchResults'
        modalElement.find('#prowlarrModalSearchResults').empty().html('<p class="text-muted text-center">Effectuez une recherche pour trouver un média à associer.</p>');
        
        modalElement.modal('show'); // Use Bootstrap 3/4 style
    });
    // END OF RESTORED HANDLER [1]

    // --- [2] Logique pour le bouton "Rechercher" DANS la modale ---
    $('body').on('click', '#executeSonarrRadarrSearch', function(e) {
        // e.stopPropagation(); // Temporarily removed for testing
        console.log("Recherche dans la modale DÉCLENCHÉE !");
        
        const query = $('#sonarrRadarrQuery').val();
        const mediaType = $('input[name="mapInstanceType"]:checked').val();
        // IMPORTANT: Ensure the modal HTML's results div ID is updated to 'prowlarrModalSearchResults'
        const resultsContainer = $('#prowlarrModalSearchResults');

        if (!query) {
            resultsContainer.html('<p class="text-danger text-center">Veuillez entrer un terme de recherche.</p>');
            return;
        }

        resultsContainer.html('<div class="d-flex justify-content-center align-items-center"><div class="spinner-border text-info" role="status"></div><strong class="ms-2">Recherche...</strong></div>');

        $.ajax({
            url: '/search/api/search-arr',
            type: 'GET',
            data: { query: query, type: mediaType },
            success: function(data) {
                resultsContainer.empty();
                // Log mediaType's value as seen by the success callback's closure
                console.log("[Handler 2 AJAX Success] Value of mediaType from closure:", mediaType); 
                if (data && data.length > 0) {
                    const list = $('<div class="list-group"></div>');
                    data.forEach(function(item) {
                        const year = item.year || '';
                        const title = item.title || 'Titre inconnu';
                        const id = item.id || item.tvdbId || item.tmdbId;

                        const itemHtml = `
                            <button type="button" class="list-group-item list-group-item-action map-select-item-btn"
                                    data-media-id="${id}"
                                    data-media-title="${title.replace(/"/g, '&quot;')}" 
                                    data-instance-type="${mediaType}" 
                                    data-year="${year}">
                                <strong>${title}</strong> (${year})
                            </button>`;
                        list.append(itemHtml);
                    });
                    resultsContainer.append(list);
                } else {
                    resultsContainer.html('<p class="text-warning text-center">Aucun résultat trouvé.</p>');
                }
            },
            error: function(jqXHR) {
                const errorMsg = jqXHR.responseJSON ? jqXHR.responseJSON.error : "Erreur de communication.";
                resultsContainer.html(`<p class="text-danger text-center">Erreur: ${errorMsg}</p>`);
            }
        });
    });

    // --- [3] Logique pour le clic sur un résultat DANS la modale ---
    // RESTORED
    $('body').on('click', '.map-select-item-btn', function(e) {
        e.stopPropagation(); // <-- AJOUTER CETTE LIGNE
        
        const button = $(this);
        const mediaId = button.data('media-id');
        const mediaType = button.data('instance-type'); // Use .data() as it's now working.
        const mediaTitle = button.data('media-title');
        const mediaYear = button.data('year');

        // Removed diagnostic logs for mediaTypeFromData and mediaTypeFromAttr here

        const modal = $('#sonarrRadarrSearchModal');
        const retrievedReleaseTitle = modal.data('releaseTitle');
        const retrievedDownloadLink = modal.data('downloadLink');
        const retrievedGuid = modal.data('guid');
        const retrievedIndexerId = modal.data('indexerId');

        // Keeping this log for now as it confirms modal data, can be removed later if desired.
        console.log("[Handler 3] Retrieving from modal: releaseTitle =", retrievedReleaseTitle,
                    ", downloadLink =", retrievedDownloadLink,
                    ", guid =", retrievedGuid,
                    ", indexerId =", retrievedIndexerId);

        // Use the retrieved values for the check and subsequent operations
        const releaseTitle = retrievedReleaseTitle;
        const downloadLink = retrievedDownloadLink;
        const guid = retrievedGuid;
        const indexerId = retrievedIndexerId;

        if (!mediaId || !mediaType || !releaseTitle || !downloadLink || !guid || !indexerId) {
            alert("Erreur critique : une information essentielle est manquante (mediaId, mediaType, releaseTitle, downloadLink, guid, ou indexerId).");
            // Simplified error log
            console.error("[Handler 3] Missing data check failed:", { mediaId, mediaType, releaseTitle, downloadLink, guid, indexerId });
            return;
        }
    
        button.closest('.list-group').find('.map-select-item-btn').prop('disabled', true);
        button.html('<span class="spinner-border spinner-border-sm" role="status"></span> Lancement...');

        fetch('/search/download-and-map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                releaseName: releaseTitle,
                downloadLink: downloadLink,
                indexerId: indexerId, // Ajouté
                guid: guid,           // Ajouté
                instanceType: mediaType,
                mediaId: mediaId
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
            button.html(`<strong>${mediaTitle}</strong> (${mediaYear})`); // Restaurer le texte
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
