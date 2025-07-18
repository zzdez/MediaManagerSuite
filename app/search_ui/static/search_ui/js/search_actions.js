// Fichier : app/search_ui/static/search_ui/js/search_actions.js
// Version : Architecture Unifiée

$(document).ready(function() {
    console.log("Search actions (UNIFIED ARCHITECTURE) script chargé.");

    const modalEl = $('#sonarrRadarrSearchModal');
    const modalBody = modalEl.find('.modal-body');

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

        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        modalBody.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div></div>');
        new bootstrap.Modal(modalEl[0]).show();

        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: releaseTitle, media_type: mediaType })
        })
        .then(response => response.json())
        .then(data => {
            const idPlaceholder = mediaType === 'tv' ? 'ID TVDB...' : 'ID TMDb...';
            const modalHtml = `
                <div data-media-type="${mediaType}">
                    <h6>Recherche par Titre</h6>
                    <div class="input-group mb-2">
                        <input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}">
                    </div>
                    <div class="text-center text-muted my-2 small">OU</div>
                    <h6>Recherche par ID</h6>
                    <div class="input-group mb-3">
                        <input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}">
                    </div>
                    <button id="unified-search-button" class="btn btn-primary w-100">Rechercher</button>
                    <hr>
                    <div id="lookup-results-container"></div>
                </div>
            `;
            modalBody.html(modalHtml);
            displayResults(data.results, mediaType);
        });
    });

    // --- GESTIONNAIRE DE LA RECHERCHE UNIFIÉE ---
    $('body').on('click', '#unified-search-button', function() {
        const button = $(this);
        const mediaType = button.closest('[data-media-type]').data('media-type');
        const titleQuery = $('#manual-search-input').val();
        const idQuery = $('#manual-id-input').val();

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

        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            displayResults(data.results, mediaType);
        });
    });

    // --- AUTRES GESTIONNAIRES (Enrichissement, Sélection, etc.) ---
    // Ils devraient continuer à fonctionner car ils sont attachés au 'body'
});
