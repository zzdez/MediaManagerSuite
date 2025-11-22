// Fichier : app/static/js/search_logic.js

$(document).ready(function() {
    // Si des requêtes initiales sont injectées par Flask, on les exécute.
    if (typeof initialQueries !== 'undefined' && Array.isArray(initialQueries) && initialQueries.length > 0) {
        // 1. Activer l'onglet "Recherche Libre"
        const freeSearchTab = new bootstrap.Tab($('#torrent-search-tab')[0]);
        freeSearchTab.show();

        // 2. Lancer la recherche avec les requêtes
        const payload = {
            queries: initialQueries,
            search_type: 'sonarr' // Par défaut, la recherche d'épisodes manquants est pour les séries
        };
        executeProwlarrSearch(payload, searchModeIntent); // Passer l'intention de recherche
    }

    // CONTEXTE GLOBAL POUR LE PRE-MAPPING
    window.currentMediaContext = null;

    const modalEl = $('#sonarrRadarrSearchModal');
    const modalBody = modalEl.find('.modal-body');
    const TMDB_POSTER_BASE_URL = 'https://image.tmdb.org/t/p/w185';
    const searchPageContainer = $('#search-page-container');
    const mediaSearchUrl = searchPageContainer.data('media-search-url');

    // =================================================================
    // ### BLOC 1 : RECHERCHE DE MÉDIAS (FILMS/SÉRIES) - NOUVELLE IMPLEMENTATION ###
    // =================================================================

    let mediaSearchResults = [];

    function renderMediaResults(results, mediaType) {
        const resultsContainer = $('#media-results-container');
        resultsContainer.empty();

        if (!results || results.length === 0) {
            resultsContainer.html('<p class="mt-3">Aucun résultat trouvé.</p>');
            return;
        }

        const listGroup = $('<div class="list-group"></div>');
        results.forEach((item, index) => {
            const posterUrl = mediaType === 'movie' && item.poster
                ? `${TMDB_POSTER_BASE_URL}${item.poster}`
                : (item.poster || 'https://via.placeholder.com/185x278.png?text=No+Poster');

            // --- NOUVELLE LOGIQUE POUR LES BADGES ET BOUTONS ---
            const details = item.details || {};
            let badgesHtml = '';

            // 1. Badges Sonarr/Radarr
            const sonarrStatus = details.sonarr_status || {};
            const radarrStatus = details.radarr_status || {};
            if (sonarrStatus.present) {
                badgesHtml += `<span class="badge bg-info me-1">Sonarr</span>`;
                badgesHtml += sonarrStatus.monitored ? `<span class="badge bg-success me-1">Surveillé</span>` : `<span class="badge bg-secondary me-1">Non surveillé</span>`;
            } else if (radarrStatus.present) {
                badgesHtml += `<span class="badge bg-info me-1">Radarr</span>`;
                badgesHtml += radarrStatus.monitored ? `<span class="badge bg-success me-1">Surveillé</span>` : `<span class="badge bg-secondary me-1">Non surveillé</span>`;
            }

            // 2. Badge de Statut de Production (Séries seulement)
            const prodStatus = details.production_status || {};
            if (mediaType === 'tv' && prodStatus.status) {
                let statusText = prodStatus.status;
                let statusClass = 'bg-secondary';
                switch (prodStatus.status.toLowerCase()) {
                    case 'ended': statusText = 'Terminée'; statusClass = 'bg-dark'; break;
                    case 'continuing': statusText = 'En Production'; statusClass = 'bg-success'; break;
                    case 'upcoming': statusText = 'À venir'; statusClass = 'bg-info text-dark'; break;
                }
                badgesHtml += `<span class="badge ${statusClass} me-1">${statusText}</span>`;
            }

            // 3. Badge de Visionnage Plex OU Statut d'Archivage
            const plexStatus = details.plex_status || {};
            const archivedInfo = item.archived_info || {};

            if (archivedInfo.is_archived) {
                let tooltipText = `Archivé par ${archivedInfo.user}.`;
                if (mediaType === 'tv' && archivedInfo.seasons_watched && archivedInfo.seasons_watched.length > 0) {
                    tooltipText += ` Saisons vues: ${archivedInfo.seasons_watched.join(', ')}.`;
                } else if (mediaType === 'movie') {
                    tooltipText += ` Statut: ${archivedInfo.status}.`;
                }
                badgesHtml += `<span class="badge bg-dark me-1" data-bs-toggle="tooltip" title="${tooltipText}">Archivé</span>`;
            } else if (plexStatus.present) {
                if (mediaType === 'tv') {
                    if (plexStatus.is_watched) {
                        badgesHtml += `<span class="badge bg-primary me-1">Série Vue</span>`;
                    } else if (plexStatus.watched_episodes && !plexStatus.watched_episodes.startsWith('0/')) {
                        badgesHtml += `<span class="badge bg-primary me-1">Commencée (${plexStatus.watched_episodes})</span>`;
                    }
                } else { // Film
                    if (plexStatus.is_watched) {
                        badgesHtml += `<span class="badge bg-primary me-1">Vu</span>`;
                    }
                }
            }

            // 4. Logique pour les boutons
            let trailerBtnClass = 'btn-outline-danger';
            if (item.trailer_status === 'LOCKED') trailerBtnClass = 'btn-outline-success';
            else if (item.trailer_status === 'UNLOCKED') trailerBtnClass = 'btn-outline-primary';

            let buttonsHtml = `
                <button class="btn btn-sm ${trailerBtnClass} search-trailer-btn"
                        data-media-type="${mediaType}"
                        data-external-id="${item.id}"
                        data-title="${item.title}"
                        data-year="${item.year || ''}">
                    <i class="fas fa-video"></i> Bande-annonce
                </button>`;

            const isArchived = item.archived_info && item.archived_info.is_archived;

            if (!isArchived) {
                if (!sonarrStatus.present && !radarrStatus.present) {
                    buttonsHtml += `
                        <button class="btn btn-sm btn-outline-success add-to-arr-btn" data-result-index="${index}">
                            <i class="fas fa-plus"></i> Ajouter
                        </button>`;
                }

                buttonsHtml += `
                    <button class="btn btn-sm btn-primary search-torrents-btn" data-result-index="${index}">
                        <i class="fas fa-download"></i> Chercher les Torrents
                    </button>`;
            }

            // --- FIN DE LA NOUVELLE LOGIQUE ---

            // --- NOUVEAU : Logique pour la date de sortie ---
            let releaseDateHtml = '';
            const releaseDate = details.release_date;
            if (releaseDate) {
                const date = new Date(releaseDate);
                // Vérifier si la date est dans le futur
                if (date > new Date()) {
                    const formattedDate = date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }).replace('.', '');
                    releaseDateHtml = `<p class="mb-1 text-info"><small><strong>Sortie le :</strong> ${formattedDate}</small></p>`;
                }
            }

            // --- NOUVEAU : Logique pour le statut de téléchargement ---
            let downloadStatusHtml = '';
            if (radarrStatus.present) {
                const statusClass = radarrStatus.has_file ? 'bg-success' : 'bg-warning text-dark';
                const statusText = radarrStatus.has_file ? `Téléchargé (${radarrStatus.size_on_disk_gb})` : 'Manquant';
                downloadStatusHtml = `<span class="badge ${statusClass} me-1">${statusText}</span>`;
            } else if (sonarrStatus.present) {
                const statusClass = sonarrStatus.episodes_file_count > 0 ? 'bg-success' : 'bg-warning text-dark';
                const statusText = sonarrStatus.episodes_file_count > 0 ? 'Téléchargé' : 'Manquant';
                downloadStatusHtml = `
                    <div>
                        <span class="badge ${statusClass} me-1">${statusText}</span>
                    </div>
                    <div class="mt-1">
                        <small class="text-muted">
                            ${sonarrStatus.seasons_complete}/${sonarrStatus.seasons_total} Saisons -
                            (${sonarrStatus.episodes_file_count}/${sonarrStatus.episodes_count} ép.) -
                            ${sonarrStatus.size_on_disk_gb}
                        </small>
                    </div>`;
            }


            const cardHtml = `
                <div class="list-group-item list-group-item-action" data-media-type="${mediaType}">
                    <div class="row g-3">
                        <div class="col-md-2 col-sm-3">
                            <img src="${posterUrl}" class="img-fluid rounded" alt="Poster de ${item.title}">
                        </div>
                        <div class="col-md-10 col-sm-9">
                            <h5 class="mb-1">${item.title} <span class="text-muted">(${item.year || 'N/A'})</span></h5>
                            ${releaseDateHtml}
                            <p class="mb-1 small">${item.overview ? item.overview.substring(0, 280) + (item.overview.length > 280 ? '...' : '') : 'Pas de synopsis disponible.'}</p>
                            <div class="mt-2 mb-2">
                                ${badgesHtml}
                                ${downloadStatusHtml}
                            </div>
                            <div class="mt-2">
                                ${buttonsHtml}
                            </div>
                        </div>
                    </div>
                </div>`;
            listGroup.append(cardHtml);
        });
        resultsContainer.append(listGroup);

        // Activer les tooltips Bootstrap pour les nouveaux éléments
        const tooltipTriggerList = [].slice.call(resultsContainer[0].querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    function performMediaSearch() {
        window.currentMediaContext = null;

        const query = $('#media-search-input').val().trim();
        const mediaType = $('input[name="media_type"]:checked').val();
        const resultsContainer = $('#media-results-container');

        if (!query) {
            resultsContainer.html('<div class="alert alert-warning">Veuillez entrer un titre à rechercher.</div>');
            return;
        }

        resultsContainer.html('<div class="text-center p-5"><div class="spinner-border text-primary" role="status"></div></div>');

        if (!mediaSearchUrl) {
            resultsContainer.html('<div class="alert alert-danger">Erreur de configuration: URL de recherche de média non trouvée.</div>');
            return;
        }

        fetch(mediaSearchUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: query, media_type: mediaType })
        })
        .then(response => {
            if (!response.ok) return response.json().then(err => { throw new Error(err.error || `Erreur HTTP ${response.status}`) });
            return response.json();
        })
        .then(data => {
            if (data.error) {
                resultsContainer.html(`<div class="alert alert-danger">${data.error}</div>`);
                return;
            }
            mediaSearchResults = data;
            renderMediaResults(data, mediaType);
        })
        .catch(error => {
            console.error('Erreur lors de la recherche de média:', error);
            resultsContainer.html(`<div class="alert alert-danger">Une erreur est survenue: ${error.message}</div>`);
        });
    }

    $('#execute-media-search-btn').on('click', performMediaSearch);
    $('#media-search-input').on('keypress', function(e) {
        if (e.which == 13) { e.preventDefault(); performMediaSearch(); }
    });

    // --- GESTION DES BANDES-ANNONCES DE LA PAGE DE RECHERCHE (NOUVELLE VERSION) ---
    // Le code a été simplifié. Le gestionnaire d'événements global `global_trailer_search.js`
    // s'occupe maintenant de toute la logique, car le bouton a le bon `data-trailer-id-key`.
    $('#media-results-container').on('click', '.search-trailer-btn', function() {
        const button = $(this);
        const mediaType = button.data('media-type');
        const externalId = button.data('external-id');
        const title = button.data('title');
        const year = button.data('year');

        // Déclencher l'événement global avec les données du bouton.
        // Le script global s'occupera du reste.
        $(document).trigger('openTrailerSearch', { mediaType, externalId, title, year });
    });

    // --- MISE À JOUR EN TEMPS RÉEL DU BOUTON DE BANDE-ANNONCE ---
    $(document).on('trailerStatusUpdated', function(event, { mediaType, externalId, newStatus }) {
        // Cible à la fois le bouton de la page de recherche et celui dans la modale de mapping
        const buttonSelectors = [
            `.search-trailer-btn[data-media-type="${mediaType}"][data-external-id="${externalId}"]`,
            `.find-trailer-from-map-btn[data-media-id="${externalId}"]`
        ];

        const button = $(buttonSelectors.join(', '));

        if (button.length) {
            button.removeClass('btn-outline-success btn-outline-primary btn-outline-danger');
            let newClass = 'btn-outline-danger'; // NONE
            if (newStatus === 'LOCKED') newClass = 'btn-outline-success';
            else if (newStatus === 'UNLOCKED') newClass = 'btn-outline-primary';
            button.addClass(newClass);
        }
    });

    $('#media-results-container').on('click', '.search-torrents-btn', function() {
        resetFilters(); // Réinitialiser les filtres pour la nouvelle recherche
        const resultIndex = $(this).data('result-index');
        const mediaData = mediaSearchResults[resultIndex];
        const mediaType = $(this).closest('[data-media-type]').data('media-type'); // 'movie' ou 'tv'

        window.currentMediaContext = { ...mediaData, media_type: mediaType };

        // --- NOUVELLE LOGIQUE DE RECHERCHE MULTI-TITRES (Corrigée) ---
        const title = mediaData.title;
        const originalTitle = mediaData.original_title;
        const year = mediaData.year;

        // 1. Nettoyer les titres de base pour enlever l'année potentielle
        const cleanedTitle = title ? title.replace(/\(\d{4}\)/, '').trim() : '';
        const cleanedOriginalTitle = originalTitle ? originalTitle.replace(/\(\d{4}\)/, '').trim() : '';

        // 2. Créer les variations de titres à partir des versions nettoyées
        let finalQueries = new Set();
        if (cleanedTitle) {
            finalQueries.add(cleanedTitle); // Titre traduit sans année
            if (year && year !== 'N/A') {
                finalQueries.add(`${cleanedTitle} ${year}`); // Titre traduit avec année
            }
        }
        if (cleanedOriginalTitle && cleanedOriginalTitle !== cleanedTitle) {
            finalQueries.add(cleanedOriginalTitle); // Titre original sans année
            if (year && year !== 'N/A') {
                finalQueries.add(`${cleanedOriginalTitle} ${year}`); // Titre original avec année
            }
        }

        // 3. Pré-remplir le champ de recherche avec le titre principal et lancer la recherche
        $('#search-form input[name="query"]').val(cleanedTitle);

        const freeSearchTab = new bootstrap.Tab($('#torrent-search-tab')[0]);
        freeSearchTab.show();

        const payload = {
            queries: [...finalQueries], // Convertir le Set en Array
            search_type: mediaType === 'movie' ? 'radarr' : 'sonarr'
        };

        executeProwlarrSearch(payload);
    });

    // --- NOUVELLE LOGIQUE POUR L'AJOUT DIRECT SANS TORRENT ---
    $('#media-results-container').on('click', '.add-to-arr-btn', function() {
        const resultIndex = $(this).data('result-index');
        const mediaData = mediaSearchResults[resultIndex];
        const mediaType = $(this).closest('[data-media-type]').data('media-type');
        const modal = $('#add-to-arr-direct-modal');

        // Stocker les données nécessaires dans la modale
        modal.data('media-data', mediaData);
        modal.data('media-type', mediaType);

        // Mettre à jour le titre de la modale
        modal.find('#add-direct-media-title').text(mediaData.title);

        // Afficher/cacher le conteneur du profil de langue pour Sonarr
        modal.find('#add-direct-language-profile-container').toggle(mediaType === 'tv');

        // Réinitialiser et désactiver les sélecteurs et le bouton de confirmation
        modal.find('select').empty().prop('disabled', true).html('<option>Chargement...</option>');
        modal.find('#confirm-add-direct-btn').prop('disabled', true);
        modal.find('#add-direct-error-container').empty();

        // Afficher la modale
        new bootstrap.Modal(modal[0]).show();

        // Définir les URLs des API en fonction du type de média
        const rootFolderUrl = mediaType === 'tv' ? '/seedbox/api/get-sonarr-rootfolders' : '/seedbox/api/get-radarr-rootfolders';
        const qualityProfileUrl = mediaType === 'tv' ? '/seedbox/api/get-sonarr-qualityprofiles' : '/seedbox/api/get-radarr-qualityprofiles';
        const languageProfileUrl = mediaType === 'tv' ? '/seedbox/api/get-sonarr-language-profiles' : null;

        // Lancer les appels API
        const promises = [
            fetch(rootFolderUrl).then(res => res.json()),
            fetch(qualityProfileUrl).then(res => res.json())
        ];
        if (languageProfileUrl) {
            promises.push(fetch(languageProfileUrl).then(res => res.json()));
        }

        Promise.all(promises).then(([rootFolders, qualityProfiles, languageProfiles]) => {
            // Peupler le sélecteur de dossier racine
            const rootFolderSelect = modal.find('#add-direct-root-folder-select').empty().prop('disabled', false);
            rootFolders.forEach(folder => rootFolderSelect.append(new Option(folder.path, folder.path)));

            // Peupler le sélecteur de profil de qualité
            const qualityProfileSelect = modal.find('#add-direct-quality-profile-select').empty().prop('disabled', false);
            qualityProfiles.forEach(profile => qualityProfileSelect.append(new Option(profile.name, profile.id)));

            // Peupler le sélecteur de profil de langue si nécessaire
            if (languageProfiles) {
                const languageProfileSelect = modal.find('#add-direct-language-profile-select').empty().prop('disabled', false);
                languageProfiles.forEach(profile => languageProfileSelect.append(new Option(profile.name, profile.id)));
            }

            // Activer le bouton de confirmation
            modal.find('#confirm-add-direct-btn').prop('disabled', false);
        }).catch(error => {
            modal.find('#add-direct-error-container').text("Erreur lors du chargement des options depuis Sonarr/Radarr.");
            console.error("Erreur API pour la modale d'ajout:", error);
        });
    });

    $('#confirm-add-direct-btn').on('click', function() {
        const btn = $(this);
        const modal = $('#add-to-arr-direct-modal');
        const mediaData = modal.data('media-data');
        const mediaType = modal.data('media-type');
        const errorContainer = modal.find('#add-direct-error-container');

        const payload = {
            media_type: mediaType,
            external_id: mediaData.id,
            root_folder_path: modal.find('#add-direct-root-folder-select').val(),
            quality_profile_id: modal.find('#add-direct-quality-profile-select').val()
        };
        if (mediaType === 'tv') {
            payload.language_profile_id = modal.find('#add-direct-language-profile-select').val();
        }

        btn.prop('disabled', true).find('.spinner-border').removeClass('d-none');
        errorContainer.empty();

        fetch('/search/api/media/add_direct', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Fermer la modale
                bootstrap.Modal.getInstance(modal[0]).hide();
                toastr.success(data.message);

                // --- NOUVELLE LOGIQUE DE RAFRAÎCHISSEMENT ---
                // 1. Trouver l'index de l'élément à mettre à jour
                const itemIndex = mediaSearchResults.findIndex(item => item.id == mediaData.id);

                // 2. Appeler le nouvel endpoint pour obtenir les détails frais
                if (itemIndex !== -1) {
                    fetch(`/search/api/media/get_details?media_type=${mediaType}&external_id=${mediaData.id}`)
                        .then(res => res.json())
                        .then(newDetails => {
                            // 3. Mettre à jour les détails de l'élément dans notre cache local
                            mediaSearchResults[itemIndex].details = newDetails;

                            // 4. Redessiner toute la liste avec les données à jour
                            const currentMediaType = $('input[name="media_type"]:checked').val();
                            renderMediaResults(mediaSearchResults, currentMediaType);
                        })
                        .catch(err => {
                            console.error("Erreur lors du rafraîchissement de la fiche.", err);
                            // En cas d'erreur, on recharge toute la recherche comme avant
                            performMediaSearch();
                        });
                } else {
                    // Fallback si on ne trouve pas l'item, ce qui ne devrait pas arriver
                    performMediaSearch();
                }

            } else {
                errorContainer.text(data.message || "Une erreur est survenue.");
            }
        })
        .catch(error => {
            errorContainer.text("Erreur de communication avec le serveur.");
            console.error("Erreur lors de l'ajout direct:", error);
        })
        .finally(() => {
            btn.prop('disabled', false).find('.spinner-border').addClass('d-none');
        });
    });

    // =================================================================
    // ### BLOC 2 : RECHERCHE LIBRE (PROWLARR) ET STATUT ###
    // =================================================================

    function updateFilterVisibility() {
        const searchType = $('input[name="search_type"]:checked').val();

        // Filtres spécifiques aux séries
        const seriesOnlyFilters = $('#filterSeason, #filterEpisode');
        // Filtre spécifique aux films
        const movieOnlyFilters = $('#filterYear');
        // Le filtre "Type de Pack" est maintenant toujours visible
        // const packTypeFilter = $('#filterPackType');

        if (searchType === 'sonarr') { // Séries
            seriesOnlyFilters.closest('.col-md-3, .col-md-2').show();
            movieOnlyFilters.closest('.col-md-2').hide();
        } else { // 'radarr' pour les Films
            seriesOnlyFilters.closest('.col-md-3, .col-md-2').hide();
            movieOnlyFilters.closest('.col-md-2').show();
        }
    }

    let prowlarrResultsCache = []; // Cache pour les résultats actuels

    function populateFilters(results, filterOptions) {
        // Helper to populate a select dropdown
        const populateSelect = (selector, options) => {
            const select = $(selector);
            select.html('<option value="" selected>Tous</option>');
            if (options && options.length > 0) {
                select.append(options.sort().map(opt => `<option value="${opt}">${opt}</option>`).join(''));
            }
        };

        // Populate from configured lists
        populateSelect('#filterQuality', filterOptions.quality);
        populateSelect('#filterCodec', filterOptions.codec);
        populateSelect('#filterSource', filterOptions.source);
        populateSelect('#filterReleaseGroup', filterOptions.release_group);

        // Populate languages dynamically from results
        const languages = new Set();
        results.forEach(result => {
            if (result.language) {
                String(result.language).split(',').forEach(l => {
                    const lang = l.trim();
                    if(lang) languages.add(lang);
                });
            }
        });
        populateSelect('#filterLang', [...languages]);
    }

    function resetFilters() {
        $('#filterPackType, #filterQuality, #filterCodec, #filterSource, #filterLang, #filterReleaseGroup').val('');
        $('#filterYear, #filterSeason, #filterEpisode').val('');
        // Déclencher un changement pour que la liste se mette à jour et affiche tout
        applyClientSideFilters();
    }

    function applyClientSideFilters() {
        const activeFilters = {
            quality: ($('#filterQuality').val() || '').toLowerCase(),
            lang: ($('#filterLang').val() || '').toLowerCase(),
            source: ($('#filterSource').val() || '').toLowerCase(),
            codec: ($('#filterCodec').val() || '').toLowerCase(),
            releaseGroup: ($('#filterReleaseGroup').val() || '').toLowerCase(),
            year: ($('#filterYear').val() || ''),
            packType: ($('#filterPackType').val() || ''),
            season: ($('#filterSeason').val() || ''),
            episode: ($('#filterEpisode').val() || '')
        };

        let visibleCount = 0;
        $('.release-item').each(function() {
            const item = $(this);
            const data = item.data('parsed') || {}; // LIRE L'OBJET DE DONNÉES

            let show = true;

            // Filtres sur les chaînes de caractères
            if (activeFilters.quality && (data.quality || '').toLowerCase() !== activeFilters.quality) show = false;
            if (activeFilters.source && (data.source || '').toLowerCase() !== activeFilters.source) show = false;
            if (activeFilters.codec && (data.codec || '').toLowerCase() !== activeFilters.codec) show = false;
            if (activeFilters.releaseGroup && (data.release_group || '').toLowerCase() !== activeFilters.releaseGroup) show = false;
            if (activeFilters.lang && !(data.language || '').toLowerCase().includes(activeFilters.lang)) show = false;

            // Filtres sur les nombres
            if (activeFilters.year && data.year != activeFilters.year) show = false;
            if (activeFilters.season && data.season != activeFilters.season) show = false;
            if (activeFilters.episode && data.episode != activeFilters.episode) show = false;

            // Filtre intelligent "Type de Pack"
            if (activeFilters.packType) {
                if (activeFilters.packType === 'episode' && !data.is_episode) show = false;
                if (activeFilters.packType === 'season' && !data.is_season_pack) show = false;
                if (activeFilters.packType === 'collection' && !data.is_collection) show = false;
                // Le filtre "special" peut être combiné, donc on ne l'exclut pas des autres types
                if (activeFilters.packType === 'special' && !data.is_special) show = false;
            }

            // Appliquer le résultat
            item.toggleClass('d-none', !show);
            if (show) visibleCount++;
        });

        // Mettre à jour le compteur
        $('#results-count').text(visibleCount);
    }


    function executeProwlarrSearch(payload, searchIntent = null) {
        const resultsContainer = $('#search-results-container');
        resultsContainer.html('<div class="text-center p-5"><div class="spinner-border text-primary" role="status"></div><p class="mt-2">Recherche en cours...</p></div>');

        $('#advancedFilters').find('select, input').prop('disabled', true);

        fetch('/search/api/prowlarr/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => {
            if (!response.ok) throw new Error(`Erreur réseau: ${response.statusText}`);
            return response.json();
        })
        .then(data => {
            let results = data.results || [];
            const filterOptions = data.filter_options || {};

            // Appliquer le filtrage par intention si spécifié
            if (searchIntent === 'packs') {
                results = results.filter(r => r.is_season_pack);
            } else if (searchIntent === 'episodes') {
                results = results.filter(r => r.is_episode);
            }

            prowlarrResultsCache = results;

            if (data.error) {
                resultsContainer.html(`<div class="alert alert-danger">${data.error}</div>`);
                return;
            }

            if (results.length === 0) {
                resultsContainer.html('<div class="alert alert-info mt-3">Aucun résultat trouvé.</div>');
                $('#advancedFilters').collapse('hide');
                return;
            }

            populateFilters(results, filterOptions);

            resultsContainer.empty();
            const batchActionsContainer = $(`
                <div id="batch-actions-container" class="mb-3" style="display: none;">
                    <button id="batch-map-btn" class="btn btn-primary">
                        <i class="fas fa-object-group"></i> Mapper la sélection (<span id="batch-count">0</span>)
                    </button>
                </div>
            `);
            resultsContainer.append(batchActionsContainer);

            const header = $(`<hr><h4 class="mb-3">Résultats pour "${payload.query}" (<span id="results-count">${results.length}</span> / <span>${results.length}</span>)</h4>`);
            resultsContainer.append(header);

            const listGroup = $('<ul class="list-group"></ul>');
            results.forEach(result => {
                const sizeInGB = (result.size / 1024**3).toFixed(2);
                const seedersClass = result.seeders > 0 ? 'text-success' : 'text-danger';

                const itemContentHtml = `
                    <div class="p-2">
                        <input type="checkbox" class="form-check-input release-checkbox" aria-label="Sélectionner cette release">
                    </div>
                    <div class="me-auto" style="flex-basis: 60%; min-width: 300px;">
                        <strong></strong>
                        <br>
                        <small class="text-muted">
                            Indexer: ${result.indexer} | Taille: ${sizeInGB} GB | Seeders: <span class="${seedersClass}">${result.seeders}</span>
                        </small>
                    </div>
                    <div class="p-2" style="min-width: 150px; text-align: center;">
                        <button class="btn btn-sm btn-outline-info check-status-btn">Vérifier Statut</button>
                        <div class="spinner-border spinner-border-sm d-none" role="status"></div>
                    </div>
                    <div class="p-2">
                        <a href="#" class="btn btn-sm btn-success download-and-map-btn individual-map-btn">
                            <i class="fas fa-cogs"></i> & Mapper
                        </a>
                    </div>`;

                const listItem = $(`<li class="list-group-item d-flex justify-content-between align-items-center flex-wrap release-item"></li>`);
                listItem.html(itemContentHtml);

                listItem.data('parsed', result);

                listItem.find('strong').text(result.title);
                listItem.find('.check-status-btn').attr({ 'data-guid': result.guid, 'data-title': result.title });
                listItem.find('.download-and-map-btn').attr({
                    'data-title': result.title,
                    'data-download-link': result.downloadUrl,
                    'data-guid': result.guid,
                    'data-indexer-id': result.indexerId
                });

                listGroup.append(listItem);
            });
            resultsContainer.append(listGroup);

            // Correction: Appliquer le filtre par défaut APRÈS le rendu des résultats
            const langSelect = $('#filterLang');
            if (langSelect.find('option[value="fr"]').length > 0) {
                langSelect.val('fr');
            }
            applyClientSideFilters();

            $('#advancedFilters').find('select, input').prop('disabled', false);
            $('#advancedFilters').collapse('show');
        })
        .catch(error => {
            console.error("Erreur lors de la recherche Prowlarr:", error);
            resultsContainer.html(`<div class="alert alert-danger">Une erreur est survenue: ${error.message}</div>`);
        });
    }

    $('#advancedFilters').on('change', 'select, input', function() {
        applyClientSideFilters();
    });

    $('body').on('click', '#execute-prowlarr-search-btn', function() {
        window.currentMediaContext = null;
        resetFilters();

        const form = $('#search-form');
        const payload = {
            query: form.find('[name="query"]').val(),
            search_type: form.find('[name="search_type"]:checked').val()
        };

        if (!payload.query) {
            alert("Veuillez entrer un terme à rechercher.");
            return;
        }

        executeProwlarrSearch(payload);
    });

    $('body').on('click', '.check-status-btn', function() {
        const button = $(this);
        const guid = button.data('guid');
        const title = button.data('title');
        const statusContainer = button.parent();
        button.addClass('d-none');
        statusContainer.find('.spinner-border').removeClass('d-none');
        fetch('/search/check_media_status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ guid: guid, title: title })
        })
        .then(response => {
            if (!response.ok) { throw new Error(`Erreur réseau: ${response.statusText}`); }
            return response.json();
        })
        .then(data => {
            let statusHtml = '';
            if (data.error) { statusHtml = `<span class="text-danger small">${data.error}</span>`; }
            else { statusHtml = `<span class="text-success small"><strong>Statut :</strong> ${data.status}</span>`; }
            statusContainer.html(statusHtml);
        })
        .catch(error => {
            console.error('Erreur lors de la vérification du statut:', error);
            statusContainer.html(`<span class="text-danger small">Erreur.</span>`);
            setTimeout(() => {
                button.removeClass('d-none');
                statusContainer.find('.spinner-border').addClass('d-none');
                statusContainer.html(button);
            }, 2000);
        });
    });

    // =================================================================
    // ### BLOC 3 : LOGIQUE DE LA MODALE "& MAPPER" ###
    // =================================================================

    function displayResults(resultsData, mediaType) {
        const resultsContainer = modalBody.find('#lookup-results-container');
        let itemsHtml = '';
        if (resultsData && resultsData.length > 0) {
            itemsHtml = resultsData.map(item => {
                const bestMatchClass = item.is_best_match ? 'best-match' : '';
                const externalId = mediaType === 'tv' ? item.tvdbId : item.tmdbId;
                const mediaExists = item.id && item.id > 0;

                let trailerBtnClass = 'btn-outline-danger';
                if (item.trailer_status === 'LOCKED') {
                    trailerBtnClass = 'btn-outline-success';
                } else if (item.trailer_status === 'UNLOCKED') {
                    trailerBtnClass = 'btn-outline-primary';
                }

                const trailerButtonHtml = `
                    <button class="btn btn-sm ${trailerBtnClass} find-trailer-from-map-btn"
                            data-media-id="${externalId}"
                            data-title="${item.title}"
                            data-year="${item.year}"
                            data-media-type="${mediaType}">
                        <i class="bi bi-film"></i>
                    </button>`;

                const mainButtonHtml = mediaExists ?
                    `<button class="btn btn-sm btn-outline-primary enrich-details-btn" data-media-id="${externalId}" data-media-type="${mediaType}">Voir les détails</button>` :
                    `<button class="btn btn-sm btn-outline-success add-and-enrich-btn" data-ext-id="${externalId}" data-title="${item.title}" data-year="${item.year}" data-media-type="${mediaType}">Ajouter & Voir les détails</button>`;

                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center ${bestMatchClass}" data-result-item>
                        <div><strong>${item.title}</strong> (${item.year})${!mediaExists ? '<span class="badge bg-info ms-2">Nouveau</span>' : ''}</div>
                        <div class="btn-group">
                            ${trailerButtonHtml}
                            ${mainButtonHtml}
                        </div>
                    </div>`;
            }).join('');
        } else {
            itemsHtml = '<div class="alert alert-info mt-3">Aucun résultat trouvé. Essayez une recherche manuelle.</div>';
        }
        resultsContainer.html(`<div class="list-group list-group-flush">${itemsHtml}</div>`);
    }

    function populateAndShowAddItemView(mediaData) {
        const mediaType = mediaData.media_type;
        const instanceType = mediaType === 'tv' ? 'sonarr' : 'radarr';
        const externalId = mediaData.id;
        const title = mediaData.title;

        const optionsContainer = modalBody.find('#add-item-options-container');
        const lookupContainer = modalBody.find('#initial-lookup-content');
        const finalButton = modalEl.find('#confirm-add-and-map-btn');
        const detailsContainer = optionsContainer.find('#new-media-details-container');

        optionsContainer.data({ 'external-id': externalId, 'media-type': mediaType, 'title': title });
        lookupContainer.hide();
        optionsContainer.removeClass('d-none');
        finalButton.removeClass('d-none').prop('disabled', true); // On désactive le bouton par défaut
        detailsContainer.html('<div class="d-flex justify-content-center align-items-center p-3"><div class="spinner-border spinner-border-sm"></div><span class="ms-2">Chargement des détails...</span></div>');
        optionsContainer.find('select').empty().prop('disabled', true).html('<option>Chargement...</option>');
        optionsContainer.find('#add-item-error-container').empty();
        optionsContainer.find('#language-profile-select').parent().toggle(instanceType === 'sonarr');

        const enrichPromise = fetch('/search/api/enrich/details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: externalId, media_type: mediaType, is_new: true })
        }).then(res => res.ok ? res.json() : Promise.reject('enrichDetails'));

        let rootFolderUrl = instanceType === 'radarr' ? '/seedbox/api/get-radarr-rootfolders' : '/seedbox/api/get-sonarr-rootfolders';
        let qualityProfileUrl = instanceType === 'radarr' ? '/seedbox/api/get-radarr-qualityprofiles' : '/seedbox/api/get-sonarr-qualityprofiles';

        const optionsPromise = Promise.all([
            fetch(rootFolderUrl).then(res => res.ok ? res.json() : Promise.reject('rootFolders')),
            fetch(qualityProfileUrl).then(res => res.ok ? res.json() : Promise.reject('qualityProfiles'))
        ]);

        Promise.all([enrichPromise, optionsPromise]).then(([details, options]) => {
            if (details.error) {
                detailsContainer.html(`<div class="text-danger">${details.error}</div>`);
            } else {
                const enrichedHtml = `
                    <div class="card bg-dark text-white">
                        <div class="row g-0">
                            <div class="col-md-3">
                                <img src="${details.poster}" class="img-fluid rounded-start" alt="Poster">
                            </div>
                            <div class="col-md-9">
                                <div class="card-body">
                                    <h5 class="card-title">${details.title} (${details.year})</h5>
                                    <p class="card-text small"><strong>Statut:</strong> ${details.status}</p>
                                    <p class="card-text small" style="max-height: 100px; overflow-y: auto;">${details.overview || 'Synopsis non disponible.'}</p>
                                <button class="btn btn-sm btn-secondary back-to-lookup-btn mt-2">Retour à la liste</button>
                                </div>
                            </div>
                        </div>
                    </div>`;
                detailsContainer.html(enrichedHtml);
            }
            const [rootFolders, qualityProfiles] = options;
            const rootFolderSelect = $('#root-folder-select').empty();
            if (rootFolders && rootFolders.length > 0) {
                rootFolders.forEach(folder => rootFolderSelect.append(new Option(folder.path, folder.id)));
                rootFolderSelect.prop('disabled', false);
            } else {
                rootFolderSelect.html('<option>Aucun dossier trouvé</option>');
            }
            const qualityProfileSelect = $('#quality-profile-select').empty();
            if (qualityProfiles && qualityProfiles.length > 0) {
                qualityProfiles.forEach(profile => qualityProfileSelect.append(new Option(profile.name, profile.id)));
                qualityProfileSelect.prop('disabled', false);
            } else {
                qualityProfileSelect.html('<option>Aucun profil trouvé</option>');
            }

            if ($('#root-folder-select').val() && $('#quality-profile-select').val()) {
                finalButton.prop('disabled', false);
            }
        }).catch(error => {
            console.error("Erreur lors de la récupération des données pour l'ajout:", error);
            optionsContainer.find('#add-item-error-container').text("Une erreur critique est survenue. Veuillez vérifier les logs.");
        });
    }


    $('body').off('click', '.download-and-map-btn').on('click', '.download-and-map-btn', function(event) {
        event.preventDefault();
        const button = $(this);
        const releaseDetails = {
            title: button.data('title'),
            downloadLink: button.data('download-link'),
            guid: button.data('guid'),
            indexerId: button.data('indexer-id')
        };
        modalEl.data('release-details', releaseDetails);
        modalEl.data('release-details-batch', null); // Nettoyer les données du lot
        modalEl.find('.modal-title').text(`Mapper : ${releaseDetails.title}`);
        new bootstrap.Modal(modalEl[0]).show();

        // --- NOUVELLE LOGIQUE UNIVERSELLE DE CONTEXTE ---
        // On essaie de construire le contexte à partir du bouton lui-même,
        // ce qui le rend autonome et utilisable depuis le tableau de bord.
        if (!window.currentMediaContext && (button.data('tmdb-id') || button.data('tvdb-id'))) {
            const mediaType = button.data('media-type');
            window.currentMediaContext = {
                id: mediaType === 'tv' ? button.data('tvdb-id') : button.data('tmdb-id'),
                media_type: mediaType,
                title: button.data('title'),
                year: button.data('year')
            };
            console.log("Contexte créé à partir du bouton:", window.currentMediaContext);
        }
        // --- FIN DE LA NOUVELLE LOGIQUE ---

        if (window.currentMediaContext) {
            // NOUVEAU FLUX PRÉ-MAPPING : Utilise le contexte pour rechercher par ID mais affiche TOUJOURS la modale pour confirmation.
            const context = window.currentMediaContext;
            console.log("FLUX PRÉ-MAPPING (Corrigé) : Contexte trouvé. Lancement du lookup par ID.", context);

            const mediaType = context.media_type;
            modalBody.find('#add-item-options-container').addClass('d-none');
            modalEl.find('#confirm-add-and-map-btn').addClass('d-none');
            const lookupContent = modalBody.find('#initial-lookup-content').removeClass('d-none').show();
            lookupContent.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche de la correspondance exacte...</p></div>');

            fetch('/search/api/search/lookup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // Envoi de l'ID du média pour un résultat ciblé
                body: JSON.stringify({ media_id: context.id, media_type: mediaType })
            })
            .then(response => response.json())
            .then(data => {
                const idPlaceholder = mediaType === 'tv' ? 'ID TVDB...' : 'ID TMDb...';
                // On réutilise le même template que la recherche manuelle pour la cohérence
                const modalHtml = `
                    <div data-media-type="${mediaType}">
                        <p class="text-muted small">Le média correspondant a été pré-sélectionné. Confirmez ou effectuez une recherche manuelle.</p>
                        <h6>Recherche manuelle par Titre</h6>
                        <div class="input-group mb-2"><input type="text" id="manual-search-input" class="form-control" value="${context.title}"></div>
                        <div class="text-center text-muted my-2 small">OU</div>
                        <h6>Recherche manuelle par ID</h6>
                        <div class="input-group mb-3"><input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}"></div>
                        <button id="unified-search-button" class="btn btn-primary w-100 mb-3">Rechercher manuellement</button>
                        <hr>
                        <div id="lookup-results-container"></div>
                    </div>`;
                lookupContent.html(modalHtml);
                // La réponse contient le résultat unique qui sera marqué comme "best_match" par le backend
                displayResults(data.results, mediaType);

                // --- NOUVEAU: Ajout du sélecteur de type si ouvert depuis le Dashboard ---
                if (button.data('media-type')) { // Indique qu'on vient du dashboard ou d'un contexte avec type prédéfini
                    const typeSelectorHtml = `
                        <div class="mb-3 border-bottom pb-3">
                            <small class="text-muted">Type de média détecté. Changez si incorrect :</small>
                            <div class="form-check form-check-inline ms-2">
                                <input class="form-check-input" type="radio" name="modal_media_type" id="modal_media_type_tv" value="tv" ${mediaType === 'tv' ? 'checked' : ''}>
                                <label class="form-check-label" for="modal_media_type_tv">Série (Sonarr)</label>
                            </div>
                            <div class="form-check form-check-inline">
                                <input class="form-check-input" type="radio" name="modal_media_type" id="modal_media_type_movie" value="movie" ${mediaType === 'movie' ? 'checked' : ''}>
                                <label class="form-check-label" for="modal_media_type_movie">Film (Radarr)</label>
                            </div>
                        </div>`;
                    lookupContent.prepend(typeSelectorHtml);
                }
            })
            .catch(error => {
                console.error("Erreur lors du lookup pré-mappé:", error);
                lookupContent.html('<div class="alert alert-danger">Erreur lors de la récupération des détails du média.</div>');
            });

        } else {
            console.log("FLUX CLASSIQUE : Aucun contexte, lancement du lookup.");
            const button = $(this); // Assurer que 'button' est bien défini dans ce scope
            // --- NOUVELLE LOGIQUE UNIVERSELLE POUR DÉTERMINER LE TYPE DE MÉDIA ---
            let mediaType = button.data('media-type'); // Priorité 1: Attribut sur le bouton (Dashboard, Recherche par Média)
            if (!mediaType) {
                // Priorité 2: Bouton radio sur la page (Recherche Libre)
                mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';
            }
            // --- FIN DE LA NOUVELLE LOGIQUE ---

            modalBody.find('#add-item-options-container').addClass('d-none');
            modalEl.find('#confirm-add-and-map-btn').addClass('d-none');
            const lookupContent = modalBody.find('#initial-lookup-content').removeClass('d-none').show();
            lookupContent.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche des correspondances...</p></div>');
            
            fetch('/search/api/search/lookup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ term: releaseDetails.title, media_type: mediaType })
            })
            .then(response => response.json())
            .then(data => {
                const idPlaceholder = mediaType === 'tv' ? 'ID TVDB...' : 'ID TMDb...';
                const modalHtml = `
                    <div data-media-type="${mediaType}">
                        <p class="text-muted small">Le meilleur résultat est surligné. Si ce n'est pas le bon, utilisez la recherche manuelle.</p>
                        <h6>Recherche manuelle par Titre</h6>
                        <div class="input-group mb-2"><input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}"></div>
                        <div class="text-center text-muted my-2 small">OU</div>
                        <h6>Recherche manuelle par ID</h6>
                        <div class="input-group mb-3"><input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}"></div>
                        <button id="unified-search-button" class="btn btn-primary w-100 mb-3">Rechercher manuellement</button>
                        <hr>
                        <div id="lookup-results-container"></div>
                    </div>`;
                lookupContent.html(modalHtml);
                displayResults(data.results, mediaType);
            });
        }
    });

    // --- NOUVEAU: Gère le changement de type de média DANS la modale ---
    $('body').on('change', 'input[name="modal_media_type"]', function() {
        const newMediaType = $(this).val();
        const releaseDetails = modalEl.data('release-details');
        const resultsContainer = $('#lookup-results-container');

        if (!releaseDetails || !releaseDetails.title) return;

        resultsContainer.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche des correspondances...</p></div>');

        // Relancer la recherche de correspondance avec le nouveau type
        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: releaseDetails.title, media_type: newMediaType })
        })
        .then(response => response.json())
        .then(data => {
            // Mettre à jour le data-media-type du conteneur parent pour que les actions suivantes (ex: "Voir les détails") aient le bon contexte
            resultsContainer.closest('[data-media-type]').attr('data-media-type', newMediaType);
            displayResults(data.results, newMediaType);
        })
        .catch(error => {
            console.error("Erreur lors du changement de type de média:", error);
            resultsContainer.html('<div class="alert alert-danger">Erreur lors de la recherche.</div>');
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal .add-and-enrich-btn', function() {
        populateAndShowAddItemView({
            media_type: $(this).data('media-type'),
            id: $(this).data('ext-id'),
            title: $(this).data('title'),
            year: $(this).data('year')
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal .back-to-lookup-btn', function() {
        const releaseDetails = modalEl.data('release-details');
        if (!releaseDetails) { return; }
        const releaseTitle = releaseDetails.title;
        const mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';
        modalBody.find('#add-item-options-container').addClass('d-none');
        modalEl.find('#confirm-add-and-map-btn').addClass('d-none');
        const lookupContent = modalBody.find('#initial-lookup-content').removeClass('d-none').show();
        lookupContent.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Retour à la liste...</p></div>');
        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ term: releaseTitle, media_type: mediaType })
        })
        .then(response => response.json())
        .then(data => {
            const idPlaceholder = mediaType === 'tv' ? 'ID TVDB...' : 'ID TMDb...';
            const modalHtml = `
                <div data-media-type="${mediaType}">
                    <p class="text-muted small">Le meilleur résultat est surligné.</p>
                    <h6>Recherche manuelle par Titre</h6>
                    <div class="input-group mb-2"><input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}"></div>
                    <div class="text-center text-muted my-2 small">OU</div>
                    <h6>Recherche manuelle par ID</h6>
                    <div class="input-group mb-3"><input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}"></div>
                    <button id="unified-search-button" class="btn btn-primary w-100 mb-3">Rechercher manuellement</button>
                    <hr>
                    <div id="lookup-results-container"></div>
                </div>`;
            lookupContent.html(modalHtml);
            displayResults(data.results, mediaType);
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal #unified-search-button', function() {
        const button = $(this);
        const mediaType = button.closest('[data-media-type]').data('media-type');
        const titleQuery = $('#manual-search-input').val();
        const idQuery = $('#manual-id-input').val();
        let payload = { media_type: mediaType };
        if (idQuery) { payload.media_id = idQuery; }
        else if (titleQuery) { payload.term = titleQuery; }
        else { alert("Veuillez entrer un titre ou un ID."); return; }
        const resultsContainer = $('#lookup-results-container');
        resultsContainer.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div></div>');
        fetch('/search/api/search/lookup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => { displayResults(data.results, mediaType); });
    });

    $('body').on('change', '#root-folder-select, #quality-profile-select', function() {
        const rootFolder = $('#root-folder-select').val();
        const qualityProfile = $('#quality-profile-select').val();
        const finalButton = $('#confirm-add-and-map-btn');

        if (rootFolder && qualityProfile) {
            finalButton.prop('disabled', false);
        } else {
            finalButton.prop('disabled', true);
        }
    });

    $('body').off('click', '#confirm-add-and-map-btn').on('click', '#confirm-add-and-map-btn', function() {
        const button = $(this);
        const optionsContainer = modalBody.find('#add-item-options-container');
        const errorContainer = optionsContainer.find('#add-item-error-container');
        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Ajout en cours...');
        errorContainer.empty();
        const releaseDetails = modalEl.data('release-details');
        const mediaType = optionsContainer.data('media-type');
        const instanceType = mediaType === 'tv' ? 'sonarr' : 'radarr';
        const addPayload = {
            app_type: instanceType,
            external_id: optionsContainer.data('external-id'),
            title: optionsContainer.data('title'),
            root_folder_path: $('#root-folder-select').find('option:selected').text(),
            quality_profile_id: $('#quality-profile-select').val(),
            searchForMovie: false
        };
        fetch('/seedbox/api/add-arr-item-and-get-id', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(addPayload)
        })
        .then(response => {
            if (!response.ok) { return response.json().then(err => Promise.reject(err)); }
            return response.json();
        })
        .then(data => {
            if (data.error || !data.new_media_id) { throw new Error(data.error || "L'ID du nouveau média n'a pas été retourné."); }
            button.html('<span class="spinner-border spinner-border-sm"></span> Envoi au téléchargement...');

            const batchReleaseDetails = modalEl.data('release-details-batch');
            const singleReleaseDetails = modalEl.data('release-details');
            let fetchUrl, finalPayload;

            if (batchReleaseDetails && batchReleaseDetails.length > 0) {
                fetchUrl = '/search/batch-download-and-map';
                finalPayload = {
                    releases: batchReleaseDetails.map(release => ({
                        releaseName: release.title,
                        downloadLink: release.downloadLink,
                        guid: release.guid,
                        indexerId: release.indexerId
                    })),
                    instanceType: mediaType,
                    mediaId: data.new_media_id
                };
            } else {
                fetchUrl = '/search/download-and-map';
                finalPayload = {
                    releaseName: singleReleaseDetails.title,
                    downloadLink: singleReleaseDetails.downloadLink,
                    guid: singleReleaseDetails.guid,
                    indexerId: singleReleaseDetails.indexerId,
                    instanceType: mediaType,
                    mediaId: data.new_media_id
                };
            }

            return fetch(fetchUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(finalPayload)
            });
        })
        .then(response => response.json())
        .then(data => {
            const modalInstance = bootstrap.Modal.getInstance(modalEl[0]);
            if (data.status === 'success') {
                if(modalInstance) modalInstance.hide();
                alert(data.message || "Succès ! Le média a été ajouté et la ou les releases ont été envoyées au téléchargement.");
            } else {
                throw new Error(data.message || "Erreur lors de l'envoi au téléchargement.");
            }
        })
        .catch(error => {
            const errorMessage = error.message || "Une erreur inconnue est survenue.";
            errorContainer.text(errorMessage);
            button.prop('disabled', false).text('Ajouter, Télécharger & Mapper');
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal .enrich-details-btn', function() {
        const button = $(this);
        const container = button.closest('[data-result-item]');
        const mediaId = button.data('media-id');
        const mediaType = button.data('media-type');
        container.html('<div class="d-flex justify-content-center align-items-center p-3"><div class="spinner-border spinner-border-sm"></div></div>');
        fetch('/search/api/enrich/details', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: mediaId, media_type: mediaType })
        })
        .then(response => response.json())
        .then(details => {
            if (details.error) {
                container.html(`<div class="text-danger">${details.error}</div>`);
                return;
            }
            const enrichedHtml = `
                <div class="card bg-dark text-white">
                    <div class="row g-0">
                        <div class="col-md-3"><img src="${details.poster}" class="img-fluid rounded-start" alt="Poster"></div>
                        <div class="col-md-9"><div class="card-body">
                            <h5 class="card-title">${details.title} (${details.year})</h5>
                            <p class="card-text small"><strong>Statut:</strong> ${details.status}</p>
                            <p class="card-text small" style="max-height: 150px; overflow-y: auto;">${details.overview || 'Synopsis non disponible.'}</p>
                            <button class="btn btn-sm btn-primary confirm-mapping-btn me-2" data-media-id="${details.id}">Choisir ce média</button>
                            <button class="btn btn-sm btn-secondary back-to-lookup-btn">Retour à la liste</button>
                        </div></div>
                    </div>
                </div>`;
            container.removeClass('list-group-item d-flex justify-content-between align-items-center').html(enrichedHtml);
        })
        .catch(err => {
            container.html('<div class="text-danger">Erreur de communication.</div>');
            console.error("Erreur d'enrichissement:", err);
        });
    });

    $('body').on('click', '#sonarrRadarrSearchModal .confirm-mapping-btn', function() {
        const button = $(this);
        const selectedMediaId = button.data('media-id');
        const mediaType = button.closest('[data-media-type]').data('media-type');
        const batchReleaseDetails = modalEl.data('release-details-batch');
        const singleReleaseDetails = modalEl.data('release-details');

        button.prop('disabled', true).html('<span class="spinner-border spinner-border-sm"></span> Confirmation...');

        let fetchUrl, payload;

        if (batchReleaseDetails && batchReleaseDetails.length > 0) {
            // Mode Batch
            fetchUrl = '/search/batch-download-and-map';
            payload = {
                releases: batchReleaseDetails.map(release => ({
                    releaseName: release.title,
                    downloadLink: release.downloadLink,
                    guid: release.guid,
                    indexerId: release.indexerId
                })),
                instanceType: mediaType,
                mediaId: selectedMediaId
            };
        } else {
            // Mode Unique
            fetchUrl = '/search/download-and-map';
            payload = {
                releaseName: singleReleaseDetails.title,
                downloadLink: singleReleaseDetails.downloadLink,
                guid: singleReleaseDetails.guid,
                indexerId: singleReleaseDetails.indexerId,
                instanceType: mediaType,
                mediaId: selectedMediaId
            };
        }

        fetch(fetchUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            const modalInstance = bootstrap.Modal.getInstance(modalEl[0]);
            if (data.status === 'success') {
                if(modalInstance) modalInstance.hide();
                alert(data.message || "Succès ! La ou les releases ont été envoyées au téléchargement.");
            } else {
                alert("Erreur : " + data.message);
                button.prop('disabled', false).text('Choisir ce média');
            }
        })
        .catch(error => {
            console.error("Erreur lors du mapping final:", error);
            alert("Une erreur de communication est survenue.");
            button.prop('disabled', false).text('Choisir ce média');
        });
    });

    // Gestion de la visibilité des filtres intelligents
    $('input[name="search_type"]').on('change', updateFilterVisibility);

    // Appel initial pour définir le bon état au chargement de la page
    updateFilterVisibility();

    // --- GESTION DES BANDES-ANNONCES DEPUIS LA MODALE DE MAPPING (NOUVELLE VERSION) ---
    $('body').on('click', '.find-trailer-from-map-btn', function(e) {
        e.stopPropagation();

        const button = $(this);
        const mediaType = button.data('media-type');
        const externalId = button.data('media-id');
        const title = button.data('title');
        const year = button.data('year');

        if (mediaType && externalId && title) {
            $(document).trigger('openTrailerSearch', {
                mediaType,
                externalId,
                title,
                year,
                sourceModalId: 'sonarrRadarrSearchModal'
            });
        } else {
            alert('Erreur: Informations manquantes pour rechercher la bande-annonce.');
        }
    });

    // =================================================================
    // ### BLOC 4 : LOGIQUE DE SÉLECTION MULTIPLE (BATCH) ###
    // =================================================================

    function updateBatchActions() {
        const selectedCheckboxes = $('.release-checkbox:checked');
        const batchActionsContainer = $('#batch-actions-container');
        const batchMapBtn = $('#batch-map-btn');
        const batchCount = $('#batch-count');
        const individualMapButtons = $('.individual-map-btn');

        if (selectedCheckboxes.length >= 2) {
            batchActionsContainer.show();
            batchCount.text(selectedCheckboxes.length);
            individualMapButtons.addClass('disabled').attr('aria-disabled', 'true');
        } else {
            batchActionsContainer.hide();
            individualMapButtons.removeClass('disabled').attr('aria-disabled', 'false');
        }
    }

    // Écouteur pour les changements sur les cases à cocher
    $('#search-results-container').on('change', '.release-checkbox', function() {
        updateBatchActions();
    });

    // =================================================================
    // ### BLOC 5 : RÉINITIALISATION DE LA MODALE & MAPPER ###
    // =================================================================

    modalEl.on('hidden.bs.modal', function () {
        // 1. Vider le contenu dynamique
        modalBody.find('#initial-lookup-content').empty();
        modalBody.find('#add-item-options-container').addClass('d-none').find('#new-media-details-container').empty();
        modalBody.find('#lookup-results-container').empty();

        // 2. Réinitialiser le titre de la modale
        modalEl.find('.modal-title').text('Mapper');

        // 3. Cacher et réinitialiser les boutons du pied de page
        modalEl.find('#confirm-add-and-map-btn').addClass('d-none').prop('disabled', false).text('Ajouter, Télécharger & Mapper');

        // 4. Nettoyer les données stockées sur l'élément de la modale
        modalEl.removeData('release-details');
        modalEl.removeData('release-details-batch');

        // 5. Réinitialiser le contexte global si nécessaire
        window.currentMediaContext = null;
    });

    // Écouteur pour le bouton de mappage de lot
    $('#search-results-container').on('click', '#batch-map-btn', function() {
        const selectedItems = [];
        $('.release-checkbox:checked').each(function() {
            const listItem = $(this).closest('.release-item');
            // Correction ici : utiliser .individual-map-btn pour être plus spécifique
            const mapButton = listItem.find('.individual-map-btn');
            const releaseDetails = {
                title: mapButton.data('title'),
                downloadLink: mapButton.data('download-link'),
                guid: mapButton.data('guid'),
                indexerId: mapButton.data('indexer-id')
            };
            selectedItems.push(releaseDetails);
        });

        if (selectedItems.length > 0) {
            const referenceTitle = selectedItems[0].title;
            modalEl.data('release-details-batch', selectedItems);
            modalEl.data('release-details', null); // Nettoyer les données de la sélection unique
            modalEl.find('.modal-title').text(`Mapper ${selectedItems.length} releases`);

            // Afficher la modale
            new bootstrap.Modal(modalEl[0]).show();

            // Déterminer le media_type et préparer le contenu de la modale
            const mediaType = $('input[name="search_type"]:checked').val() === 'sonarr' ? 'tv' : 'movie';
            const lookupContent = modalBody.find('#initial-lookup-content').removeClass('d-none').show();

            // Vider les autres parties de la modale
            modalBody.find('#add-item-options-container').addClass('d-none');
            modalEl.find('#confirm-add-and-map-btn').addClass('d-none');

            // Afficher le spinner
            lookupContent.html('<div class="text-center p-4"><div class="spinner-border text-primary"></div><p class="mt-2">Recherche des correspondances...</p></div>');

            // Lancer la recherche de correspondance
            fetch('/search/api/search/lookup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ term: referenceTitle, media_type: mediaType })
            })
            .then(response => response.json())
            .then(data => {
                const idPlaceholder = mediaType === 'tv' ? 'ID TVDB...' : 'ID TMDb...';

                // Construire le résumé des releases sélectionnées
                let releasesSummaryHtml = '<div class="alert alert-secondary mb-3"><h6>Releases sélectionnées :</h6><ul class="list-unstyled mb-0 small">';
                selectedItems.forEach(item => {
                    releasesSummaryHtml += `<li><i class="fas fa-file-video me-2"></i>${item.title}</li>`;
                });
                releasesSummaryHtml += '</ul></div>';

                const modalHtml = `
                    ${releasesSummaryHtml}
                    <div data-media-type="${mediaType}">
                        <p class="text-muted small">Le meilleur résultat pour le lot est surligné. Si ce n'est pas le bon, utilisez la recherche manuelle.</p>
                        <h6>Recherche manuelle par Titre</h6>
                        <div class="input-group mb-2"><input type="text" id="manual-search-input" class="form-control" value="${data.cleaned_query}"></div>
                        <div class="text-center text-muted my-2 small">OU</div>
                        <h6>Recherche manuelle par ID</h6>
                        <div class="input-group mb-3"><input type="number" id="manual-id-input" class="form-control" placeholder="${idPlaceholder}"></div>
                        <button id="unified-search-button" class="btn btn-primary w-100 mb-3">Rechercher manuellement</button>
                        <hr>
                        <div id="lookup-results-container"></div>
                    </div>`;
                lookupContent.html(modalHtml);
                displayResults(data.results, mediaType);
            })
            .catch(error => {
                console.error("Erreur lors du lookup pour le lot:", error);
                lookupContent.html('<div class="alert alert-danger">Erreur lors de la recherche des correspondances.</div>');
            });
        }
    });
});
