// Fichier : app/static/js/plex_editor_ui.js (Version Complète et Définitive)

$(document).ready(function() {

    // =================================================================
    // ### PARTIE 1 : GESTION DES FILTRES ET DE LA SESSION ###
    // =================================================================
    const userSelect = $('#user-select');
    const librarySelect = $('#library-select');
    const genreSelect = $('#genre-filter');
    const applyBtn = $('#apply-filters-btn');
    const loader = $('#plex-items-loader');
    const itemsContainer = $('#plex-items-container');
    const LAST_USER_KEY = 'mms_last_plex_user_id';

    // --- 1. Charger les utilisateurs au démarrage ---
    fetch("/plex/api/users")
        .then(response => response.json())
        .then(users => {
            userSelect.html('<option value="" selected disabled>Choisir un utilisateur...</option>');
            if (users && users.length > 0) {
                users.forEach(user => {
                    userSelect.append(new Option(user.text, user.id));
                });
            }
            const lastUserId = localStorage.getItem(LAST_USER_KEY);
            if (lastUserId && userSelect.find(`option[value="${lastUserId}"]`).length) {
                userSelect.val(lastUserId).trigger('change');
            }
        });

    // --- 2. Gérer la sélection de l'utilisateur ---
    userSelect.on('change', function () {
        const userId = $(this).val();
        const userTitle = $(this).find('option:selected').text();
        if (!userId) return;

        localStorage.setItem(LAST_USER_KEY, userId);
        librarySelect.html('<option selected disabled>Chargement...</option>').prop('disabled', true);

        // On informe le serveur pour mettre la session à jour
        fetch('/plex/select_user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: userId, title: userTitle })
        }).then(response => response.json())
          .then(data => {
            if (data.status === 'success') console.log("Utilisateur sauvegardé en session.");
            else console.error('Erreur sauvegarde session:', data.message);
        });

        fetch(`/plex/api/libraries/${userId}`)
            .then(response => response.json())
            .then(libraries => {
                librarySelect.html('');
                if (libraries && libraries.length > 0) {
                    libraries.forEach(lib => librarySelect.append(new Option(lib.text, lib.id)));
                    librarySelect.prop('disabled', false);
                } else {
                    librarySelect.html('<option selected disabled>Aucune bibliothèque</option>');
                }
                librarySelect.trigger('change'); // Trigger change to load genres
            });
    });

    librarySelect.on('change', function () {
        const selectedLibraries = $(this).val();
        const userId = userSelect.val();

        genreSelect.html('<option value="" selected>Tous les genres</option>').prop('disabled', true);

        if (selectedLibraries && selectedLibraries.length > 0) {
            fetch('/plex/api/genres', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ userId: userId, libraryKeys: selectedLibraries })
            })
            .then(response => response.json())
            .then(genres => {
                if (genres && genres.length > 0) {
                    genres.forEach(genre => {
                        genreSelect.append(new Option(genre, genre));
                    });
                    genreSelect.prop('disabled', false);
                }
            })
            .catch(error => console.error('Error fetching genres:', error));
        }
    });

    // --- 3. Appliquer les filtres pour charger les médias ---
    applyBtn.on('click', function() {
        const userId = userSelect.val();
        const selectedLibraries = librarySelect.val();
        const statusFilter = $('#status-filter').val();
        const titleFilter = $('#title-filter-input').val().trim();
        const selectedGenres = genreSelect.val();
        const genreLogic = $('input[name="genre-logic"]:checked').val();

        if (!userId || !selectedLibraries || selectedLibraries.length === 0) {
            itemsContainer.html('<p class="text-center text-warning">Veuillez sélectionner un utilisateur et une bibliothèque.</p>');
            return;
        }

        loader.show();
        itemsContainer.html('');

        fetch("/plex/api/media_items", {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                userId: userId,
                libraryKeys: selectedLibraries,
                statusFilter: statusFilter,
                titleFilter: titleFilter,
                genres: selectedGenres,
                genreLogic: genreLogic
            })
        })
        .then(response => response.text())
        .then(html => {
            loader.hide();
            itemsContainer.html(html);
        });
    });

    // =================================================================
    // ### PARTIE 2 : GESTION DES ACTIONS (Archivage, Rejet, etc.) ###
    // =================================================================

    // --- A. Écouteur d'événements délégué pour SETUP les modales ---
    // Cet unique écouteur gère les clics sur les boutons qui ouvrent les modales
    itemsContainer.on('click', function(event) {
        const target = $(event.target);

        const archiveMovieBtn = target.closest('.archive-movie-btn');
        if (archiveMovieBtn) {
            const ratingKey = archiveMovieBtn.data('ratingKey');
            $('#archiveMovieTitle').text(archiveMovieBtn.data('title'));
            $('#confirmArchiveMovieBtn').data('ratingKey', ratingKey);
        }

        const archiveShowBtn = target.closest('.archive-show-btn');
        if (archiveShowBtn) {
            const ratingKey = archiveShowBtn.data('ratingKey');
            $('#archiveShowTitle').text(archiveShowBtn.data('title'));
            $('#archiveShowTotalCount').text(archiveShowBtn.data('leaf-count'));
            $('#archiveShowViewedCount').text(archiveShowBtn.data('viewed-leaf-count'));
            $('#confirmArchiveShowBtn').data('ratingKey', ratingKey);
        }

        const rejectShowBtn = target.closest('.reject-show-btn');
        if (rejectShowBtn) {
            const ratingKey = rejectShowBtn.data('ratingKey');
            $('#rejectShowTitle').text(rejectShowBtn.data('title'));
            $('#confirmRejectShowBtn').data('ratingKey', ratingKey);
        }

// --- ACTION : COPIER LE CHEMIN DU FICHIER ---
        const copyPathBtn = event.target.closest('.copy-path-btn');
        if (copyPathBtn) {
            const path = $(copyPathBtn).data('path');
            navigator.clipboard.writeText(path).then(() => {
                // Succès ! On change l'icône temporairement pour donner un feedback.
                const originalIcon = $(copyPathBtn).html();
                $(copyPathBtn).html('<i class="bi bi-check-lg text-success"></i>');
                setTimeout(() => {
                    $(copyPathBtn).html(originalIcon);
                }, 1500); // Rétablir l'icône après 1.5 secondes
            }).catch(err => {
                console.error('Erreur de copie dans le presse-papiers:', err);
                alert("La copie a échoué. Vérifiez les permissions de votre navigateur.");
            });
        }

        // --- ACTION : SETUP MODALE DÉTAILS DU MÉDIA ---
        const titleLink = event.target.closest('.item-title-link');
        if (titleLink) {
            event.preventDefault(); // Empêche le lien de remonter en haut de la page
            const ratingKey = $(titleLink).data('ratingKey');
            const modalElement = document.getElementById('item-details-modal');
            const modalTitle = modalElement.querySelector('#itemDetailsModalLabel');
            const modalBody = modalElement.querySelector('.modal-body');

            // Affiche le loader et réinitialise le contenu
            modalTitle.textContent = 'Chargement des détails...';
            modalBody.innerHTML = '<div class="text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>';

            fetch(`/plex/api/media_details/${ratingKey}`)
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(errData => { throw new Error(errData.error || `Erreur HTTP ${response.status}`); });
                    }
                    return response.json();
                })
                .then(data => {
                    modalTitle.textContent = data.title || 'Détails du Média';
                    const posterHtml = data.poster_url ? `<img src="${data.poster_url}" class="img-fluid rounded mb-3">` : '<p class="text-muted">Aucune affiche disponible.</p>';
                    const durationHtml = data.duration_readable ? `<p><strong>Durée:</strong> ${data.duration_readable}</p>` : '';
                    const ratingHtml = data.rating ? `<p><strong>Note:</strong> ${data.rating} / 10</p>` : '<p><strong>Note:</strong> Non noté</p>';

                    modalBody.innerHTML = `
                        <div class="row">
                            <div class="col-md-4">${posterHtml}</div>
                            <div class="col-md-8">
                                <h4>${data.title || 'Titre inconnu'} ${data.year ? `(${data.year})` : ''}</h4>
                                <p class="fst-italic text-muted">${data.tagline || ''}</p>
                                <p>${data.summary || 'Aucun résumé.'}</p>
                                <p><strong>Genres:</strong> ${data.genres && data.genres.length > 0 ? data.genres.join(', ') : 'Non spécifiés'}</p>
                                ${ratingHtml}
                                ${durationHtml}
                            </div>
                        </div>
                    `;
                })
                .catch(error => {
                    modalTitle.textContent = 'Erreur';
                    modalBody.innerHTML = `<div class="alert alert-danger">${error.message}</div>`;
                    console.error("Erreur chargement détails:", error);
                });
        }

        // --- ACTION : SETUP MODALE GÉRER SÉRIE ---
        const manageSeriesBtn = event.target.closest('.manage-series-btn');
        if (manageSeriesBtn) {
            const ratingKey = $(manageSeriesBtn).data('ratingKey');
            const seriesTitle = $(manageSeriesBtn).data('title');
            const modalBody = $('#series-management-modal .modal-body');

            $('#seriesManagementModalLabel').text(`Gestion de la Série : ${seriesTitle}`);
            modalBody.html('<div class="text-center my-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2">Chargement...</p></div>');

            // On lance la requête pour obtenir le contenu de la modale
            fetch(`/plex/api/series_details/${ratingKey}`, {
                method: 'POST', // On passe à POST pour envoyer le userId
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ userId: userSelect.val() }) // On envoie l'ID de l'utilisateur
            })
            .then(response => response.text())
            .then(html => modalBody.html(html))
            .catch(error => {
                console.error("Erreur chargement détails série:", error);
                modalBody.html(`<div class="alert alert-danger">Erreur de communication : ${error.message}</div>`);
            });
        }
    });

    // --- B. Écouteurs d'événements pour les boutons de CONFIRMATION des modales ---

    $('#confirmArchiveMovieBtn').on('click', function() {
        const btn = $(this);
        const ratingKey = btn.data('ratingKey');
        btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Archivage...');
        const options = {
            deleteFiles: $('#archiveMovieDeleteFiles').is(':checked'),
            unmonitor: $('#archiveMovieUnmonitor').is(':checked'),
            addTag: $('#archiveMovieAddTag').is(':checked')
        };
        fetch('/plex/archive_movie', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ratingKey: ratingKey, options: options })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                $(`.archive-movie-btn[data-rating-key='${ratingKey}']`).closest('tr').remove();
                bootstrap.Modal.getInstance(document.getElementById('archiveMovieModal')).hide();
            } else { alert('Erreur: ' + data.message); }
        })
        .catch(error => { console.error(error); alert('Erreur de communication.'); })
        .finally(() => btn.prop('disabled', false).html('Confirmer l\'archivage'));
    });

    $('#confirmArchiveShowBtn').on('click', function() {
        const btn = $(this);
        const ratingKey = btn.data('ratingKey');
        btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Archivage...');
        const options = {
            deleteFiles: $('#archiveShowDeleteFiles').is(':checked'),
            unmonitor: $('#archiveShowUnmonitor').is(':checked'),
            addTag: $('#archiveShowAddTag').is(':checked')
        };
        fetch('/plex/archive_show', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ratingKey: ratingKey,
                options: options,
                userId: $('#user-select').val() // <-- AJOUTE CETTE LIGNE
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                $(`.archive-show-btn[data-rating-key='${ratingKey}']`).closest('tr').remove();
                bootstrap.Modal.getInstance(document.getElementById('archiveShowModal')).hide();
            } else { alert('Erreur: ' + data.message); }
        })
        .catch(error => { console.error(error); alert('Erreur de communication.'); })
        .finally(() => btn.prop('disabled', false).html('Confirmer l\'archivage'));
    });

    $('#confirmRejectShowBtn').on('click', function() {
        const btn = $(this);
        const ratingKey = btn.data('ratingKey');
        btn.prop('disabled', true).text('Suppression...');
        fetch('/plex/reject_show', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ratingKey: ratingKey })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                $(`.reject-show-btn[data-rating-key='${ratingKey}']`).closest('tr').remove();
                bootstrap.Modal.getInstance(document.getElementById('rejectShowModal')).hide();
            } else { alert('Erreur: ' + data.message); }
        })
        .catch(error => { console.error(error); alert('Erreur de communication.'); })
        .finally(() => btn.prop('disabled', false).text('Oui, rejeter et supprimer'));
    });

    // --- Logique pour la modale de gestion de série ---
    const seriesModalElement = document.getElementById('series-management-modal');

    if (seriesModalElement) {
        // --- GESTION DU TOGGLE GLOBAL DE LA SÉRIE ---
        $(seriesModalElement).on('change', '#series-monitor-toggle', function() {
            const seriesToggle = $(this);
            const isMonitored = seriesToggle.is(':checked');

            // Étape 1 : On met à jour visuellement tous les toggles de saison
            const seasonToggles = $(seriesModalElement).find('.season-monitor-toggle');
            seasonToggles.prop('checked', isMonitored);

            // Étape 2 : On déclenche leur événement "change" pour que la cascade se produise
            // et que les appels API pour chaque saison soient lancés.
            seasonToggles.trigger('change');
        });

        // --- GESTION DU TOGGLE PAR SAISON ---
        $(seriesModalElement).on('change', '.season-monitor-toggle', function() {
            const seasonToggle = $(this);
            const seasonRow = seasonToggle.closest('.season-row');
            const isMonitored = seasonToggle.is(':checked');

            // On lance l'appel API (code existant et correct)
            const sonarrSeriesId = seasonRow.data('sonarr-series-id');
            const seasonNumber = seasonRow.data('season-number');
            seasonRow.addClass('opacity-50');
            fetch('/plex/update_season_monitoring', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sonarrSeriesId: sonarrSeriesId, seasonNumber: seasonNumber, monitored: isMonitored })
            })
            .then(response => response.json())
            .then(data => { if (data.status !== 'success') seasonToggle.prop('checked', !isMonitored); })
            .catch(() => seasonToggle.prop('checked', !isMonitored))
            .finally(() => seasonRow.removeClass('opacity-50'));

            // **LA CASCADE** : On met à jour visuellement tous les épisodes de la saison
            const collapseTargetSelector = seasonRow.find('[data-bs-toggle="collapse"]').data('bs-target');
            const episodeToggles = $(collapseTargetSelector).find('.episode-monitor-toggle');
            episodeToggles.prop('checked', isMonitored);

            // On déclenche l'événement "change" pour chaque épisode pour lancer leurs appels API
            episodeToggles.trigger('change');
        });
        // --- GESTION DE LA SUPPRESSION D'UNE SAISON ---
        $(seriesModalElement).on('click', '.delete-season-btn', function() {
            const btn = $(this);
            const seasonRow = btn.closest('.season-row');
            const seasonId = btn.data('season-id'); // C'est le ratingKey de la saison
            const seasonTitle = btn.data('season-title');

            if (!confirm(`Êtes-vous sûr de vouloir supprimer tous les fichiers de "${seasonTitle}" et la dé-monitorer dans Sonarr ? Cette action est irréversible.`)) {
                return;
            }

            btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

            // --- CORRECTION : On utilise la bonne URL et la bonne méthode (DELETE) ---
            fetch(`/plex/api/season/${seasonId}`, {
                method: 'DELETE'
                // Pas besoin de headers ou de body, l'ID est dans l'URL
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // On grise la ligne et désactive les contrôles
                    seasonRow.addClass('opacity-50 text-decoration-line-through');
                    seasonRow.find('input, button').prop('disabled', true);
                    alert(`La saison "${seasonTitle}" a été traitée avec succès.`);
                } else {
                    alert('Erreur: ' + data.message);
                }
            })
            .catch(error => { console.error(error); alert("Erreur de communication."); })
            .finally(() => {
                // On change l'icône en succès pour confirmer
                btn.removeClass('btn-outline-danger').addClass('btn-success').html('<i class="bi bi-check-lg"></i>');
            });
        });

        // --- GESTION DU TOGGLE PAR ÉPISODE (EFFET IMMÉDIAT) ---
        $(seriesModalElement).on('change', '.episode-monitor-toggle', function() {
            const episodeToggle = $(this);
            const episodeRow = episodeToggle.closest('li');
            const episodeId = episodeToggle.data('sonarr-episode-id');
            const isMonitored = episodeToggle.is(':checked');

            if (!episodeId) return;

            episodeRow.addClass('opacity-50');
            fetch('/plex/api/episodes/update_monitoring_single', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ episodeId: episodeId, monitored: isMonitored })
            })
            .then(response => response.json())
            .then(data => { if (data.status !== 'success') episodeToggle.prop('checked', !isMonitored); })
            .catch(() => episodeToggle.prop('checked', !isMonitored))
            .finally(() => episodeRow.removeClass('opacity-50'));
        });

        // --- GESTION DU BOUTON DE SUPPRESSION ---
        $(seriesModalElement).on('click', '#delete-selected-episodes-btn', function() {
            const btn = $(this);
            const checked_boxes = $(seriesModalElement).find('.episode-delete-checkbox:checked');

            if (checked_boxes.length === 0) {
                alert("Veuillez cocher au moins un épisode à supprimer.");
                return;
            }

            if (!confirm(`Êtes-vous sûr de vouloir supprimer définitivement les fichiers des ${checked_boxes.length} épisodes sélectionnés ?`)) {
                return;
            }

            const episodeFileIds = checked_boxes.map(function() {
                return $(this).val();
            }).get();

            btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Suppression...');

            fetch('/plex/api/episodes/delete_bulk', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ episodeFileIds: episodeFileIds })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    alert(`Suppression de ${checked_boxes.length} épisode(s) lancée.`);
                    // On grise les lignes supprimées
                    checked_boxes.each(function() {
                        $(this).closest('li').addClass('opacity-50 text-decoration-line-through');
                        $(this).prop('checked', false).prop('disabled', true);
                    });
                } else {
                    alert('Erreur: ' + data.message);
                }
            })
            .catch(error => { console.error(error); alert("Erreur de communication."); })
            .finally(() => {
                btn.prop('disabled', false).html('<i class="bi bi-trash"></i> Supprimer la Sélection');
            });
        });

        // --- GESTION DU CLIC SUR L'ICÔNE VU/NON VU D'UN ÉPISODE ---
        $(seriesModalElement).on('click', '.toggle-episode-watched-btn', function(event) {
            event.preventDefault();
            const link = $(this);
            const ratingKey = link.data('ratingKey');
            const userId = userSelect.val(); // On a besoin de l'utilisateur

            // Feedback visuel
            link.html('<span class="spinner-border spinner-border-sm"></span>');

            fetch('/plex/toggle_watched_status', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ratingKey: ratingKey, userId: userId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    // On remplace juste l'icône, sans recharger toute la modale
                    const isNowWatched = data.new_status === 'Vu';
                    const newIcon = isNowWatched
                        ? '<i class="bi bi-check-circle-fill text-success"></i>'
                        : '<i class="bi bi-circle"></i>';
                    link.html(newIcon);

                    // On met aussi à jour le style de la ligne
                    const listItem = link.closest('li');
                    if (isNowWatched) {
                        listItem.removeClass('list-group-item-secondary').addClass('list-group-item-light text-muted');
                    } else {
                        listItem.removeClass('list-group-item-light text-muted').addClass('list-group-item-secondary');
                    }
                } else {
                    alert('Erreur: ' + data.message);
                }
            })
            .catch(error => { console.error(error); alert("Erreur de communication."); });
        });
    }
    // =================================================================
    // ### LOGIQUE POUR BASCULER LE STATUT VU/NON-VU ###
    // =================================================================
    itemsContainer.on('click', '.toggle-watched-btn', function() {
        const button = $(this);
        const ratingKey = button.data('ratingKey');
        const userId = userSelect.val(); // On récupère l'ID de l'utilisateur depuis le dropdown.
        const statusCell = button.closest('tr').find('.media-status-cell');
        const originalIcon = button.html();

        // Feedback visuel immédiat
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

        fetch('/plex/toggle_watched_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ratingKey: ratingKey, userId: userId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success' && data.new_status_html) {
                statusCell.html(data.new_status_html);
            } else {
                alert('Erreur: ' + (data.message || 'Une erreur est survenue.'));
            }
        })
        .catch(error => {
            console.error("Erreur lors de la bascule du statut 'vu':", error);
            alert("Erreur de communication pour la mise à jour du statut.");
        })
        .finally(() => {
            button.prop('disabled', false).html(originalIcon);
        });
    });

}); // Fin de $(document).ready