// Fichier : app/search_ui/static/search_ui/js/search_actions.js
// Version : FINALE avec "meilleur candidat" et gestion de la réponse OBJET

$(document).ready(function() {
    console.log("Search actions (FINAL v3 - Best Match) script chargé.");

    const modalEl = $('#sonarrRadarrSearchModal');
    if (modalEl.length === 0) {
        console.error("Erreur critique: La modale #sonarrRadarrSearchModal est introuvable.");
        return;
    }
    const modal = new bootstrap.Modal(modalEl[0]);
    const modalBody = modalEl.find('.modal-body');
    const confirmBtn = modalEl.find('#confirm-map-btn');

    // --- FONCTION UTILITAIRE QUI RETOURNE LE HTML DE LA LISTE ---
    function getResultsListHtml(results, mediaType) {
        if (!results || results.length === 0) {
            return '<div id="lookup-results-list" class="alert alert-warning">Aucun résultat trouvé.</div>';
        }
        const itemsHtml = results.map(item => {
            // Ajoute la classe 'best-match' si l'item est marqué
            const bestMatchClass = item.is_best_match ? 'best-match' : '';
            return `
                <div class="list-group-item d-flex justify-content-between align-items-center ${bestMatchClass}" id="item-${item.tvdbId || item.tmdbId}">
                    <span><strong>${item.title}</strong> (${item.year})</span>
                    <button class="btn btn-sm btn-outline-primary enrich-details-btn"
                            data-media-id="${item.tvdbId || item.tmdbId}"
                            data-media-type="${mediaType}">
                        Voir les détails
                    </button>
                </div>
            `;
        }).join('');
        return `<div class="list-group list-group-flush" id="lookup-results-list">${itemsHtml}</div>`;
    }

    // --- GESTIONNAIRE PRINCIPAL : OUVRE LA MODALE ---
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseTitle = button.data('title');
        confirmBtn.data('guid', button.data('guid'));
        confirmBtn.data('downloadLink', button.data('download-link'));
        confirmBtn.data('indexerId', button.data('indexer-id'));
        confirmBtn.data('releaseTitle', releaseTitle);
        confirmBtn.prop('disabled', true);
        const mediaType = $('#search-form [name="media_type"]').val();
        if (!mediaType) { alert("Erreur: Type de média introuvable."); return; }

        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        modalBody.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche...</p></div>');
        modal.show();

        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: releaseTitle, media_type: mediaType })
        })
        .then(response => response.json())
        .then(data => {
            // 'data' est maintenant l'OBJET { results: [...], cleaned_query: "..." }
            const searchBarHtml = `
                <div class="manual-search-container mb-3" data-media-type="${mediaType}">
                    <div class="input-group">
                        <input type="text" id="manual-search-input" class="form-control" placeholder="Affiner la recherche..." value="${data.cleaned_query}">
                        <button id="manual-search-button" class="btn btn-secondary">Rechercher</button>
                    </div>
                </div>
            `;
            // On passe data.results à la fonction
            const resultsHtml = getResultsListHtml(data.results, mediaType);
            modalBody.html(searchBarHtml + resultsHtml);
        })
        .catch(error => {
            console.error("Erreur pendant la recherche lookup:", error);
            modalBody.html('<div class="alert alert-danger">Erreur de communication avec le serveur.</div>');
        });
    });
    
    // --- GESTIONNAIRE POUR LA RECHERCHE MANUELLE ---
    $('body').on('click', '#manual-search-button', function() {
        const button = $(this);
        const manualQuery = $('#manual-search-input').val();
        const searchContainer = $('.manual-search-container');
        const mediaType = searchContainer.data('media-type');
        const resultsList = $('#lookup-results-list');

        if (!manualQuery || !mediaType) { alert("Erreur: Terme ou type manquant."); return; }

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');
        resultsList.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div></div>');
        
        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: manualQuery, media_type: mediaType })
        })
        .then(response => response.json())
        .then(data => {
            // On passe data.results à la fonction
            const newResultsHtml = getResultsListHtml(data.results, mediaType);
            resultsList.replaceWith(newResultsHtml);
        })
        .catch(error => {
            console.error("Erreur recherche manuelle:", error);
            resultsList.replaceWith('<div id="lookup-results-list" class="alert alert-danger">Erreur de communication.</div>');
        })
        .finally(() => {
            button.prop('disabled', false).html('Rechercher');
        });
    });

    // ---- GESTIONNAIRE D'ENRICHISSEMENT (LAZY LOADING) ----
    $('body').on('click', '.enrich-details-btn', function() {
        const button = $(this);
        const mediaId = button.data('media-id');
        const mediaType = button.data('media-type');
        const itemContainer = button.closest('.list-group-item');
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        fetch('/search/api/enrich/details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: mediaId, media_type: mediaType })
        })
        .then(response => response.json())
        .then(details => {
            if (details.error) throw new Error(details.error);
            const cardHtml = `
                <div class="card enriched-card mb-2">
                    <div class="row g-0">
                        <div class="col-md-2 text-center align-self-center">
                            <img src="${details.poster || 'https://via.placeholder.com/150x225'}" class="img-fluid rounded-start" style="max-height: 150px;" alt="Poster">
                        </div>
                        <div class="col-md-10">
                            <div class="card-body py-2">
                                <h6 class="card-title mb-1">${details.title} (${details.year})</h6>
                                <p class="card-text small" style="max-height: 60px; overflow-y: auto;">${details.overview || 'Pas de description.'}</p>
                                <button class="btn btn-sm btn-success select-candidate-btn" data-media-id="${details.id}">✓ Sélectionner ce média</button>
                            </div>
                        </div>
                    </div>
                </div>`;
            itemContainer.replaceWith(cardHtml);
        })
        .catch(error => {
            console.error('Erreur enrichissement:', error);
            button.prop('disabled', false).html('Voir les détails');
        });
    });

    // ---- GESTIONNAIRE DE SÉLECTION FINALE ----
    $('body').on('click', '.select-candidate-btn', function() {
        const button = $(this);
        const mediaId = button.data('media-id');
        modalBody.find('.enriched-card').removeClass('border-primary border-3');
        button.closest('.enriched-card').addClass('border-primary border-3');
        confirmBtn.data('selectedMediaId', mediaId).prop('disabled', false);
    });

    // ---- GESTIONNAIRE DE CONFIRMATION FINALE ----
    $('body').on('click', '#confirm-map-btn', function() {
        const button = $(this);
        const data = button.data();
        const payload = { releaseName: data.releaseTitle, downloadLink: data.downloadLink, indexerId: data.indexerId, guid: data.guid, instanceType: data.mediaType, mediaId: data.selectedMediaId, actionType: 'add_then_map' };
        if (!payload.mediaId) { alert("Erreur : Aucun média n'a été sélectionné."); return; }
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Lancement...');
        fetch('/search/download-and-map', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success' || data.status === 'warning') {
                alert(data.message);
                modal.hide();
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