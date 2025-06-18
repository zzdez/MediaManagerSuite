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
    // =================================================================
    // ### LOGIQUE POUR REJETER UNE SÉRIE ###
    // =================================================================
    let ratingKeyToShowReject = null;

    $('.reject-show-btn').on('click', function() {
        ratingKeyToShowReject = $(this).data('rating-key');
        $('#rejectShowModalTitle').text($(this).data('title'));
    });

    $('#confirmRejectShowBtn').on('click', function() {
        const btn = $(this);
        btn.prop('disabled', true).text('Suppression...');
        fetch('/plex/reject_show', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ratingKey: ratingKeyToShowReject })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                $(`.reject-show-btn[data-rating-key='${ratingKeyToShowReject}']`).closest('li').fadeOut(500, function() { $(this).remove(); });
                alert(data.message);
            } else {
                alert('Erreur: ' + data.message);
            }
        })
        .catch(error => { alert('Erreur de communication avec le serveur.'); console.error('Fetch Error:', error); })
        .finally(() => {
            btn.prop('disabled', false).text('Oui, rejeter et supprimer');
            bootstrap.Modal.getInstance(document.getElementById('rejectShowModal')).hide();
            ratingKeyToShowReject = null;
        });
    });

    // =================================================================
    // ### LOGIQUE POUR LA MODALE DE DÉTAILS ###
    // =================================================================
    $('#item-list').on('click', '.item-title-link', function(e) {
        e.preventDefault();
        const ratingKey = $(this).data('rating-key');
        const modal = $('#detailsModal');
        const contentDiv = modal.find('#detailsModalContent');
        const spinnerDiv = modal.find('#detailsModalSpinner');

        contentDiv.hide();
        spinnerDiv.show();
        modal.find('#detailsModalTitle').text('Chargement...');
        modal.find('#detailsModalPoster').attr('src', '');
        modal.find('#detailsModalYear, #detailsModalDuration, #detailsModalRating, #detailsModalGenres, #detailsModalSummary, #detailsModalActors, #detailsModalDirectors').text('...');

        fetch(`/plex/details/${ratingKey}`)
            .then(response => {
                if (!response.ok) { throw new Error(`Erreur réseau: ${response.statusText}`); }
                return response.json();
            })
            .then(data => {
                if (data.status === 'success') {
                    const details = data.details;
                    modal.find('#detailsModalTitle').text(details.title);
                    modal.find('#detailsModalLabel').text(details.title);
                    modal.find('#detailsModalPoster').attr('src', details.poster_url || 'https://via.placeholder.com/400x600.png?text=Pas+d\'affiche');
                    modal.find('#detailsModalYear').text(details.year || 'N/A');
                    modal.find('#detailsModalDuration').text(details.duration_min ? `${details.duration_min} min` : 'N/A');
                    let ratingText = '';
                    if (details.rating) ratingText += `Critique: ⭐ ${details.rating}`;
                    if (details.user_rating) {
                        if (ratingText) ratingText += ' | ';
                        ratingText += `Ma Note: ❤️ ${details.user_rating}`;
                    }
                    modal.find('#detailsModalRating').text(ratingText || 'N/A');
                    modal.find('#detailsModalGenres').text(details.genres.join(', ') || 'Non spécifiés');
                    modal.find('#detailsModalSummary').text(details.summary || 'Aucun résumé.');
                    modal.find('#detailsModalActors').text(details.actors.join(', ') || 'Non spécifiés');

                    if (details.type === 'show') {
                        $('#detailsShowInfo').show();
                        $('#detailsDirectorsBlock').hide();
                        $('#detailsSonarrStatus').text(details.sonarr_status || 'N/A');
                        $('#detailsSonarrSeasonCount').text(details.sonarr_season_count !== undefined ? `${details.sonarr_season_count} saisons` : 'N/A');
                        $('#detailsPlexProgress').text(`${details.viewed_leaf_count} / ${details.leaf_count} épisodes vus`);
                        $('#detailsAddedAt').text(details.added_at || 'N/A');
                        $('#detailsFirstAired').text(details.originally_available_at || 'N/A');
                    } else {
                        $('#detailsShowInfo').hide();
                        $('#detailsDirectorsBlock').show();
                        $('#detailsModalDirectors').text(details.directors.join(', ') || 'Non spécifié');
                    }
                } else {
                    modal.find('#detailsModalTitle').text('Erreur');
                    modal.find('#detailsModalSummary').text(data.message);
                }
            })
            .catch(error => {
                console.error("Fetch error for details:", error);
                modal.find('#detailsModalTitle').text('Erreur de Communication');
                modal.find('#detailsModalSummary').text('Impossible de contacter le serveur pour obtenir les détails.');
            })
            .finally(() => {
                spinnerDiv.hide();
                contentDiv.show();
            });
    });

});