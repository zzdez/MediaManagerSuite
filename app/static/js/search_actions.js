// Fichier : app/search_ui/static/search_ui/js/search_actions.js
// Version : Architecture Unifiée Finale

$(document).ready(function() {
    console.log("Search actions (UNIFIED ARCHITECTURE) script chargé.");

    const modalEl = $('#sonarrRadarrSearchModal');
    const modalBody = modalEl.find('.modal-body');
    const confirmBtn = modalEl.find('#confirm-map-btn'); // Gardé pour les actions futures

    // --- FONCTION UTILITAIRE POUR AFFICHER LES RÉSULTATS ---
    function displayResults(resultsData, mediaType) {
        const resultsContainer = modalBody.find('#lookup-results-container');
        let itemsHtml = '';
        if (resultsData && resultsData.length > 0) {
            itemsHtml = resultsData.map(item => {
                const bestMatchClass = item.is_best_match ? 'best-match' : '';
                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center ${bestMatchClass}">
                        <span><strong>${item.title}</strong> (${item.year})</span>
                        <button class="btn btn-sm btn-outline-primary enrich-details-btn" data-media-id="${item.tvdbId || item.tmdbId}" data-media-type="${mediaType}">
                            Voir les détails
                        </button>
                    </div>
                `;
            }).join('');
        } else {
            itemsHtml = '<div class="alert alert-info mt-3">Aucun résultat trouvé.</div>';
        }
        resultsContainer.html(`<div class="list-group list-group-flush">${itemsHtml}</div>`);
    }

    // --- GESTIONNAIRE PRINCIPAL : OUVRE ET CONSTRUIT LA MODALE ---
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseTitle = button.data('title');
        const mediaType = $('#search-form [name="media_type"]').val();
        
        // Stocke les données initiales sur le bouton de confirmation final
        confirmBtn.data('guid', button.data('guid'));
        confirmBtn.data('downloadLink', button.data('download-link'));
        confirmBtn.data('indexerId', button.data('indexer-id'));
        confirmBtn.data('releaseTitle', releaseTitle);
        confirmBtn.prop('disabled', true);

        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        modalBody.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche initiale...</p></div>');
        new bootstrap.Modal(modalEl[0]).show();

        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: releaseTitle, media_type: mediaType })
        })
        .then(response => response.json())
        .then(data => {
            const idPlaceholder = mediaType === 'tv' ? 'Rechercher par ID TVDB...' : 'Rechercher par ID TMDb...';
            const modalHtml = `
                <div data-media-type="${mediaType}">
                    <label for="manual-search-input" class="form-label small">Recherche par Titre</label>
                    <div class="input-group mb-2">
                        <input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}">
                    </div>
                    <div class="text-center text-muted my-2 small text-uppercase">ou</div>
                    <label for="manual-id-input" class="form-label small">Recherche par ID</label>
                    <div class="input-group mb-3">
                        <input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}">
                    </div>
                    <button id="unified-search-button" class="btn btn-primary w-100"><i class="fas fa-search"></i> Lancer la recherche</button>
                    <hr>
                    <div id="lookup-results-container"></div>
                </div>
            `;
            modalBody.html(modalHtml);
            displayResults(data.results, mediaType);
        })
        .catch(error => {
            console.error("Erreur pendant la recherche lookup:", error);
            modalBody.html('<div class="alert alert-danger">Erreur de communication avec le serveur.</div>');
        });
    });

    // --- GESTIONNAIRE DE LA RECHERCHE UNIFIÉE ---
    $('body').on('click', '#unified-search-button', function() {
        const button = $(this);
        const container = button.closest('[data-media-type]');
        const mediaType = container.data('media-type');
        const titleQuery = container.find('#manual-search-input').val();
        const idQuery = container.find('#manual-id-input').val();
        
        let payload = { media_type: mediaType };
        if (idQuery) {
            payload.media_id = idQuery;
        } else if (titleQuery) {
            payload.term = titleQuery;
        } else {
            alert("Veuillez entrer un titre ou un ID.");
            return;
        }

        const resultsContainer = modalBody.find('#lookup-results-container');
        resultsContainer.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div></div>');
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Recherche...');

        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            displayResults(data.results, mediaType);
        })
        .catch(error => {
            console.error("Erreur recherche unifiée:", error);
            resultsContainer.html('<div class="alert alert-danger">Erreur de communication.</div>');
        })
        .finally(() => {
            button.prop('disabled', false).html('<i class="fas fa-search"></i> Lancer la recherche');
        });
    });
    
    // --- GESTIONNAIRES EXISTANTS ---
    // Le code ci-dessous est identique aux versions précédentes et doit être conservé.

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
        const payload = { releaseName: data.releaseTitle, downloadLink: data.downloadLink, indexerId: data.indexerId, guid: data.guid, instanceType: button.closest('.modal-content').find('[data-media-type]').data('media-type'), mediaId: data.selectedMediaId, actionType: 'add_then_map' };
        if (!payload.mediaId) { alert("Erreur : Aucun média n'a été sélectionné."); return; }
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Lancement...');
        fetch('/search/download-and-map', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success' || data.status === 'warning') {
                alert(data.message);
                new bootstrap.Modal(modalEl[0]).hide();
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