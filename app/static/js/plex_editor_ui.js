$(document).ready(function() {
    
    // =================================================================
    // ### LOGIQUE POUR L'ARCHIVAGE DES FILMS (TON CODE EXISTANT) ###
    // =================================================================
    let ratingKeyToArchive = null;

    // 1. Quand un bouton "Archive Movie" est cliqué
    $('.archive-movie-btn').on('click', function() {
        ratingKeyToArchive = $(this).data('rating-key');
        const movieTitle = $(this).data('title');
        $('#archiveMovieModalTitle').text(movieTitle);
    });

    // 2. Quand le bouton de confirmation de la modale film est cliqué
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
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ratingKey: ratingKeyToArchive,
                options: options
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // Correctif : on cible le <li> parent du bouton cliqué
                $(`.archive-movie-btn[data-rating-key='${ratingKeyToArchive}']`).closest('li').fadeOut(500, function() {
                    $(this).remove();
                });
                console.log('Success:', data.message);
                // Idéalement, on utiliserait une notification "toast" ici
                alert('Film archivé avec succès !');
            } else {
                alert('Erreur: ' + data.message);
                console.error('Error:', data.message);
            }
        })
        .catch(error => {
            alert('Erreur de communication avec le serveur.');
            console.error('Fetch Error:', error);
        })
        .finally(() => {
            btn.prop('disabled', false).html('Confirmer l\'archivage');
            const modal = bootstrap.Modal.getInstance(document.getElementById('archiveMovieModal'));
            modal.hide();
            ratingKeyToArchive = null;
        });
    });

    // =================================================================
    // ### LOGIQUE POUR L'ARCHIVAGE DES SÉRIES (NOUVEAU BLOC) ###
    // =================================================================
    
    let ratingKeyToShowArchive = null;

    // 1. Quand un bouton "Archive Show" est cliqué
    $('.archive-show-btn').on('click', function() {
        ratingKeyToShowArchive = $(this).data('rating-key');
        const showTitle = $(this).data('title');
        const leafCount = $(this).data('leaf-count');
        const viewedLeafCount = $(this).data('viewed-leaf-count');

        $('#archiveShowModalTitle').text(showTitle);
        $('#archiveShowModalTotalCount').text(leafCount);
        $('#archiveShowModalEpisodeCount').text(viewedLeafCount);
    });

    // 2. Quand le bouton de confirmation de la modale série est cliqué
    $('#confirmArchiveShowBtn').on('click', function() {
        const btn = $(this);
        btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Archivage de la série...');

        const options = {
            deleteFiles: $('#archiveShowDeleteFiles').is(':checked'),
            unmonitor: $('#archiveShowUnmonitor').is(':checked'),
            addTag: $('#archiveShowAddTag').is(':checked')
        };

        fetch('/plex/archive_show', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ratingKey: ratingKeyToShowArchive,
                options: options
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // On cible le <li> parent du bouton cliqué pour le faire disparaître
                $(`.archive-show-btn[data-rating-key='${ratingKeyToShowArchive}']`).closest('li').fadeOut(500, function() {
                    $(this).remove();
                });
                console.log('Success:', data.message);
                alert('Série archivée avec succès !');
            } else {
                alert('Erreur: ' + data.message);
                console.error('Error:', data.message);
            }
        })
        .catch(error => {
            alert('Erreur de communication avec le serveur.');
            console.error('Fetch Error:', error);
        })
        .finally(() => {
            btn.prop('disabled', false).html('Confirmer l\'archivage de la série');
            const modal = bootstrap.Modal.getInstance(document.getElementById('archiveShowModal'));
            modal.hide();
            ratingKeyToShowArchive = null;
        });
    });

});