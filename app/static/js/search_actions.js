// Dans search_actions.js

$(document).ready(function() {
    console.log("Search actions script loaded. (Version corrigée)");

    // GESTIONNAIRE POUR LE BOUTON "& MAPPER"
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        console.log('BOUTON & MAPPER CLIQUE (NOUVELLE LOGIQUE)');

        const button = $(this);
        const releaseTitle = button.data('title'); // Assure-toi que le data-attribute est 'data-title'
        const guid = button.data('guid');
        const downloadLink = button.data('download-link');
        const indexerId = button.data('indexer-id');

        const modalEl = $('#sonarrRadarrSearchModal');
        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        const loader = $('#mapping-modal-loader');
        const content = $('#mapping-modal-content');
        const confirmBtn = $('#confirm-map-btn');

        // Affiche le loader et la modale
        loader.show();
        content.addClass('d-none').html('');
        confirmBtn.prop('disabled', true);

        // Stocke les données pour l'action finale
        confirmBtn.data('guid', guid);
        confirmBtn.data('downloadLink', downloadLink);
        confirmBtn.data('indexerId', indexerId);
        confirmBtn.data('releaseTitle', releaseTitle);

        const modalElement = document.getElementById('sonarrRadarrSearchModal');
        if (!modalElement) {
            console.error("ERREUR: La structure HTML de la modale #sonarrRadarrSearchModal est introuvable !");
            return;
        }
        const myModal = bootstrap.Modal.getOrCreateInstance(modalElement);
        myModal.show(); // La commande pour afficher la modale

        // Appelle la NOUVELLE route d'enrichissement
        console.log("JS: Lancement du fetch vers /search/api/prepare_mapping_details");

        fetch("/search/api/prepare_mapping_details", {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: releaseTitle })
        })
        .then(response => {
            // --- LOG 1 : Est-ce qu'on reçoit une réponse ? ---
            console.log("JS: Réponse reçue du serveur. Statut:", response.status);
            if (!response.ok) {
                throw new Error(`Erreur HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            // --- LOG 2 : Est-ce que les données JSON sont correctes ? ---
            console.log("JS: Données JSON parsées avec succès:", data);

            if (data.error) throw new Error(data.error);

            // Remplit le contenu
            const posterHtml = data.remotePoster ? `<img src="${data.remotePoster}" class="img-fluid rounded">` : '';
            content.html(`<div class="row"><div class="col-md-3">${posterHtml}</div><div class="col-md-9"><h4>${data.title} (${data.year})</h4><p>${data.overview}</p></div></div>`);

            confirmBtn.data('arr-id', data.id); // Stocke l'ID Sonarr/Radarr

            console.log("JS: Contenu de la modale mis à jour. Affichage...");
            loader.hide();
            content.removeClass('d-none');
            confirmBtn.prop('disabled', false);
        })
        .catch(error => {
            // --- LOG 3 : Est-ce qu'une erreur est attrapée ? ---
            console.error("JS: ERREUR DANS LE BLOC FETCH:", error);
            content.html(`<div class="alert alert-danger">${error.message}</div>`);
            loader.hide();
            content.removeClass('d-none');
        });
    });

    // GESTIONNAIRE POUR LE BOUTON "CONFIRMER" DANS LA MODALE
    $('body').on('click', '#confirm-map-btn', function() {
        const button = $(this);
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Lancement...');

        const releaseTitle = button.data('releaseTitle');
        const downloadLink = button.data('downloadLink');
        const guid = button.data('guid');
        const indexerId = button.data('indexerId');
        const mediaId = button.data('arr-id');
        const instanceType = mediaId ? (String(mediaId).startsWith('tvdb') ? 'sonarr' : 'radarr') : null;

        fetch('/search/download-and-map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                releaseName: releaseTitle,
                downloadLink: downloadLink,
                indexerId: indexerId,
                guid: guid,
                instanceType: instanceType,
                mediaId: mediaId,
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
                button.prop('disabled', false).html('Confirmer');
            }
        })
        .catch(error => {
            console.error('Erreur Fetch:', error);
            alert('Erreur de communication avec le serveur.');
            button.prop('disabled', false).html('Confirmer');
        });
    });

    // Supprime les anciens gestionnaires qui ne sont plus utiles
    // $('body').on('click', '#executeSonarrRadarrSearch', ...);
    // $('body').on('click', '.map-select-item-btn', ...);

    $('body').on('click', '#executeSonarrRadarrSearch', function() {
        console.log("Bouton de recherche manuelle cliqué !");

        const modal = $(this).closest('.modal');
        const query = modal.find('#sonarrRadarrQuery').val();
        const resultsContainer = modal.find('#prowlarrModalSearchResults');
        const instanceType = modal.find('input[name="mapInstanceType"]:checked').val();

        if (!query) {
            resultsContainer.html('<p class="text-danger">Veuillez entrer une recherche.</p>');
            return;
        }

        resultsContainer.html('<div class="d-flex justify-content-center"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div></div>');

        // Réutilise l'appel AJAX existant vers /search/api/search-arr
        $.ajax({
            url: '/search/api/search-arr',
            data: {
                query: query,
                type: instanceType
            },
            success: function(data) {
                let html = '';
                if (data.length > 0) {
                    data.forEach(function(item) {
                        html += `<div class="list-group-item">
                                    <div class="row align-items-center">
                                        <div class="col-md-2">
                                            <img src="${item.poster || 'https://via.placeholder.com/100x150'}" class="img-fluid rounded">
                                        </div>
                                        <div class="col-md-8">
                                            <strong>${item.title} (${item.year})</strong>
                                            <p class="mb-1 small">${item.overview ? item.overview.substring(0, 150) + '...' : ''}</p>
                                            <small class="text-muted">Status: ${item.status} | Is Added: ${item.isAdded}</small>
                                        </div>
                                        <div class="col-md-2 text-end">
                                            <button class="btn btn-sm btn-primary map-select-item-btn" data-media-id="${item.id}" data-instance-type="${instanceType}">
                                                Select
                                            </button>
                                        </div>
                                    </div>
                                </div>`;
                    });
                } else {
                    html = '<p class="text-warning">Aucun résultat trouvé.</p>';
                }
                resultsContainer.html(html);
            },
            error: function() {
                resultsContainer.html('<p class="text-danger">Erreur lors de la recherche.</p>');
            }
        });
    });
});
