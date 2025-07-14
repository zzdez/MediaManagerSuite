// static/js/search_actions.js

$(document).ready(function() {
    console.log("Search actions script loaded (Lazy Loading version).");

    const modalEl = $('#sonarrRadarrSearchModal');
    const modal = new bootstrap.Modal(modalEl[0]);

    // ---- GESTIONNAIRE PRINCIPAL : OUVRE LA MODALE DE MAPPING ----
    $('body').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseTitle = button.data('title');
        const guid = button.data('guid');
        const downloadLink = button.data('download-link');
        const indexerId = button.data('indexer-id');

        // Récupère le type de média depuis le formulaire principal de recherche
        const mediaType = $('#search-form-media-type').val();
        if (!mediaType) {
            console.error("Impossible de déterminer le media_type. Assurez-vous d'avoir un input avec l'id #search-form-media-type sur la page.");
            alert("Erreur: Type de média (tv/movie) non trouvé.");
            return;
        }

        // Configure et affiche la modale
        modalEl.find('.modal-title').text(`Mapper : ${releaseTitle}`);
        const modalBody = modalEl.find('.modal-body');
        const confirmBtn = $('#confirm-map-btn');

        // Stocke les données du téléchargement sur le bouton de confirmation
        confirmBtn.data({
            guid: guid,
            downloadLink: downloadLink,
            indexerId: indexerId,
            releaseTitle: releaseTitle,
            mediaType: mediaType
        }).prop('disabled', true);

        modal.show();
        modalBody.html('<div class="text-center"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Recherche...</span></div><p>Recherche des correspondances...</p></div>');

        // --- ÉTAPE 1 : APPEL RAPIDE À SONARR/RADARR ---
        fetch('/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: releaseTitle, media_type: mediaType })
        })
        .then(response => response.json())
        .then(results => {
            if (results.length > 0) {
                const resultsHtml = results.map(item => `
                    <div class="list-group-item d-flex justify-content-between align-items-center simple-result-item" id="item-${item.tvdbId || item.tmdbId}">
                        <div>
                            <strong>${item.title}</strong> (${item.year})
                        </div>
                        <button class="btn btn-sm btn-outline-primary enrich-details-btn"
                                data-media-id="${item.tvdbId || item.tmdbId}"
                                data-media-type="${mediaType}">
                            Voir les détails
                        </button>
                    </div>
                `).join('');
                modalBody.html(`<div class="list-group">${resultsHtml}</div>`);
            } else {
                modalBody.html('<div class="alert alert-warning">Aucun résultat trouvé dans Sonarr/Radarr.</div>');
            }
        })
        .catch(error => {
            console.error("Error during initial lookup:", error);
            modalBody.html('<div class="alert alert-danger">Erreur de communication avec le serveur pour la recherche.</div>');
        });
    });

    // ---- GESTIONNAIRE D'ENRICHISSEMENT (LAZY LOADING) ----
    $('body').on('click', '.enrich-details-btn', function() {
        const button = $(this);
        const mediaId = button.data('media-id');
        const mediaType = button.data('media-type');
        const itemContainer = button.parent();

        // Affiche un spinner sur la ligne
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Chargement...');

        // --- ÉTAPE 2 : APPEL LENT POUR ENRICHIR UN SEUL ITEM ---
        fetch('/api/enrich/details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: mediaId, media_type: mediaType })
        })
        .then(response => response.json())
        .then(details => {
            const cardHtml = `
                <div class="card enriched-card">
                    <div class="row g-0">
                        <div class="col-md-2">
                            <img src="${details.poster || 'https://via.placeholder.com/150x225'}" class="img-fluid rounded-start" alt="Poster">
                        </div>
                        <div class="col-md-10">
                            <div class="card-body">
                                <h5 class="card-title">${details.title} (${details.year})</h5>
                                <p class="card-text small">${details.overview ? details.overview.substring(0, 200) + '...' : 'Pas de description.'}</p>
                                <p class="card-text"><small class="text-muted">Statut : ${details.status || 'Inconnu'}</small></p>
                                <button class="btn btn-success select-candidate-btn" data-media-id="${details.id}">
                                    ✓ Sélectionner ce média
                                </button>
                            </div>
                        </div>
                    </div>
                </div>`;
            itemContainer.replaceWith(cardHtml);
        })
        .catch(error => {
            console.error('Error fetching enrichment details:', error);
            button.replaceWith('<span class="text-danger">Erreur de chargement</span>');
        });
    });

    // ---- GESTIONNAIRE DE SÉLECTION FINALE ----
    $('body').on('click', '.select-candidate-btn', function() {
        const button = $(this);
        const mediaId = button.data('media-id');

        // Highlight
        $('.enriched-card').removeClass('border-primary border-3');
        button.closest('.enriched-card').addClass('border-primary border-3');

        // Stocke l'ID sélectionné et active le bouton de confirmation
        $('#confirm-map-btn').data('selectedMediaId', mediaId).prop('disabled', false);
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
            mediaId: data.selectedMediaId, // Utilise l'ID stocké
            actionType: 'add_then_map'
        };

        if (!payload.mediaId) {
            alert("Erreur : Aucun média n'a été sélectionné.");
            return;
        }

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Lancement...');

        fetch('/search/download-and-map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert(data.message);
                modal.hide();
                // Optionnel : supprimer la ligne de la recherche principale
                $(`.download-and-map-btn[data-guid="${payload.guid}"]`).closest('tr').remove();
            } else {
                alert('Erreur: ' + data.message);
                button.prop('disabled', false).html('Confirmer le Mapping');
            }
        })
        .catch(error => {
            console.error('Erreur Fetch:', error);
            alert('Erreur de communication avec le serveur.');
            button.prop('disabled', false).html('Confirmer le Mapping');
        });
    });

    // Note : La recherche manuelle dans la modale via `#executeSonarrRadarrSearch` a été retirée
    // car la nouvelle logique de pré-mapping la rend redondante. La modale s'ouvre maintenant
    // directement avec les résultats pertinents.
});
