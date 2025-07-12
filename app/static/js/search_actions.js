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

        const modalEl = $('#intelligent-mapping-modal');
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

        modalEl.modal('show'); // Ouvre la NOUVELLE modale

        // Appelle la NOUVELLE route d'enrichissement
        fetch("/search/api/prepare_mapping_details", {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: releaseTitle })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) throw new Error(data.error);

            // Remplit le contenu
            const posterHtml = data.remotePoster ? `<img src="${data.remotePoster}" class="img-fluid rounded">` : '';
            content.html(`<div class="row"><div class="col-md-3">${posterHtml}</div><div class="col-md-9"><h4>${data.title} (${data.year})</h4><p>${data.overview}</p></div></div>`);

            confirmBtn.data('arr-id', data.id); // Stocke l'ID Sonarr/Radarr
            loader.hide();
            content.removeClass('d-none');
            confirmBtn.prop('disabled', false);
        })
        .catch(error => {
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
                $('#intelligent-mapping-modal').modal('hide');
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
});
