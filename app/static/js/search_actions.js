$(document).ready(function() {
    console.log("Search actions script loaded.");

    // --- [1] Logique pour le bouton "Télécharger & Mapper" (Ouvre la modale INTELLIGENTE) ---
    // Réactivation et adaptation de l'ancien gestionnaire jQuery
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        console.log('Bouton "& Mapper" cliqué (jQuery)');

        const button = $(this);
        // Lire les data-attributes du bouton cliqué
        // Note: jQuery .data() convertit les noms kebab-case en camelCase.
        // Donc data-release-title devient releaseTitle, data-download-link devient downloadLink.
        const releaseTitle = button.data('release-title');
        const guid = button.data('guid');
        const downloadLink = button.data('download-link');
        const indexerId = button.data('indexer-id');

        console.log("Données du bouton:", { releaseTitle, guid, downloadLink, indexerId });

        const modalEl = $('#intelligent-mapping-modal'); // Cible la nouvelle modale
        const loader = $('#mapping-modal-loader');
        const content = $('#mapping-modal-content');
        const confirmBtn = $('#confirm-map-btn');

        // Réinitialise et affiche la modale
        loader.show();
        content.addClass('d-none').html('');
        confirmBtn.prop('disabled', true); // Désactive le bouton en attendant les infos

        // Stocke les infos pour le bouton de confirmation
        // Utiliser .data() pour stocker, ce qui est la manière jQuery.
        confirmBtn.data('guid', guid);
        confirmBtn.data('download-link', downloadLink);
        confirmBtn.data('indexer-id', indexerId);
        confirmBtn.data('release-title', releaseTitle); // Stocker aussi releaseTitle sur confirmBtn

        modalEl.modal('show'); // Utilise la méthode modal de Bootstrap via jQuery

        // Fait l'appel d'enrichissement
        fetch("/search/api/prepare_mapping_details", {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: releaseTitle })
        })
        .then(response => {
            if (!response.ok) {
                // Si c'est une erreur 404, on passe à la gestion du "non trouvé"
                if (response.status === 404) {
                    return response.json().then(errData => {
                        // On lance une erreur personnalisée avec un type
                        let error = new Error(errData.error || 'Média non trouvé dans Sonarr/Radarr.');
                        error.type = 'NOT_FOUND';
                        error.releaseTitle = releaseTitle; // Ajout pour l'utiliser dans le catch
                        throw error;
                    }).catch(() => { // Au cas où .json() échoue pour une 404
                        let error = new Error('Média non trouvé dans Sonarr/Radarr (erreur parsing JSON de la 404).');
                        error.type = 'NOT_FOUND';
                        error.releaseTitle = releaseTitle;
                        throw error;
                    });
                }
                // Pour les autres erreurs HTTP (500, etc.)
                return response.json().then(errData => { // Essayer de parser le JSON d'erreur
                    throw new Error(errData.error || `Erreur serveur ${response.status}.`);
                }).catch(() => { // Si le corps de l'erreur n'est pas JSON
                    throw new Error(`Erreur serveur ${response.status}.`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.error) { // Erreur applicative retournée dans un JSON avec statut 200 (moins probable ici)
                throw new Error(data.error);
            }

            // Remplit le contenu de la modale pour un média trouvé
            const yearDisplay = data.year ? `(${data.year})` : '';
            const overviewDisplay = data.overview || 'Synopsis non disponible.';
            const posterHtml = data.remotePoster ? `<img src="${data.remotePoster}" class="img-fluid rounded mb-3" style="max-height: 400px; object-fit: contain;">` : '<p class="text-muted">Aucune jaquette disponible.</p>';

            content.html(`
                <p>La release <code>${releaseTitle}</code> sera mappée avec le média suivant :</p>
                <div class="row">
                    <div class="col-md-4 text-center">${posterHtml}</div>
                    <div class="col-md-8">
                        <h4>${data.title || 'Titre inconnu'} ${yearDisplay}</h4>
                        <p class="text-muted small" style="max-height: 250px; overflow-y: auto;">${overviewDisplay}</p>
                        ${data.id ? '' : '<p class="text-warning small">Note: Ce média n\'est pas encore dans Sonarr/Radarr. Le mapping l\'ajoutera (si confirmé).</p>'}
                    </div>
                </div>
            `);

            confirmBtn.data('arr-id', data.id);
            confirmBtn.data('media-type', data.media_type);
            confirmBtn.show(); // Assure que le bouton de confirmation initial est visible
            confirmBtn.prop('disabled', false); // Réactive le bouton

            loader.hide();
            content.removeClass('d-none');
        })
        .catch(error => {
            console.error("Erreur lors de la préparation du mapping (jQuery handler):", error);

            if (error.type === 'NOT_FOUND') {
                // Affiche le message d'erreur ET le bouton pour ajouter
                content.html(`
                    <div class="alert alert-warning">${error.message}</div>
                    <p>Voulez-vous tenter d'ajouter <strong>"${error.releaseTitle}"</strong> à Sonarr/Radarr et de le mapper ?</p>
                    <div class="text-center">
                        <button class="btn btn-info" id="add-and-map-new-item-btn">
                            <i class="fas fa-plus-circle"></i> Oui, Ajouter et Mapper
                        </button>
                    </div>
                `);
                confirmBtn.hide(); // Cache le bouton de confirmation initial
            } else {
                // Erreur générique
                content.html(`<div class="alert alert-danger">${error.message}</div>`);
                confirmBtn.hide(); // Cache aussi le bouton de confirmation pour les erreurs génériques
            }
            loader.hide();
            content.removeClass('d-none');
            // confirmBtn est déjà désactivé par défaut ou caché.
        });
    });
    // FIN du gestionnaire pour .download-and-map-btn

    // Gestionnaire pour le bouton de confirmation final dans la modale intelligente (jQuery)
    $('body').on('click', '#confirm-map-btn', function() {
        const button = $(this);
        const guid = button.data('guid');
        // jQuery .data() peut retourner undefined si l'attribut n'existe pas.
        // Il convertit aussi "null" (string) en null (object) si l'attribut data-arr-id="null"
        let arrId = button.data('arr-id');
        const downloadLink = button.data('download-link');
        const indexerId = button.data('indexer-id');
        const releaseTitle = button.data('release-title');
        const mediaType = button.data('media-type');

        // Assurer que arrId est un entier ou null.
        let finalArrId = null;
        if (arrId !== undefined && arrId !== null && arrId !== "null") {
            const parsedId = parseInt(arrId, 10);
            if (!isNaN(parsedId)) {
                finalArrId = parsedId;
            }
        }

        console.log(`[jQuery] Lancement du mapping pour GUID: ${guid} avec l'ID Sonarr/Radarr: ${finalArrId} (Type: ${mediaType})`);
        console.log(`[jQuery] Infos Prowlarr: Release='${releaseTitle}', Link='${downloadLink}', Indexer='${indexerId}'`);

        // TODO: Ici, appeler la VRAIE route de téléchargement et mapping
        // Exemple: fetch('/search/download-and-map', { ... })
        // ...

        alert(`[jQuery] Simulation: Mapping pour GUID: ${guid}, ArrID: ${finalArrId}, Type: ${mediaType}. Vérifiez la console.`);

        // Cacher la modale
        // On s'assure de cibler la bonne modale, même si #confirm-map-btn est dedans.
        $('#intelligent-mapping-modal').modal('hide');
    });
    // FIN du gestionnaire pour #confirm-map-btn

    // Gestionnaire pour le bouton "Oui, Ajouter et Mapper" (ajouté dynamiquement)
    $('body').on('click', '#add-and-map-new-item-btn', function() {
        const addButton = $(this);
        // Les informations nécessaires (guid, downloadLink, indexerId, releaseTitle)
        // sont stockées sur le bouton #confirm-map-btn.
        // #confirm-map-btn est caché mais toujours dans le DOM de la modale.
        const confirmBtn = $('#confirm-map-btn');

        const guid = confirmBtn.data('guid');
        const downloadLink = confirmBtn.data('download-link');
        const indexerId = confirmBtn.data('indexer-id');
        const releaseTitle = confirmBtn.data('release-title');
        // Le mediaType n'est pas connu à ce stade car prepare_mapping_details a échoué.
        // Le backend devra le déduire à partir de releaseTitle (guessit).

        console.log(`[jQuery] Clic sur #add-and-map-new-item-btn.`);
        console.log(`[jQuery] Intention d'AJOUTER et MAPPER pour Release: "${releaseTitle}", GUID: ${guid}`);
        console.log(`[jQuery] Avec DownloadLink: ${downloadLink}, IndexerID: ${indexerId}`);

        // Mettre le bouton en état de chargement
        addButton.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Traitement...');

        // TODO: Logique d'appel à /search/download-and-map
        // Il faudra passer un identifiant spécial pour mediaId, par exemple 'NEW_ITEM_FROM_MODAL_ADD_BUTTON'
        // et s'assurer que le backend peut déterminer le instanceType (sonarr/radarr)
        // Exemple de payload:
        /*
        const payload = {
            releaseName: releaseTitle,
            downloadLink: downloadLink,
            indexerId: indexerId,
            guid: guid,
            mediaId: 'NEW_ITEM_FROM_MODAL_ADD_BUTTON', // Flag spécial
            actionType: 'add_then_map' // Action explicite
            // instanceType devra être déterminé par le backend ou via une étape supplémentaire.
        };
        fetch('/search/download-and-map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert('Succès (simulation): ' + data.message);
                $('#intelligent-mapping-modal').modal('hide');
            } else {
                alert('Erreur (simulation): ' + data.message);
                addButton.prop('disabled', false).html('<i class="fas fa-plus-circle"></i> Oui, Ajouter et Mapper');
            }
        })
        .catch(error => {
            console.error('Erreur fetch pour add-and-map-new-item:', error);
            alert('Erreur de communication serveur (simulation).');
            addButton.prop('disabled', false).html('<i class="fas fa-plus-circle"></i> Oui, Ajouter et Mapper');
        });
        */

        // Pour l'instant, simple alerte et fermeture de la modale
        alert(`Simulation: Ajout et Mapping pour "${releaseTitle}". Le backend doit être adapté.`);
        console.log("La logique réelle d'appel à /search/download-and-map avec action d'ajout est à implémenter.");

        // Optionnel: remettre le bouton à son état initial si on ne ferme pas la modale tout de suite
        // addButton.prop('disabled', false).html('<i class="fas fa-plus-circle"></i> Oui, Ajouter et Mapper');

        $('#intelligent-mapping-modal').modal('hide');
    });
    // FIN du gestionnaire pour #add-and-map-new-item-btn


    // --- Nouvelle logique pour la modale de mapping intelligent (JavaScript natif) ---
    // Ce bloc entier sera supprimé.
    // document.addEventListener('DOMContentLoaded', function() { ... });
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

    // --- [4] Logique pour le bouton "Vérifier Statut" (converti en jQuery delegation) ---
    $('body').on('click', '.check-status-btn', function(event) {
        const button = $(this); // jQuery object for the button
        const statusCell = button.closest('.status-cell');
        const spinner = statusCell.find('.spinner-border'); // Use jQuery find

        // Utiliser .data() pour récupérer les attributs, par cohérence
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
                statusCell.html(`<span class="${data.status_class}">${data.text}</span>`); // Use jQuery .html()
            } else {
                statusCell.html(`<span class="text-warning">Réponse invalide</span>`);
            }
        })
        .catch(error => {
            console.error("Erreur de vérification du statut:", error);
            statusCell.html(`<span class="text-danger">Erreur: ${error.message || 'Communication'}</span>`);
        });
    });
    // FIN du gestionnaire pour .check-status-btn
});
