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
});
