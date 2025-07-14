// Fichier : app/static/js/search_actions.js
// Version : Lazy Loading (corrigée)

$(document).ready(function() {
    console.log("Search actions (Lazy Loading) script chargé.");

    const modalEl = $('#sonarrRadarrSearchModal');
    if (modalEl.length === 0) {
        console.error("Erreur critique: La modale #sonarrRadarrSearchModal est introuvable sur la page.");
        return;
    }
    const modal = new bootstrap.Modal(modalEl[0]);
    const modalBody = modalEl.find('.modal-body');
    const confirmBtn = modalEl.find('#confirm-map-btn');

    // ---- GESTIONNAIRE PRINCIPAL : Ouvre la modale de mapping ----
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseTitle = button.data('title');

        // Stocke les données du téléchargement sur le bouton de confirmation
        confirmBtn.data('guid', button.data('guid'));
        confirmBtn.data('downloadLink', button.data('download-link'));
        confirmBtn.data('indexerId', button.data('indexer-id'));
        confirmBtn.data('releaseTitle', releaseTitle);
        confirmBtn.prop('disabled', true); // Désactivé par défaut

        // Récupère le type de média (tv/movie) depuis le formulaire de recherche principal
        const mediaType = $('#search-form [name="media_type"]').val();
        if (!mediaType) {
            alert("Erreur: Impossible de déterminer le type de média (tv/movie) depuis le formulaire principal.");
            return;
        }
        confirmBtn.data('mediaType', mediaType);

        // Configure la modale et affiche un spinner
        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        modalBody.html('<div class="text-center p-4"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Recherche...</span></div><p class="mt-2">Recherche des correspondances...</p></div>');
        modal.show();

        // --- ÉTAPE 1 : APPEL RAPIDE À SONARR/RADARR ---
        // L'URL est préfixée par le blueprint '/search'
        const lookupUrl = '/search/api/search/lookup';
        console.log(`Appel de l'API Lookup : ${lookupUrl} avec le terme "${releaseTitle}" et type "${mediaType}"`);

        fetch(lookupUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: releaseTitle, media_type: mediaType })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`Erreur réseau (${response.status})`);
            }
            return response.json();
        })
        .then(results => {
            let resultsHtml = '';
            if (results && results.length > 0) {
                resultsHtml = results.map(item => `
                    <div class="list-group-item d-flex justify-content-between align-items-center" id="item-${item.tvdbId || item.tmdbId}">
                        <span><strong>${item.title}</strong> (${item.year})</span>
                        <button class="btn btn-sm btn-outline-primary enrich-details-btn"
                                data-media-id="${item.tvdbId || item.tmdbId}"
                                data-media-type="${mediaType}">
                            Voir les détails
                        </button>
                    </div>
                `).join('');
            } else {
                resultsHtml = '<div class="alert alert-warning">Aucun résultat trouvé dans Sonarr/Radarr.</div>';
            }
            modalBody.html(`<div class="list-group list-group-flush">${resultsHtml}</div>`);
        })
        .catch(error => {
            console.error("Erreur pendant la recherche lookup:", error);
            modalBody.html(`<div class="alert alert-danger">Erreur de communication avec le serveur pour la recherche. Vérifiez la console.</div>`);
        });
    });

    // ---- GESTIONNAIRE D'ENRICHISSEMENT (LAZY LOADING) ----
    $('body').on('click', '.enrich-details-btn', function() {
        const button = $(this);
        const mediaId = button.data('media-id');
        const mediaType = button.data('media-type');
        const itemContainer = button.closest('.list-group-item');

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>');

        // --- ÉTAPE 2 : APPEL LENT POUR ENRICHIR UN SEUL ITEM ---
        const enrichUrl = '/search/api/enrich/details';
        console.log(`Appel de l'API Enrich : ${enrichUrl} avec l'id "${mediaId}" et type "${mediaType}"`);

        fetch(enrichUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: mediaId, media_type: mediaType })
        })
        .then(response => response.json())
        .then(details => {
            if (details.error) {
                throw new Error(details.error);
            }
            const cardHtml = `
                <div class="card enriched-card mb-2">
                    <div class="row g-0">
                        <div class="col-md-2 text-center">
                            <img src="${details.poster || 'https://via.placeholder.com/150x225'}" class="img-fluid rounded-start" style="max-height: 150px;" alt="Poster">
                        </div>
                        <div class="col-md-10">
                            <div class="card-body py-2">
                                <h6 class="card-title mb-1">${details.title} (${details.year})</h6>
                                <p class="card-text small" style="max-height: 60px; overflow: hidden;">${details.overview ? details.overview : 'Pas de description.'}</p>
                                <button class="btn btn-sm btn-success select-candidate-btn" data-media-id="${details.id}">
                                    ✓ Sélectionner ce média
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
            itemContainer.replaceWith(cardHtml);
        })
        .catch(error => {
            console.error('Erreur pendant l\'enrichissement:', error);
            button.parent().append(`<span class="text-danger small ms-2">Erreur</span>`);
            button.prop('disabled', false).html('Voir les détails');
        });
    });

    // ---- GESTIONNAIRE DE SÉLECTION FINALE ----
    $('body').on('click', '.select-candidate-btn', function() {
        const button = $(this);
        const mediaId = button.data('media-id');

        $('.enriched-card').removeClass('border-primary border-3');
        button.closest('.enriched-card').addClass('border-primary border-3');

        confirmBtn.data('selectedMediaId', mediaId).prop('disabled', false);
    });

    // ---- GESTIONNAIRE DE CONFIRMATION FINALE ----
    $('body').on('click', '#confirm-map-btn', function() {
        const button = $(this);
        const data = button.data();

        const payload = {
            releaseName: data.releaseTitle,
            downloadLink: data.downloadLink,
            indexerId: data.indexerId,
            guid: data.guid,
            instanceType: data.mediaType,
            mediaId: data.selectedMediaId,
            actionType: 'add_then_map' // Action par défaut
        };

        if (!payload.mediaId) {
            alert("Erreur : Aucun média n'a été sélectionné.");
            return;
        }

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Lancement...');

        // L'URL est préfixée par le blueprint '/search'
        const finalUrl = '/search/download-and-map';

        fetch(finalUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success' || data.status === 'warning') {
                alert(data.message);
                modal.hide();
                // Optionnel : supprimer la ligne de la recherche principale
                $(`.download-and-map-btn[data-guid="${payload.guid}"]`).closest('tr').fadeOut();
            } else {
                alert('Erreur: ' + (data.message || "Une erreur inconnue est survenue."));
                button.prop('disabled', false).html('Confirmer le Mapping');
            }
        })
        .catch(error => {
            console.error('Erreur Fetch finale:', error);
            alert('Erreur de communication majeure avec le serveur.');
            button.prop('disabled', false).html('Confirmer le Mapping');
        });
    });
});
