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

    // --- Logique pour le bouton "Télécharger & Mapper" ---
    // Nouveau code pour le gestionnaire de clic
    $('body').on('click', '.download-and-map-btn', function(e) {
        e.preventDefault();
        console.log("Bouton 'Télécharger & Mapper' cliqué !");

        // On récupère TOUTES les données du bouton
        const releaseTitle = $(this).data('release-title');
        const downloadLink = $(this).data('download-link');
        const parsedTitle = $(this).data('parsed-title'); // <-- LA NOUVELLE DONNÉE

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
        
        // Attache les données à l'élément DOM de la modale pour les retrouver plus tard
        $(modalElement).data('releaseTitle', releaseTitle);
        $(modalElement).data('downloadLink', downloadLink);
        
        // Réinitialise et PRÉ-REMPLIT le contenu de la modale
        $(modalElement).find('#sonarrRadarrModalLabel').text(`Mapper : ${releaseTitle}`);
        $(modalElement).find('#sonarrRadarrQuery').val(parsedTitle || ''); // <-- ON PRÉ-REMPLIT ICI
        $(modalElement).find('#sonarrRadarrResults').empty().html('<p class="text-muted text-center">Effectuez une recherche pour trouver un média à associer.</p>');
        
        // Affiche la modale
        modalInstance.show();
        
        // Met le focus sur le champ de recherche
        setTimeout(function() {
            $(modalElement).find('#sonarrRadarrQuery').focus();
        }, 500);
    });
});