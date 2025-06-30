$(document).ready(function() {
    console.log("Search actions script loaded.");

    // Logique pour l'onglet "Recherche Libre"
    $('#prowlarr-search-form').on('submit', function(e) {
        const query = $(this).find('input[name="query"]').val();
        if (!query.trim()) {
            e.preventDefault();
            return false;
        }
        $('#search-button')
            .prop('disabled', true)
            .html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Recherche...');
    });

    // --- Logique pour le bouton "Télécharger & Mapper" (Ouvre la modale) ---
    $('body').on('click', '.download-and-map-btn', function(e) {
        e.preventDefault();
        console.log("Bouton 'Télécharger & Mapper' cliqué !");

        const releaseTitle = $(this).data('release-title');
        const downloadLink = $(this).data('download-link');
        const parsedTitle = $(this).data('parsed-title');

        if (!releaseTitle || !downloadLink) {
            alert("Erreur : Données de la release manquantes sur le bouton.");
            return;
        }
        
        const modalElement = document.getElementById('sonarrRadarrSearchModal');
        if (!modalElement) {
            console.error("Erreur critique: La modale #sonarrRadarrSearchModal n'a pas été trouvée.");
            alert("Erreur : Le composant de recherche n'a pas pu être chargé.");
            return;
        }
        
        const modalInstance = new bootstrap.Modal(modalElement);
        
        $(modalElement).data('releaseTitle', releaseTitle);
        $(modalElement).data('downloadLink', downloadLink);
        
        $(modalElement).find('#sonarrRadarrModalLabel').text(`Mapper : ${releaseTitle}`);
        $(modalElement).find('#sonarrRadarrQuery').val(parsedTitle || '');
        $(modalElement).find('#sonarrRadarrResults').empty().html('<p class="text-muted text-center">Effectuez une recherche pour trouver un média à associer.</p>');
        
        modalInstance.show();
        
        setTimeout(function() {
            $(modalElement).find('#sonarrRadarrQuery').focus();
        }, 500);
    });

    // --- Logique pour le bouton "Rechercher" DANS la modale ---
    $('body').on('click', '#executeSonarrRadarrSearch', function(e) { // <-- (1) On ajoute 'e' ici
        e.stopPropagation(); // <-- (2) On arrête la propagation de l'événement !
        
        console.log("Recherche dans la modale DÉCLENCHÉE !"); 
        
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
                                    data-media-title="${title.replace(/"/g, '"')}"
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