$(document).ready(function() {
    console.log("Search actions script loaded.");

    function displayLookupResults(results, mediaType) {
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
            resultsHtml = '<div class="alert alert-warning">Aucun résultat trouvé.</div>';
        }
        return `<div class="list-group list-group-flush" id="lookup-results-list">${resultsHtml}</div>`;
    }

    // --- [1] Logique pour le bouton "Télécharger & Mapper" (Ouvre la modale) ---
    $('body').on('click', '.download-and-map-btn', function(e) {
        e.preventDefault();
        console.log("Bouton 'Télécharger & Mapper' cliqué !");

        const modalElement = $('#sonarrRadarrSearchModal'); // Use jQuery selector
        const modalBody = modalElement.find('.modal-body');
        const confirmBtn = modalElement.find('#confirm-map-btn');

        // Stocker les données sur la modale pour les retrouver plus tard
        const releaseTitle = $(this).data('release-title');
        const downloadLink = $(this).data('download-link');
        const mediaType = $('input[name="mapInstanceType"]:checked').val();

        modalElement.data('releaseTitle', releaseTitle);
        modalElement.data('downloadLink', downloadLink);
        confirmBtn.data('mediaType', mediaType);


        // Pré-remplir le champ de recherche
        modalElement.find('#sonarrRadarrQuery').val($(this).data('parsed-title') || '');

        // Réinitialiser les résultats et le titre
        modalElement.find('#sonarrRadarrModalLabel').text(`Mapper : ${releaseTitle}`);

        modalBody.html('<div class="d-flex justify-content-center align-items-center"><div class="spinner-border text-info" role="status"></div><strong class="ms-2">Recherche...</strong></div>');

        modalElement.modal('show'); // Use Bootstrap 3/4 style

        fetch('/search/api/search-arr', {
            method: 'GET',
            headers: { 'Content-Type': 'application/json' },

        })
        .then(response => response.json())
        .then(results => {
            const initialQuery = releaseTitle; // releaseTitle est disponible dans ce scope
            const searchBarHtml = `
                <div class="manual-search-container mb-3">
                    <div class="input-group">
                        <input type="text" id="manual-search-input" class="form-control" placeholder="Affiner la recherche..." value="${initialQuery}">
                        <button id="manual-search-button" class="btn btn-secondary">Rechercher</button>
                    </div>
                </div>
            `;
            const resultsHtml = displayLookupResults(results, mediaType); // mediaType est disponible
            modalBody.html(searchBarHtml + resultsHtml);
        })
    });

    // ---- GESTIONNAIRE POUR LA RECHERCHE MANUELLE ----
    $('body').on('click', '#manual-search-button', function() {
        const button = $(this);
        const manualQuery = $('#manual-search-input').val();
        const confirmBtn = $('#sonarrRadarrSearchModal').find('#confirm-map-btn');
        const mediaType = confirmBtn.data('mediaType'); // Récupère le type de média
        const resultsContainer = $('#lookup-results-list');

        if (!manualQuery) {
            alert("Veuillez entrer un terme à rechercher.");
            return;
        }

        // Affiche un spinner et désactive le bouton
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');
        resultsContainer.html('<div class="text-center p-4"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Recherche...</span></div></div>');

        const lookupUrl = '/search/api/search/lookup';

        fetch(lookupUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: manualQuery, media_type: mediaType })
        })
        .then(response => response.json())
        .then(results => {
            const resultsHtml = displayLookupResults(results, mediaType);
            resultsContainer.replaceWith(resultsHtml); // Remplace seulement la liste
        })
        .catch(error => {
            console.error("Erreur pendant la recherche manuelle:", error);
            resultsContainer.html('<div class="alert alert-danger">Erreur de communication avec le serveur.</div>');
        })
        .finally(() => {
            // Réactive le bouton
            button.prop('disabled', false).html('Rechercher');
        });
    });
});
