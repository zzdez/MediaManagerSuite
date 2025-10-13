$(document).ready(function() {
    console.log("Search UI script loaded.");

    $('#prowlarr-search-form').on('submit', function(e) {
        // On intercepte la soumission du formulaire
        console.log("Form submission intercepted.");

        const query = $('#prowlarr-search-form input[name="query"]').val();
        if (!query.trim()) {
            // Si la recherche est vide, on empêche l'envoi
            console.log("Search query is empty. Preventing submission.");
            e.preventDefault();
            return false;
        }

        // Affiche un état de chargement pour indiquer que la recherche est en cours
        $('#search-button')
            .prop('disabled', true)
            .html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Recherche...');

        // On laisse le formulaire se soumettre normalement (pas de e.preventDefault() ici)
        console.log("Form submission allowed to proceed.");
    });
});
