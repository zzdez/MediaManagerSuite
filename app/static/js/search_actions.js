// Dans search_actions.js

$(document).ready(function() {
    console.log("Search actions script loaded. (Version corrigée)");

    // GESTIONNAIRE POUR LE BOUTON "& MAPPER"
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseTitle = button.data('title');
        const guid = button.data('guid');
        const downloadLink = button.data('download-link');
        const indexerId = button.data('indexer-id');

        const modalEl = $('#sonarrRadarrSearchModal');
        const modalBody = modalEl.find('.modal-body');
        const confirmBtn = $('#confirm-map-btn');

        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        modalBody.html('<div class="d-flex justify-content-center"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div></div>');
        confirmBtn.prop('disabled', true);

        confirmBtn.data('guid', guid);
        confirmBtn.data('downloadLink', downloadLink);
        confirmBtn.data('indexerId', indexerId);
        confirmBtn.data('releaseTitle', releaseTitle);

        const myModal = new bootstrap.Modal(modalEl[0]);
        myModal.show();

        fetch("/api/prepare_mapping_details", {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: releaseTitle })
        })
        .then(response => response.text())
        .then(html => {
            modalBody.html(html);
        })
        .catch(error => {
            console.error("Error fetching mapping details:", error);
            modalBody.html('<div class="alert alert-danger">Erreur de communication avec le serveur.</div>');
        });
    });

    // GESTIONNAIRE POUR LE BOUTON "SELECT" DANS LA MODALE
    $('body').on('click', '.select-candidate-btn', function() {
        const button = $(this);
        const mediaId = button.data('media-id');
        const title = button.data('title');

        // Highlight the selected card
        $('.card').removeClass('border-primary');
        button.closest('.card').addClass('border-primary');

        // Store the selected media ID on the confirm button
        $('#confirm-map-btn').data('media-id', mediaId).prop('disabled', false);
    });

    // GESTIONNAIRE POUR LE BOUTON "CONFIRMER" DANS LA MODALE
    $('body').on('click', '#confirm-map-btn', function() {
        const button = $(this);
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Lancement...');

        const releaseTitle = button.data('releaseTitle');
        const downloadLink = button.data('downloadLink');
        const guid = button.data('guid');
        const indexerId = button.data('indexerId');
        const mediaId = button.data('media-id');
        const instanceType = $('#media_type').val();

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
