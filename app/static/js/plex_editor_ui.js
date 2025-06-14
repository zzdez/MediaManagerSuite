$(document).ready(function() {
    let ratingKeyToArchive = null;

    // 1. When an "Archive" button is clicked, populate the modal
    $('.archive-movie-btn').on('click', function() {
        ratingKeyToArchive = $(this).data('rating-key');
        const movieTitle = $(this).data('title');

        $('#archiveMovieModalTitle').text(movieTitle);
    });

    // 2. When the confirmation button inside the modal is clicked
    $('#confirmArchiveMovieBtn').on('click', function() {
        const btn = $(this);
        btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Archivage...');

        const options = {
            deleteFiles: $('#archiveDeleteFiles').is(':checked'),
            unmonitor: $('#archiveUnmonitor').is(':checked'),
            addTag: $('#archiveAddTag').is(':checked')
        };

        fetch('/plex/archive_movie', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                ratingKey: ratingKeyToArchive,
                options: options
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // Find the table row and fade it out
                $(`.archive-movie-btn[data-rating-key='${ratingKeyToArchive}']`).closest('tr').fadeOut(500, function() {
                    $(this).remove();
                });
                // You can add a toast notification here for better UX
                console.log('Success:', data.message);
            } else {
                alert('Erreur: ' + data.message); // Simple alert for now
                console.error('Error:', data.message);
            }
        })
        .catch(error => {
            alert('Erreur de communication avec le serveur.');
            console.error('Fetch Error:', error);
        })
        .finally(() => {
            // Reset button and hide modal
            btn.prop('disabled', false).html('Confirmer l\'archivage');
            const modal = bootstrap.Modal.getInstance(document.getElementById('archiveMovieModal'));
            modal.hide();
            ratingKeyToArchive = null;
        });
    });
});