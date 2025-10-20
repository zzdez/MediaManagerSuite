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
                    librarySelect.append($('<option>', { value: 'all', text: 'Toutes les bibliothèques' }));
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
        $('#collection-filter').html('').prop('disabled', true);
        $('#resolution-filter').html('').prop('disabled', true);
        $('#studio-filter').html('').prop('disabled', true);

        if (selectedLibraries && selectedLibraries.length > 0) {
            const payload = { userId: userId, libraryKeys: selectedLibraries };

            // Fetch Genres
            fetch('/plex/api/genres', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(response => response.json())
            .then(genres => {
                if (genres && genres.length > 0) {
                    genres.forEach(genre => genreSelect.append(new Option(genre, genre)));
                    genreSelect.prop('disabled', false);
                }
            });

            // **LOGIQUE MANQUANTE À AJOUTER CI-DESSOUS**
            const collectionSelect = $('#collection-filter');
            fetch('/plex/api/collections', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ userId: userId, libraryKeys: selectedLibraries })
            })
            .then(response => response.json())
            .then(collections => {
                collectionSelect.empty(); // Vider le sélecteur
                collections.forEach(collection => {
                    collectionSelect.append($('<option>', {
                        value: collection,
                        text: collection
                    }));
                });
                collectionSelect.prop('disabled', false);
            })
            .catch(error => console.error('Error fetching collections:', error));

            // Fetch Resolutions
            fetch('/plex/api/resolutions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(response => response.json())
            .then(resolutions => {
                const resolutionSelect = $('#resolution-filter');
                resolutionSelect.empty();
                if (resolutions && resolutions.length > 0) {
                    resolutions.forEach(resolution => resolutionSelect.append(new Option(resolution, resolution)));
                    resolutionSelect.prop('disabled', false);
                }
            });

            // Fetch Studios
            fetch('/plex/api/studios', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(response => response.json())
            .then(studios => {
                const studioSelect = $('#studio-filter');
                studioSelect.empty();
                if (studios && studios.length > 0) {
                    studios.forEach(studio => studioSelect.append(new Option(studio, studio)));
                    studioSelect.prop('disabled', false);
                }
            });
        }
    });

    // --- 3. Appliquer les filtres pour charger les médias ---
    // Remplace l'ancienne logique de gestion des dates par celle-ci
    $('#date-filter-type').on('change', function() {
        const type = $(this).val();
        $('#date-filter-preset').prop('disabled', !type);
        if (!type) {
            $('#custom-date-fields-container').hide();
        }
    });

    $('#date-filter-preset').on('change', function() {
        $('#custom-date-fields-container').toggle($(this).val() === 'custom');
    });

    // Logique pour gérer l'affichage dynamique du filtre de note
    $('#rating-filter-operator').on('change', function() {
        const operator = $(this).val();
        const showValueSelector = ['gte', 'lte', 'eq'].includes(operator);
        $('#rating-value-container').toggle(showValueSelector);
    });

    applyBtn.on('click', function() {
        const userId = userSelect.val();
        const selectedLibraries = librarySelect.val();
        const statusFilter = $('#status-filter').val();
        const titleFilter = $('#title-filter-input').val().trim();
        const yearFilter = $('#year-filter').val(); // <-- NOUVELLE LIGNE
        const selectedGenres = genreSelect.val();
        const genreLogic = $('input[name="genre-logic"]:checked').val();
        const dateFilterType = $('#date-filter-type').val();
        const dateFilterPreset = $('#date-filter-preset').val();
        const dateFilterStart = $('#date-filter-start').val();
        const dateFilterEnd = $('#date-filter-end').val();
        const ratingFilterOperator = $('#rating-filter-operator').val();
        const ratingFilterValue = $('#rating-filter-value').val();
        const selectedCollections = $('#collection-filter').val();
        const selectedResolutions = $('#resolution-filter').val();
        const actorFilter = $('#actor-filter').val().trim();
        const directorFilter = $('#director-filter').val().trim();
        const writerFilter = $('#writer-filter').val().trim();
        const selectedStudios = $('#studio-filter').val();

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
                year: yearFilter, // <-- NOUVELLE LIGNE
                genres: selectedGenres,
                genreLogic: genreLogic,
                dateFilter: {
                    type: dateFilterType,
                    preset: dateFilterPreset,
                    start: dateFilterStart,
                    end: dateFilterEnd
                },
                ratingFilter: {
                    operator: ratingFilterOperator,
                    value: ratingFilterValue
                },
                collections: selectedCollections,
                resolutions: selectedResolutions,
                actor: actorFilter,
                director: directorFilter,
                writer: writerFilter,
                studios: selectedStudios
            })
        })
        .then(response => response.text())
        .then(html => {
            loader.hide();
            itemsContainer.html(html);
        });
    });

    // --- FILTRE POUR AFFICHER UNIQUEMENT LES SÉRIES INCOMPLÈTES ---
    $(document).on('change', '#show-incomplete-only-filter', function() {
        const showOnlyIncomplete = $(this).is(':checked');
        const tableRows = $('#plex-results-table tbody tr');

        if (!showOnlyIncomplete) {
            // Si la case est décochée, on affiche tout
            tableRows.show();
            return;
        }

        // Sinon, on boucle et on affiche/cache en fonction de l'attribut data
        tableRows.each(function() {
            const row = $(this);
            const isIncomplete = row.data('incomplete') === true;
            row.toggle(isIncomplete);
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

// Met les options d'archivage de film par défaut LORS DE L'OUVERTURE de la modale
$('#archiveMovieModal').on('show.bs.modal', function () {
    $('#archiveMovieDeleteFiles').prop('checked', true);
    $('#archiveMovieUnmonitor').prop('checked', true);
    $('#archiveMovieAddTag').prop('checked', true);
});

// Met les options d'archivage de série par défaut LORS DE L'OUVERTURE de la modale
$('#archiveShowModal').on('show.bs.modal', function () {
    $('#archiveShowDeleteFiles').prop('checked', true);
    $('#archiveShowUnmonitor').prop('checked', true);
    $('#archiveShowAddTag').prop('checked', true);
});

// Gère la soumission LORS DU CLIC sur le bouton de confirmation
$('#confirmArchiveMovieBtn').on('click', function() {
    const btn = $(this);
    const ratingKey = btn.data('ratingKey');
    const userId = $('#user-select').val();
    if (!userId) {
        alert("Erreur : Aucun utilisateur n'est sélectionné.");
        return;
    }

    btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Archivage...');
    const options = {
        deleteFiles: $('#archiveMovieDeleteFiles').is(':checked'),
        unmonitor: $('#archiveMovieUnmonitor').is(':checked'),
        addTag: $('#archiveMovieAddTag').is(':checked')
    };
    fetch('/plex/archive_movie', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ratingKey: ratingKey, options: options, userId: userId })
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

        // --- GESTION DU BOUTON DE RENOMMAGE (GLOBAL ET PAR SAISON) ---

        // Écouteur pour le bouton GLOBAL (série entière)
        $(seriesModalElement).on('click', '#rename-series-files-btn', function() {
            const button = $(this);
            const sonarrSeriesId = button.data('sonarr-id');
            handleFileRename(button, sonarrSeriesId, null); // season_number est null
        });

        // NOUVEL ÉCOUTEUR pour les boutons de SAISON
        $(seriesModalElement).on('click', '.rename-season-files-btn', function() {
            const button = $(this);
            const sonarrSeriesId = button.data('sonarr-id');
            const seasonNumber = button.data('season-number');
            handleFileRename(button, sonarrSeriesId, seasonNumber);
        });

        // NOUVELLE FONCTION HELPER pour éviter la duplication de code
        function handleFileRename(button, sonarrSeriesId, seasonNumber) {
            const isSeason = seasonNumber !== null;
            const message = isSeason ? `la saison ${seasonNumber}` : "toute la série";

            if (!confirm(`Êtes-vous sûr de vouloir demander à Sonarr de renommer tous les fichiers pour ${message} ?`)) {
                return;
            }

            const originalHtml = button.html();
            button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span>');

            fetch('/plex/api/series/rename_files', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sonarr_series_id: sonarrSeriesId,
                    season_number: seasonNumber // Envoie null pour la série entière
                })
            })
            .then(response => response.json())
            .then(data => {
                alert(data.message);
            })
            .catch(error => {
                console.error('Erreur:', error);
                alert("Une erreur technique est survenue.");
            })
            .finally(() => {
                button.prop('disabled', false).html(originalHtml);
            });
        }

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

    // =================================================================
    // ### PARTIE 3 : GESTION DES ACTIONS DE MASSE (BULK) ###
    // =================================================================

    // --- A. Logique de sélection et affichage du conteneur d'actions ---
    $(document).on('change', '#select-all-checkbox, .item-checkbox', function() {
        const isSelectAll = $(this).is('#select-all-checkbox');
        const itemCheckboxes = $('.item-checkbox');
        const selectAllCheckbox = $('#select-all-checkbox');

        if (isSelectAll) {
            // Si la case "tout sélectionner" est cochée, on coche toutes les autres
            itemCheckboxes.prop('checked', $(this).prop('checked'));
        } else {
            // Si une case individuelle est décochée, on décoche "tout sélectionner"
            if (!$(this).prop('checked')) {
                selectAllCheckbox.prop('checked', false);
            }
            // Si toutes les cases sont cochées manuellement, on coche "tout sélectionner"
            if ($('.item-checkbox:checked').length === itemCheckboxes.length) {
                selectAllCheckbox.prop('checked', true);
            }
        }

        const selectedCount = $('.item-checkbox:checked').length;
        const batchActionsContainer = $('#batch-actions-container');
        const selectedItemCountSpan = $('#selected-item-count');

        selectedItemCountSpan.text(selectedCount);
        batchActionsContainer.toggle(selectedCount > 0);
    });

    // --- B. Action de suppression en masse ---
    $(document).on('click', '#batch-delete-btn', function() {
        const selectedItems = $('.item-checkbox:checked');
        const selectedItemKeys = selectedItems.map(function() {
            return $(this).data('rating-key');
        }).get();

        if (selectedItemKeys.length === 0) {
            alert('Veuillez sélectionner au moins un élément.');
            return;
        }

        if (confirm(`Êtes-vous sûr de vouloir supprimer ${selectedItemKeys.length} élément(s) ? Cette action est irréversible.`)) {
            fetch('/plex/bulk_delete_items', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: new URLSearchParams({
                    'selected_item_keys': selectedItemKeys
                })
            })
            .then(response => {
                if (response.ok) {
                    return response.json();
                }
                // Si la réponse n'est pas OK, on essaie de lire le message d'erreur JSON
                return response.json().then(errData => {
                    throw new Error(errData.error || 'Erreur inconnue du serveur.');
                });
            })
            .then(data => {
                 alert(data.message || 'Éléments supprimés avec succès.');
                $('#apply-filters-btn').click(); // Rafraîchir la liste
            })
            .catch(error => {
                console.error('Error during batch delete:', error);
                alert(`Une erreur est survenue lors de la suppression: ${error.message}`);
            });
        }
    });

    // =================================================================
    // ### PARTIE 4 : TRI DYNAMIQUE DU TABLEAU ###
    // =================================================================

// NOUVELLE FONCTION PARSESIZE ROBUSTE
function parseSize(sizeStr) {
    if (!sizeStr || typeof sizeStr !== 'string' || sizeStr === 'N/A') return 0;
    const sizeMatch = sizeStr.match(/([\d,.]+)\s*(\w+)/);
    if (!sizeMatch) return 0;

    const value = parseFloat(sizeMatch[1].replace(',', '.'));
    const unit = sizeMatch[2].toUpperCase();

    switch (unit) {
        case 'TB': case 'TO': return value * 1e12;
        case 'GB': case 'GO': return value * 1e9;
        case 'MB': case 'MO': return value * 1e6;
        case 'KB': case 'KO': return value * 1e3;
        default: return value;
    }
}

function sortTable(table, sortBy, sortType, direction) {
    const tbody = table.find('tbody');
    const rows = tbody.find('tr').toArray();

    // Correction majeure : On trouve l'index de la colonne PARMI TOUS les <th>
    const cellIndex = table.find(`th.sortable-header[data-sort-by='${sortBy}']`).index();

    rows.sort(function(a, b) {
        let valA, valB;

        if (sortBy === 'rating') {
            valA = parseFloat($(a).data('rating')) || 0;
            valB = parseFloat($(b).data('rating')) || 0;
        } else {
            // On utilise maintenant le cellIndex qui est fiable
            const cellA = $(a).children('td').eq(cellIndex);
            const cellB = $(b).children('td').eq(cellIndex);

            if (sortBy === 'title') {
                valA = cellA.find('.item-title-link').text().trim().toLowerCase();
                valB = cellB.find('.item-title-link').text().trim().toLowerCase();
            } else {
                valA = cellA.text().trim();
                valB = cellB.text().trim();
            }
        }

        if (sortType === 'size') {
            valA = parseSize(valA);
            valB = parseSize(valB);
        } else if (sortType === 'date') {
            valA = new Date(valA).getTime() || 0;
            valB = new Date(valB).getTime() || 0;
        } else if (sortType === 'text') {
            valA = valA.toLowerCase();
            valB = valB.toLowerCase();
        }

        if (valA < valB) return -1 * direction;
        if (valA > valB) return 1 * direction;
        return 0;
    });

    tbody.empty().append(rows);
}

    // Écouteur pour les en-têtes de colonne
    $(document).on('click', '.sortable-header', function() {
        const header = $(this);
        const table = $('#plex-results-table');
        const sortBy = header.data('sort-by');
        const sortType = header.data('sort-type') || 'text';

        let currentDir = header.data('sort-direction') || 'desc';
        let newDir = currentDir === 'asc' ? 'desc' : 'asc';
        header.data('sort-direction', newDir);

        $('.sortable-header').removeClass('sort-asc sort-desc');
        header.addClass(newDir === 'asc' ? 'sort-asc' : 'sort-desc');

        sortTable(table, sortBy, sortType, newDir === 'asc' ? 1 : -1);
    });

    // Écouteur pour le bouton de tri par note
    $(document).on('click', '#sort-by-rating-btn', function() {
        const table = $('#plex-results-table');
        let newDir = $(this).data('sort-direction') === 'asc' ? 'desc' : 'asc';
        $(this).data('sort-direction', newDir);

        $('.sortable-header').removeClass('sort-asc sort-desc');
        sortTable(table, 'rating', 'number', newDir === 'asc' ? 1 : -1);
    });

// --- DÉBUT DU BLOC DE GESTION DES BANDES-ANNONCES (NOUVELLE VERSION) ---

// Handler pour le bouton principal "Voir la BA" sur la ligne du média
$(document).on('click', '.find-and-play-trailer-btn', function() {
    const button = $(this);
    const plexTrailerUrl = button.data('plex-trailer-url');

    if (plexTrailerUrl) {
        // Cas 1: La bande-annonce est fournie directement par Plex. On la joue.
        const title = button.data('title');
        $('#trailerModalLabel').text('Bande-Annonce (Plex): ' + title);
        $('#trailer-modal .modal-body').html(`<div class="ratio ratio-16x9"><iframe src="${plexTrailerUrl}" allow="autoplay; encrypted-media" allowfullscreen></iframe></div>`);
        bootstrap.Modal.getOrCreateInstance(document.getElementById('trailer-modal')).show();
    } else {
        // Cas 2: Pas de bande-annonce Plex, on utilise notre nouveau système de recherche.
        // On récupère toutes les informations nécessaires directement depuis le bouton.
        const mediaType = button.data('media-type');
        const externalId = button.data('external-id');
        const title = button.data('title');
        const year = button.data('year'); // On récupère aussi l'année

        if (mediaType && externalId && title) {
            // On déclenche l'événement global avec toutes les données.
            $(document).trigger('openTrailerSearch', { mediaType, externalId, title, year });
        } else {
            alert('Erreur: Informations manquantes pour rechercher la bande-annonce (mediaType, externalId, title).');
            console.error('Attributs de données manquants sur le bouton de bande-annonce:', {
                mediaType: mediaType,
                externalId: externalId,
                title: title
            });
        }
    }
});

// --- FIN DU BLOC DE GESTION DES BANDES-ANNONCES ---

    // NOUVEL ÉCOUTEUR D'ÉVÉNEMENT
    $(document).on('click', '#scan-libraries-btn', function() {
        const button = $(this);
        const selectedLibraries = $('#library-select').val();
        const userId = $('#user-select').val();
        let keysToScan = [];

        if (!selectedLibraries || selectedLibraries.length === 0) {
            alert("Veuillez sélectionner au moins une bibliothèque.");
            return;
        }

        // Gestion de l'option "Toutes"
        if (selectedLibraries.includes('all')) {
            keysToScan = $('#library-select option').map(function() {
                if (this.value && this.value !== 'all') return this.value;
            }).get();
        } else {
            keysToScan = selectedLibraries;
        }

        button.prop('disabled', true).find('i').addClass('fa-spin'); // Ajoute un effet de chargement

        fetch('/plex/api/scan_libraries', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ libraryKeys: keysToScan, userId: userId })
        })
        .then(response => response.json())
        .then(data => {
            alert(data.message);
        })
        .catch(error => {
            console.error('Erreur lors du scan:', error);
            alert('Une erreur technique est survenue.');
        })
        .finally(() => {
            button.prop('disabled', false).find('i').removeClass('fa-spin');
        });
    });

    // --- GESTION DE L'AJOUT AUX *ARR DEPUIS LES SUGGESTIONS ---
    $(document).on('click', '.add-to-arr-btn', function(e) {
        e.preventDefault();
        const button = $(this);
        const mediaType = button.data('media-type');
        const mediaId = button.data('id');
        const searchOnAdd = button.data('search-on-add');

        // Afficher un spinner
        button.closest('.btn-group').find('button').prop('disabled', true);

        // NOTE: The user prompt assumes a route at '/search/api/add_to_arr'.
        // I will need to check for this route and potentially create it.
        // For now, I will assume it exists as per the instructions.
        fetch('/search/api/add_to_arr', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                media_type: mediaType,
                id: mediaId,
                search_on_add: searchOnAdd
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                alert('Média ajouté avec succès !');
                // Remplacer le bouton par un badge "Déjà surveillé"
                button.closest('.btn-group').replaceWith('<span class="badge bg-success">Ajouté !</span>');
            } else {
                alert('Erreur : ' + data.message);
                // Réactiver les boutons en cas d'erreur
                button.closest('.btn-group').find('button').prop('disabled', false);
            }
        })
        .catch(error => {
            console.error('Erreur:', error);
            alert('Une erreur de communication est survenue.');
            button.closest('.btn-group').find('button').prop('disabled', false);
        });
    });

    // =================================================================
    // ### PARTIE 5 : GESTION DU DÉPLACEMENT DE MÉDIAS ###
    // =================================================================

    let activeMoveTaskId = null;
    let activeMoveMediaId = null;
    let moveCheckInterval = null;

    // --- A. Ouvrir la modale et charger les dossiers ---
    $(document).on('click', '.move-media-btn', function() {
        if (activeMoveTaskId) {
            alert("Un déplacement est déjà en cours. Veuillez attendre sa fin.");
            return;
        }

        const button = $(this);
        const mediaId = button.data('media-id');
        const mediaTitle = button.data('media-title');
        const mediaType = button.data('media-type'); // 'sonarr' or 'radarr'

        const modal = $('#move-media-modal');
        modal.find('#move-media-title').text(mediaTitle);
        const confirmBtn = modal.find('#confirm-move-btn');
        const folderSelect = modal.find('#root-folder-select');

        confirmBtn.data({ mediaId, mediaType });
        folderSelect.html('<option>Chargement...</option>').prop('disabled', true);

        fetch(`/plex/api/media/root_folders?type=${mediaType}`)
            .then(response => response.json())
            .then(folders => {
                folderSelect.html('').prop('disabled', false);
                if (folders && folders.length > 0) {
                    folders.forEach(folder => {
                        const freeSpace = folder.freeSpace_formatted ? `(Espace libre: ${folder.freeSpace_formatted})` : '';
                        const optionText = `${folder.path} ${freeSpace}`;
                        folderSelect.append(new Option(optionText, folder.path));
                    });
                } else {
                    folderSelect.html('<option>Aucun dossier trouvé.</option>').prop('disabled', true);
                }
            })
            .catch(err => {
                console.error("Erreur chargement dossiers:", err);
                folderSelect.html('<option>Erreur de chargement.</option>').prop('disabled', true);
            });
    });

    // --- B. Confirmer le déplacement et démarrer le polling ---
    $('#confirm-move-btn').on('click', function() {
        const btn = $(this);
        const mediaId = btn.data('mediaId');
        const mediaType = btn.data('mediaType');
        const newPath = $('#move-media-modal #root-folder-select').val();

        if (!newPath) {
            alert("Veuillez sélectionner un dossier de destination.");
            return;
        }

        if (!confirm(`Êtes-vous sûr de vouloir déplacer ce média vers "${newPath}" ?`)) {
            return;
        }

        btn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Lancement...');

        fetch('/plex/api/media/move', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mediaId, mediaType, newPath })
        })
        .then(response => response.json())
        .then(data => {
            bootstrap.Modal.getInstance(document.getElementById('move-media-modal')).hide();
            if (data.status === 'success') {
                activeMoveTaskId = data.task_id;
                activeMoveMediaId = mediaId; // Store the mediaId
                updateUIAfterMoveStart(mediaId);
                startMoveStatusPolling();
            } else {
                alert('Erreur: ' + data.message);
            }
        })
        .catch(err => {
            console.error("Erreur API déplacement:", err);
            alert("Erreur de communication lors du lancement du déplacement.");
        })
        .finally(() => {
            btn.prop('disabled', false).html('Valider le déplacement');
        });
    });

    function updateUIAfterMoveStart(mediaId) {
        const row = $(`tr[data-rating-key="${mediaId}"]`);
        row.addClass('opacity-50');
        row.find('.move-media-btn').html('<span class="spinner-border spinner-border-sm"></span>').prop('disabled', true);
        row.find('button').not('.move-media-btn').prop('disabled', true);
    }

    function startMoveStatusPolling() {
        if (moveCheckInterval) clearInterval(moveCheckInterval);

        moveCheckInterval = setInterval(() => {
            fetch('/plex/api/media/move_status')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'idle' || data.status === 'completed' || data.status === 'failed') {
                        clearInterval(moveCheckInterval);
                        moveCheckInterval = null;
                        const mediaIdToEnd = activeMoveMediaId; // Use the stored mediaId
                        activeMoveTaskId = null;
                        activeMoveMediaId = null;
                        updateUIAfterMoveEnd(mediaIdToEnd, data.status === 'completed');
                        alert(data.message || "Opération terminée.");
                        $('#apply-filters-btn').click(); // Refresh the table
                    }
                })
                .catch(err => {
                    console.error("Erreur polling statut:", err);
                    clearInterval(moveCheckInterval);
                    activeMoveTaskId = null;
                });
        }, 15000); // Poll every 15 seconds
    }

    function updateUIAfterMoveEnd(mediaId, wasSuccessful) {
        const row = $(`tr[data-rating-key="${mediaId}"]`);
        row.removeClass('opacity-50');
        const moveBtn = row.find('.move-media-btn');
        moveBtn.html('<i class="bi bi-folder-symlink"></i>').prop('disabled', false);
        row.find('button').prop('disabled', false);

        if(wasSuccessful) {
            moveBtn.addClass('btn-success').removeClass('btn-outline-info');
            setTimeout(() => {
                 moveBtn.removeClass('btn-success').addClass('btn-outline-info');
            }, 5000);
        }
    }

}); // Fin de $(document).ready