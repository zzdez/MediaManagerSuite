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
});
