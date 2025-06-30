$(document).ready(function() {
    console.log("Search actions script loaded.");

    // --- [1] Logique pour le bouton "Télécharger & Mapper" (Ouvre la modale) ---
    $('body').on('click', '.download-and-map-btn', function(e) {
        e.preventDefault();
        console.log("Bouton 'Télécharger & Mapper' cliqué !");

        const modalElement = $('#sonarrRadarrSearchModal'); // Use jQuery selector

        // Stocker les données sur la modale pour les retrouver plus tard
        modalElement.data('releaseTitle', $(this).data('release-title'));
        modalElement.data('downloadLink', $(this).data('download-link'));

        // Pré-remplir le champ de recherche
        modalElement.find('#sonarrRadarrQuery').val($(this).data('parsed-title') || '');

        // Réinitialiser les résultats et le titre
        modalElement.find('#sonarrRadarrModalLabel').text(`Mapper : ${$(this).data('release-title')}`);
        // IMPORTANT: The HTML for sonarrRadarrSearchModal must have its results div ID changed to 'prowlarrModalSearchResults'
        modalElement.find('#prowlarrModalSearchResults').empty().html('<p class="text-muted text-center">Effectuez une recherche pour trouver un média à associer.</p>');

        modalElement.modal('show'); // Use Bootstrap 3/4 style
    });

    // --- [2] Logique pour le bouton "Rechercher" DANS la modale ---
    $('body').on('click', '#executeSonarrRadarrSearch', function(e) {
        // e.stopPropagation(); // Temporarily removed for testing
        console.log("Recherche dans la modale DÉCLENCHÉE !");

        const query = $('#sonarrRadarrQuery').val();
        const mediaType = $('input[name="mapInstanceType"]:checked').val();
        // IMPORTANT: Ensure the modal HTML's results div ID is updated to 'prowlarrModalSearchResults'
        const resultsContainer = $('#prowlarrModalSearchResults');

        if (!query) {
            resultsContainer.html('<p class="text-danger text-center">Veuillez entrer un terme de recherche.</p>');
            return;
        }

        resultsContainer.html('<div class="d-flex justify-content-center align-items-center"><div class="spinner-border text-info" role="status"></div><strong class="ms-2">Recherche...</strong></div>');

        $.ajax({
            url: '/search/api/search-arr',
            type: 'GET',
            data: { query: query, type: mediaType },
            success: function(data) {
                resultsContainer.empty();
                if (data && data.length > 0) {
                    const list = $('<div class="list-group"></div>');
                    data.forEach(function(item) {
                        const year = item.year || '';
                        const title = item.title || 'Titre inconnu';
                        const id = item.id || item.tvdbId || item.tmdbId;

                        const itemHtml = `
                            <button type="button" class="list-group-item list-group-item-action map-select-item-btn"
                                    data-media-id="${id}"
                                    data-media-title="${title.replace(/"/g, '&quot;')}"
                                    data-instance-type="${mediaType}"
                                    data-year="${year}">
                                <strong>${title}</strong> (${year})
                            </button>`;
                        list.append(itemHtml);
                    });
                    resultsContainer.append(list);
                } else {
                    resultsContainer.html('<p class="text-warning text-center">Aucun résultat trouvé.</p>');
                }
            },
            error: function(jqXHR) {
                const errorMsg = jqXHR.responseJSON ? jqXHR.responseJSON.error : "Erreur de communication.";
                resultsContainer.html(`<p class="text-danger text-center">Erreur: ${errorMsg}</p>`);
            }
        });
    });

    // --- [3] Logique pour le clic sur un résultat DANS la modale ---
    $('body').on('click', '.map-select-item-btn', function(e) {
        e.stopPropagation(); // <-- AJOUTER CETTE LIGNE

        const button = $(this);
        const mediaId = button.data('media-id');
        const mediaType = button.data('media-type');
        const mediaTitle = button.data('media-title');
        const mediaYear = button.data('year');

        const modal = $('#sonarrRadarrSearchModal');
        const releaseTitle = modal.data('releaseTitle');
        const downloadLink = modal.data('downloadLink');

        if (!mediaId || !mediaType || !releaseTitle || !downloadLink) {
            alert("Erreur critique : une information essentielle est manquante.");
            return;
        }

        button.closest('.list-group').find('.map-select-item-btn').prop('disabled', true);
        button.html('<span class="spinner-border spinner-border-sm" role="status"></span> Lancement...');

        fetch('/search/download-and-map', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                releaseName: releaseTitle,
                downloadLink: downloadLink,
                instanceType: mediaType,
                mediaId: mediaId
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
            button.html(`<strong>${mediaTitle}</strong> (${mediaYear})`); // Restaurer le texte
        });
    });

});
