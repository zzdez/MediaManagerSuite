$(document).ready(function() {
    // Utiliser la délégation d'événement sur un conteneur parent stable
    $('#free-search').on('click', '.download-and-map-btn', function() {
        const releaseTitle = $(this).data('release-title');
        const downloadLink = $(this).data('download-link');

        // On stocke ces infos dans la modale pour les récupérer plus tard
        $('#sonarrRadarrSearchModal').data('releaseTitle', releaseTitle);
        $('#sonarrRadarrSearchModal').data('downloadLink', downloadLink);

        // On réinitialise et on ouvre la modale de recherche (qui existe déjà)
        $('#sonarrRadarrSearchModal').modal('show');
        $('#sonarrRadarrQuery').val('').focus();
        $('#sonarrRadarrResults').empty();
        $('#sonarrRadarrModalLabel').text(`Mapper et Télécharger : ${releaseTitle}`);
    });

    // Nouveau gestionnaire d'événements pour le bouton #executeSonarrRadarrSearch
    $('body').on('click', '#executeSonarrRadarrSearch', function() {
        const query = $('#sonarrRadarrQuery').val();
        const mediaType = $('input[name="mapInstanceType"]:checked').val();
        const resultsContainer = $('#sonarrRadarrResults');

        if (!query) {
            resultsContainer.html('<p class="text-danger text-center">Veuillez entrer un terme de recherche.</p>');
            return;
        }

        resultsContainer.html('<div class="d-flex justify-content-center align-items-center"><div class="spinner-border text-info" role="status"><span class="visually-hidden">Loading...</span></div><strong class="ms-2">Recherche en cours...</strong></div>');

        $.ajax({
            url: '/search/api/search-arr',
            type: 'GET',
            data: {
                query: query,
                type: mediaType
            },
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
                                    data-media-type="${mediaType}">
                                <strong>${title}</strong> (${year})
                            </button>
                        `;
                        list.append(itemHtml);
                    });
                    resultsContainer.append(list);
                } else {
                    resultsContainer.html('<p class="text-warning text-center">Aucun résultat trouvé.</p>');
                }
            },
            error: function(jqXHR, textStatus, errorThrown) {
                console.error("Erreur AJAX:", textStatus, errorThrown);
                const errorMsg = jqXHR.responseJSON ? jqXHR.responseJSON.error : "Une erreur est survenue.";
                resultsContainer.html(`<p class="text-danger text-center">Erreur: ${errorMsg}</p>`);
            }
        });
    });

    // Ajoute ce bloc dans $(document).ready(...)
    $('body').on('click', '.map-select-item-btn', function() {
        const button = $(this);
        const mediaId = button.data('media-id');
        const mediaType = button.data('media-type');
        const mediaTitle = button.data('media-title'); // Already escaped with &quot; if needed

        const modal = $('#sonarrRadarrSearchModal');
        const releaseTitle = modal.data('releaseTitle');
        const downloadLink = modal.data('downloadLink');

        if (!mediaId || !mediaType || !releaseTitle || !downloadLink) {
            alert("Erreur critique : une information essentielle est manquante pour le mapping et téléchargement.");
            console.error("Données manquantes:", { mediaId, mediaType, mediaTitle, releaseTitle, downloadLink });
            return;
        }

        // Disable all buttons in the list and show spinner on the clicked one
        button.closest('.list-group').find('.map-select-item-btn').prop('disabled', true);
        button.html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Lancement...');

        fetch('/search/download-and-map', { // Corrected URL from your initial prompt
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
                alert(data.message); // Or use a more sophisticated notification
                modal.modal('hide');
            } else {
                alert('Erreur: ' + (data.message || "Une erreur inconnue est survenue."));
                // Re-enable buttons and restore text only on error
                button.closest('.list-group').find('.map-select-item-btn').prop('disabled', false);
                // Restore original button text (important: use the stored mediaTitle)
                // The original HTML was <strong>${title}</strong> (${year}), but we only have mediaTitle here.
                // For simplicity, just using mediaTitle. If year is needed, it should also be stored or passed.
                button.html(`<strong>${mediaTitle}</strong>`);
            }
        })
        .catch(error => {
            console.error('Erreur Fetch:', error);
            alert('Erreur de communication avec le serveur lors du lancement du téléchargement.');
            button.closest('.list-group').find('.map-select-item-btn').prop('disabled', false);
            button.html(`<strong>${mediaTitle}</strong>`);
        });
    });
});
