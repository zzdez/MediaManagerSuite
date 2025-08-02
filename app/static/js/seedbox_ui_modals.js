// ========================================================================== //
// MODAL RELATED JAVASCRIPT FUNCTIONS                                         //
// ========================================================================== //

// --- Globals that might be needed by modal functions ---
let currentlySelectedSonarrSeriesIdInModal = null;
let currentAddTorrentAppType = null;

// --- Helper Functions ---
function escapeJsString(str) {
    if (str === null || typeof str === 'undefined') { return ''; }
    return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t').replace(/</g, '\\u003C').replace(/>/g, '\\u003E').replace(/&/g, '\\u0026');
}
// C'est votre fonction originale, mais rendue plus fiable

function getCleanedSearchTerm(itemName) {
    const baseNameForSearch = itemName.split(/[\\/]/).pop();
    let cleanedName = baseNameForSearch;
    
    // On retire les tags un par un. C'est plus sûr.
    cleanedName = cleanedName.replace(/\.(mkv|mp4|avi|srt|nfo|jpg|png)$/i, '');
    cleanedName = cleanedName.replace(/[\.\[\(]?\d{3,4}p[\.\]\)]?/ig, ' ');
    // --- LA CORRECTION EST SUR CETTE LIGNE ---
    // On remplace les tags par un espace pour éviter que les mots se collent.
    cleanedName = cleanedName.replace(/[\._\-\(\[]?(hdtv|web-dl|webrip|bluray|x264|x265|h264|h265|hevc|ac3|dts|multi|vfq|vff|vof|french|truefrench|fanart|pack|aac|720p|1080p|2160p)[\._\-\)\]]?/ig, ' ');
    cleanedName = cleanedName.replace(/[\.\[\(]?S\d{1,3}(E\d{1,3}(-E?\d{1,3}(\s?-\s?E?\d{1,3})?)?)?[\.\]\)]?/ig, ' ');
    cleanedName = cleanedName.replace(/[\.\[\(]?\d{4}[\.\]\)]?/g, ' '); // Nettoie aussi les années
    
    // Tentative de suppression du nom de la team/release, souvent après le dernier '-'
    const lastDashIndex = cleanedName.lastIndexOf('-');
    if (lastDashIndex > cleanedName.length / 2) { // Heuristique : le nom de la team est plutôt vers la fin
        const potentialTeamName = cleanedName.substring(lastDashIndex + 1).trim();
        // Si la "team" ne contient pas de chiffres (peu probable pour un titre) et est courte, on la supprime.
        if (!/\d/.test(potentialTeamName) && potentialTeamName.length < 10) {
             cleanedName = cleanedName.substring(0, lastDashIndex);
        }
    }

    // Nettoyage final des séparateurs et des espaces multiples
    cleanedName = cleanedName.replace(/[\._-]+/g, ' ').replace(/\s+/g, ' ').trim();

    // Si après tout ça, le nom est vide, on retourne un fallback simple.
    return cleanedName || baseNameForSearch.split('.')[0];
}

function flashMessageGlobally(message, category) {
    const container = document.querySelector('div.container.mt-4');
    if (!container) {
        console.warn("Flash message global container 'div.container.mt-4' not found. Message:", message);
        return;
    }

    let targetElement = null;
    // Try to find a specific element to insert before, for better placement
    // Prioritize inserting after elements that are typically at the top of the content area.
    let preferredInsertPoint = container.querySelector('header.border-bottom + .btn-toolbar, header.border-bottom + h1, header.border-bottom + h2, header.border-bottom + p, header.border-bottom + div.alert, #sftpActionFeedback + p.text-muted, #sftpActionFeedback + .file-tree');

    const alertHtml = `<div class="alert alert-${category} alert-dismissible fade show" role="alert" style="margin-top: 1rem;">
        ${escapeJsString(message)}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    </div>`;

    if (preferredInsertPoint && preferredInsertPoint.insertAdjacentHTML) {
         preferredInsertPoint.insertAdjacentHTML('afterend', alertHtml); // Insert after the found element
         targetElement = preferredInsertPoint.nextElementSibling; // The new alert
    } else if (container.firstChild && container.firstChild.insertAdjacentHTML) {
        // Fallback: insert before the first child element of the container
        container.firstChild.insertAdjacentHTML('beforebegin', alertHtml);
        targetElement = container.firstChild.previousElementSibling; // The new alert
    } else if (container.insertAdjacentHTML) {
        // Fallback: insert at the beginning of the container itself
        container.insertAdjacentHTML('afterbegin', alertHtml);
        targetElement = container.firstChild; // The new alert
    } else {
        console.error("flashMessageGlobally: Could not find a valid target element to insert the message using insertAdjacentHTML. Appending to container as last resort.");
        // Last resort: append as a child, might not be styled/positioned ideally
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = alertHtml;
        if (tempDiv.firstChild) {
            container.appendChild(tempDiv.firstChild);
            targetElement = container.lastChild;
        } else {
            return; // Cannot insert
        }
    }

    if (targetElement && typeof targetElement.scrollIntoView === 'function') {
        targetElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

// --- Sonarr/Radarr Search Modals (Generic for Staging, Problem Items, etc.) ---
function openSonarrSearchModal(itemPathForAction, itemType) {
    const itemNameForDisplay = itemPathForAction.split(/[\\/]/).pop();
    const sonarrModalElement = document.getElementById('sonarrSearchModal');
    if (!sonarrModalElement) { console.error("Modal Sonarr (ID: sonarrSearchModal) non trouvé!"); return; }

    sonarrModalElement.setAttribute('data-current-action', 'mapIndividualStaging');
    sonarrModalElement.removeAttribute('data-is-new-series');
    sonarrModalElement.removeAttribute('data-selected-media-id');
    sonarrModalElement.removeAttribute('data-selected-media-title');
    sonarrModalElement.removeAttribute('data-problem-torrent-hash');

    document.getElementById('sonarrItemToMap').textContent = itemNameForDisplay;
    document.getElementById('sonarrOriginalItemName').value = itemPathForAction;
    document.getElementById('sonarrOriginalItemType').value = itemType;
    document.getElementById('sonarrItemType').textContent = itemType === 'directory' ? 'Dossier (Staging)' : 'Fichier (Staging)';
    document.getElementById('sonarrSearchQuery').value = getCleanedSearchTerm(itemPathForAction);
        
    // --- LIGNE AJOUTÉE ---
    executeSonarrSearch(); // Pour lancer la recherche automatiquement après avoir rempli le champ

    document.getElementById('sonarrSearchResults').innerHTML = '';
    document.getElementById('sonarrSearchModalFeedbackZone').innerHTML = ''; // Clear previous feedback
    document.getElementById('sonarrSelectedSeriesId').value = '';
    document.getElementById('sonarrSelectedSeriesTitle').innerText = 'Aucune série sélectionnée';
    document.getElementById('sonarrManualSeasonDiv').style.display = 'none';
    document.getElementById('sonarrManualSeasonInput').value = '';
    currentlySelectedSonarrSeriesIdInModal = null;

    const modalMapButton = document.getElementById('sonarrModalMapButton');
    if (modalMapButton) {
        modalMapButton.innerHTML = '<i class="fas fa-link"></i> Mapper à cette Série';
        modalMapButton.disabled = true;
        modalMapButton.className = 'btn btn-primary';

        modalMapButton.onclick = function() {
            // ... (le reste de votre fonction onclick reste identique)
            const seriesTitle = document.getElementById('sonarrSelectedSeriesTitle').innerText.replace('Série sélectionnée : ', '');
            const userForcedSeason = document.getElementById('sonarrManualSeasonInput').value;
            const isNewMedia = sonarrModalElement.getAttribute('data-is-new-media') === 'true';
            const mediaIdForPayload = sonarrModalElement.getAttribute('data-selected-media-id');
            const mediaTitleForAdd = sonarrModalElement.getAttribute('data-selected-media-title');
            const currentAction = sonarrModalElement.getAttribute('data-current-action');

            if (!mediaIdForPayload) {
                alert("Veuillez sélectionner une série.");
                return;
            }

            if (currentAction === 'mapIndividualStaging' && isNewMedia) {
                const mediaYear = sonarrModalElement.getAttribute('data-selected-media-year');
                const searchResultData = { id: mediaIdForPayload, title: mediaTitleForAdd, year: parseInt(mediaYear) || 0 };
                promptAndAddArrItemForLocalStaging(searchResultData, 'sonarr', sonarrModalElement);
            } else {
                triggerSonarrManualImportWithSeason(mediaIdForPayload, seriesTitle, userForcedSeason);
            }
        };
    }
    var modal = new bootstrap.Modal(sonarrModalElement);
    modal.show();
}

function openRadarrSearchModal(itemPathForAction, itemType) {
    const itemNameForDisplay = itemPathForAction.split(/[\\/]/).pop();
    const radarrModalElement = document.getElementById('radarrSearchModal');
    if (!radarrModalElement) { console.error("Modal Radarr (ID: radarrSearchModal) non trouvé!"); return; }

    radarrModalElement.setAttribute('data-current-action', 'mapIndividualStaging');
    radarrModalElement.removeAttribute('data-is-new-media');
    radarrModalElement.removeAttribute('data-selected-media-id');
    radarrModalElement.removeAttribute('data-selected-media-title');
    radarrModalElement.removeAttribute('data-selected-media-year');
    radarrModalElement.removeAttribute('data-problem-torrent-hash');

    document.getElementById('radarrItemToMap').textContent = itemNameForDisplay;
    document.getElementById('radarrOriginalItemName').value = itemPathForAction;
    document.getElementById('radarrOriginalItemType').value = itemType;
    document.getElementById('radarrItemType').textContent = itemType === 'directory' ? 'Dossier (Staging)' : 'Fichier (Staging)';
    document.getElementById('radarrSearchQuery').value = getCleanedSearchTerm(itemPathForAction);

    // --- LIGNE AJOUTÉE ---
    executeRadarrSearch(); // Pour lancer la recherche automatiquement après avoir rempli le champ

    document.getElementById('radarrSearchResults').innerHTML = '';
    const radarrFeedbackZone = document.getElementById('radarrSearchModalFeedbackZone');
    if (radarrFeedbackZone) radarrFeedbackZone.innerHTML = '';
    document.getElementById('radarrSelectedMovieId').value = '';
    document.getElementById('radarrSelectedMovieTitle').innerText = 'Aucun film sélectionné';

    const modalMapButton = document.getElementById('radarrModalMapButton');
    if (modalMapButton) {
        modalMapButton.innerHTML = '<i class="fas fa-link"></i> Mapper à ce Film';
        modalMapButton.disabled = true;
        modalMapButton.className = 'btn btn-primary';
        modalMapButton.onclick = function() {
            // ... (le reste de votre fonction onclick reste identique)
            const radarrModalElement = document.getElementById('radarrSearchModal');
            const isNewMedia = radarrModalElement.getAttribute('data-is-new-media') === 'true';
            const mediaIdForPayload = radarrModalElement.getAttribute('data-selected-media-id');
            const mediaTitleForAdd = radarrModalElement.getAttribute('data-selected-media-title');
            let currentAction = radarrModalElement.getAttribute('data-current-action');

            if (!mediaIdForPayload) {
                alert("Veuillez sélectionner un film.");
                return;
            }

            if (currentAction === 'mapIndividualStaging' && isNewMedia) {
                const mediaYear = radarrModalElement.getAttribute('data-selected-media-year');
                const searchResultData = { id: mediaIdForPayload, title: mediaTitleForAdd, year: parseInt(mediaYear) || 0 };
                promptAndAddArrItemForLocalStaging(searchResultData, 'radarr', radarrModalElement);
            } else {
                triggerRadarrManualImport(mediaIdForPayload, mediaTitleForAdd);
            }
        };
    }
    var modal = new bootstrap.Modal(radarrModalElement);
    modal.show();
}

function openSonarrSearchModalForProblemItem(releaseName, currentTargetId, torrentHash) {
    const sonarrModalElement = document.getElementById('sonarrSearchModal');
    if (!sonarrModalElement) { console.error("Modal Sonarr (ID: sonarrSearchModal) non trouvé pour item problématique!"); return; }

    sonarrModalElement.setAttribute('data-current-action', 'mapProblemItem');
    sonarrModalElement.setAttribute('data-problem-torrent-hash', torrentHash || '');
    sonarrModalElement.removeAttribute('data-is-new-series');
    sonarrModalElement.removeAttribute('data-selected-media-id');
    sonarrModalElement.removeAttribute('data-selected-media-title');

    document.getElementById('sonarrItemToMap').textContent = releaseName;
    document.getElementById('sonarrOriginalItemName').value = releaseName;
    document.getElementById('sonarrItemType').textContent = 'Item problématique (Torrent)';
    document.getElementById('sonarrSearchQuery').value = getCleanedSearchTerm(releaseName);
    document.getElementById('sonarrSearchResults').innerHTML = '';
    document.getElementById('sonarrSearchModalFeedbackZone').innerHTML = '';
    document.getElementById('sonarrSelectedSeriesId').value = currentTargetId || '';
    document.getElementById('sonarrSelectedSeriesTitle').innerText = currentTargetId ? `Série actuelle (problème): ID ${currentTargetId}` : 'Aucune série sélectionnée';
    document.getElementById('sonarrManualSeasonDiv').style.display = currentTargetId ? 'block' : 'none';
    document.getElementById('sonarrManualSeasonInput').value = '';
    currentlySelectedSonarrSeriesIdInModal = currentTargetId || null;

    const modalMapButton = document.getElementById('sonarrModalMapButton');
    if (modalMapButton) {
        modalMapButton.innerHTML = '<i class="fas fa-link"></i> Re-Mapper à cette Série';
        modalMapButton.disabled = !currentTargetId;
        modalMapButton.className = 'btn btn-primary';
        modalMapButton.onclick = function() {
            const seriesTitle = document.getElementById('sonarrSelectedSeriesTitle').innerText.replace('Série sélectionnée : ', '').replace(`Série actuelle (problème): ID ${currentTargetId}`, '').trim();
            const userForcedSeason = document.getElementById('sonarrManualSeasonInput').value;
            const isNewSeries = sonarrModalElement.getAttribute('data-is-new-series') === 'true';
            const mediaIdForPayload = sonarrModalElement.getAttribute('data-selected-media-id') || document.getElementById('sonarrSelectedSeriesId').value;
            const mediaTitleForAdd = sonarrModalElement.getAttribute('data-selected-media-title');
            if (mediaIdForPayload) {
                triggerSonarrManualImportWithSeason(mediaIdForPayload, seriesTitle || "Série sélectionnée", userForcedSeason, isNewSeries, mediaTitleForAdd);
            } else { alert("Veuillez sélectionner une série."); }
        };
    }
    var modal = new bootstrap.Modal(sonarrModalElement);
    modal.show();
}

function openRadarrSearchModalForProblemItem(releaseName, currentTargetId, torrentHash) {
    const radarrModalElement = document.getElementById('radarrSearchModal');
    if (!radarrModalElement) { console.error("Modal Radarr (ID: radarrSearchModal) non trouvé pour item problématique!"); return; }

    radarrModalElement.setAttribute('data-current-action', 'mapProblemItem');
    radarrModalElement.setAttribute('data-problem-torrent-hash', torrentHash || '');

    document.getElementById('radarrItemToMap').textContent = releaseName;
    document.getElementById('radarrOriginalItemName').value = releaseName;
    document.getElementById('radarrItemType').textContent = 'Item problématique (Torrent)';
    document.getElementById('radarrSearchQuery').value = getCleanedSearchTerm(releaseName);
    document.getElementById('radarrSearchResults').innerHTML = '';
    const radarrFeedbackZone = document.getElementById('radarrSearchModalFeedbackZone');
    if (radarrFeedbackZone) radarrFeedbackZone.innerHTML = '';
    document.getElementById('radarrSelectedMovieId').value = currentTargetId || '';
    document.getElementById('radarrSelectedMovieTitle').innerText = currentTargetId ? `Film actuel (problème): ID ${currentTargetId}` : 'Aucun film sélectionné';

    const modalMapButton = document.getElementById('radarrModalMapButton');
    if (modalMapButton) {
        modalMapButton.innerHTML = '<i class="fas fa-link"></i> Re-Mapper à ce Film';
        modalMapButton.disabled = !currentTargetId;
        modalMapButton.className = 'btn btn-primary';
        modalMapButton.onclick = function() {
            const movieId = document.getElementById('radarrSelectedMovieId').value;
            const movieTitle = document.getElementById('radarrSelectedMovieTitle').innerText.replace('Film sélectionné : ', '').replace(`Film actuel (problème): ID ${currentTargetId}`, '').trim();
            if (movieId) { triggerRadarrManualImport(movieId, movieTitle || "Film sélectionné"); }
            else { alert("Veuillez sélectionner un film."); }
        };
    }
    var modal = new bootstrap.Modal(radarrModalElement);
    modal.show();
}

async function executeSonarrSearch() {
    const query = document.getElementById('sonarrSearchQuery').value;
    const resultsDiv = document.getElementById('sonarrSearchResults');
    const feedbackDiv = document.getElementById('sonarrSearchModalFeedbackZone');
    if(feedbackDiv) feedbackDiv.innerHTML = ''; // Clear previous feedback

    if (!resultsDiv) { console.error("Div 'sonarrSearchResults' non trouvée."); return; }
    if (!query.trim()) { resultsDiv.innerHTML = '<p class="text-warning">Terme de recherche manquant.</p>'; return; }
    resultsDiv.innerHTML = `<div class="d-flex align-items-center"><strong role="status">Recherche Sonarr...</strong><div class="spinner-border ms-auto"></div></div>`;

    try {
        const response = await fetch(`${window.appUrls.searchSonarrApi}?query=${encodeURIComponent(query)}`);
        if (!response.ok) {
            let eD; try { eD = await response.json(); } catch (e) { eD = { error: "Erreur serveur." }; }
            throw new Error(eD.error || `HTTP ${response.status}`);
        }
        const results = await response.json();
        if (results.length === 0) { resultsDiv.innerHTML = '<p class="text-muted">Aucune série trouvée.</p>'; return; }
        let html = '<ul class="list-group mt-3">';
        results.forEach(series => {
            let posterUrl = series.remotePoster || (series.images && series.images.length > 0 ? series.images.find(img => img.coverType === 'poster')?.remoteUrl : 'data:image/svg+xml;charset=UTF-8,%3Csvg%20width%3D%2260%22%20height%3D%2290%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2060%2090%22%20preserveAspectRatio%3D%22none%22%3E%3Cdefs%3E%3Cstyle%20type%3D%22text%2Fcss%22%3E%23holder_1582426688c%20text%20%7B%20fill%3A%23AAAAAA%3Bfont-weight%3Abold%3Bfont-family%3AArial%2C%20Helvetica%2C%20Open%20Sans%2C%20sans-serif%2C%20monospace%3Bfont-size%3A10pt%20%7D%20%3C%2Fstyle%3E%3C%2Fdefs%3E%3Cg%20id%3D%22holder_1582426688c%22%3E%3Crect%20width%3D%2260%22%20height%3D%2290%22%20fill%3D%22%23EEEEEE%22%3E%3C%2Frect%3E%3Cg%3E%3Ctext%20x%3D%2213.171875%22%20y%3D%2249.5%22%3EN/A%3C%2Ftext%3E%3C%2Fg%3E%3C%2Fg%3E%3C%2Fsvg%3E');
            const escapedSeriesTitle = escapeJsString(series.title);
            const sonarrIdAsInt = parseInt(series.id);
            const isAlreadyInSonarr = !isNaN(sonarrIdAsInt) && sonarrIdAsInt > 0;
            const idForHandler = isAlreadyInSonarr ? sonarrIdAsInt : (parseInt(series.tvdbId) || 0);
            let buttonText = isAlreadyInSonarr ? "Sélectionner" : "Ajouter & Sélectionner";
            let buttonIcon = isAlreadyInSonarr ? "fas fa-check-circle" : "fas fa-plus-circle";
            let buttonClass = isAlreadyInSonarr ? "btn-success" : "btn-info";
            let buttonTitle = isAlreadyInSonarr ? `Mapper à la série existante : ${series.title}` : `Ajouter la série '${series.title}' à Sonarr et la sélectionner`;
            let disabledReason = !idForHandler ? "ID externe/interne manquant ou invalide" : "";

            // Ajout des data-attributes pour le nouveau handler sur #sonarrRadarrResults
            html += `
                <li class="list-group-item" data-media-id="${idForHandler || 0}" data-instance-type="sonarr" style="cursor: pointer;">
                    <div class="row align-items-center">
                    <div class="col-auto"><img src="${posterUrl}" alt="${escapedSeriesTitle}" class="img-fluid rounded" style="max-height: 90px;" onerror="this.onerror=null; this.src='https://via.placeholder.com/60x90?text=ImgErr';"></div>
                    <div class="col">
                        <strong>${series.title}</strong> (${series.year || 'N/A'})<br>
                        <small class="text-muted">
                            Statut: <span class="fw-bold ${isAlreadyInSonarr ? 'text-success' : 'text-primary'}">${isAlreadyInSonarr ? (series.status || 'Gérée') : 'Non Ajoutée'}</span>
                            | TVDB ID: ${series.tvdbId || 'N/A'}
                            ${isAlreadyInSonarr && series.id ? `| Sonarr ID: ${series.id}` : ''}
                        </small>
                        <p class="mb-0 small">${(series.overview || '').substring(0, 120)}${(series.overview || '').length > 120 ? '...' : ''}</p>
                    </div>
                    <div class="col-auto">
                        <button type="button" class="btn ${buttonClass} btn-sm"
                                onclick="handleGenericSonarrSeriesSelection(${idForHandler || 0}, '${escapedSeriesTitle}', ${isAlreadyInSonarr})"
                                title="${buttonTitle}" ${disabledReason ? `disabled title="${disabledReason}"` : ''}>
                            <i class="${buttonIcon}"></i> ${buttonText}
                        </button>
                    </div>
                </div></li>`;
        });
        html += '</ul>';
        resultsDiv.innerHTML = html;
    } catch (error) {
        resultsDiv.innerHTML = ''; // Clear loading spinner
        if(feedbackDiv) feedbackDiv.innerHTML = `<p class="alert alert-danger">Erreur recherche Sonarr: ${escapeJsString(error.message)}</p>`;
        else resultsDiv.innerHTML = `<p class="text-danger">Erreur recherche Sonarr: ${escapeJsString(error.message)}</p>`;
        console.error("Erreur executeSonarrSearch:", error);
    }
}

async function executeRadarrSearch() {
    const query = document.getElementById('radarrSearchQuery').value;
    const resultsDiv = document.getElementById('radarrSearchResults');
    const feedbackDiv = document.getElementById('radarrSearchModalFeedbackZone'); // Assuming similar ID for Radarr
    if(feedbackDiv) feedbackDiv.innerHTML = '';

    if (!resultsDiv) { console.error("Div 'radarrSearchResults' non trouvée."); return; }
    if (!query.trim()) { resultsDiv.innerHTML = '<p class="text-warning">Terme de recherche manquant.</p>'; return; }
    resultsDiv.innerHTML = `<div class="d-flex align-items-center"><strong role="status">Recherche Radarr...</strong><div class="spinner-border ms-auto"></div></div>`;

    try {
        const response = await fetch(`${window.appUrls.searchRadarrApi}?query=${encodeURIComponent(query)}`);
        if (!response.ok) {
            let eD; try { eD = await response.json(); } catch (e) { eD = { error: "Erreur serveur Radarr." }; }
            throw new Error(eD.error || `HTTP ${response.status}`);
        }
        const results = await response.json();
        if (results.length === 0) { resultsDiv.innerHTML = '<p class="text-muted">Aucun film trouvé.</p>'; return; }
        let html = '<ul class="list-group mt-3">';
        results.forEach(movie => {
            let posterUrl = movie.remotePoster || (movie.images && movie.images.length > 0 ? movie.images.find(img => img.coverType === 'poster')?.remoteUrl : 'data:image/svg+xml;charset=UTF-8,%3Csvg%20width%3D%2260%22%20height%3D%2290%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2060%2090%22%20preserveAspectRatio%3D%22none%22%3E%3Cdefs%3E%3Cstyle%20type%3D%22text%2Fcss%22%3E%23holder_1582426688c%20text%20%7B%20fill%3A%23AAAAAA%3Bfont-weight%3Abold%3Bfont-family%3AArial%2C%20Helvetica%2C%20Open%20Sans%2C%20sans-serif%2C%20monospace%3Bfont-size%3A10pt%20%7D%20%3C%2Fstyle%3E%3C%2Fdefs%3E%3Cg%20id%3D%22holder_1582426688c%22%3E%3Crect%20width%3D%2260%22%20height%3D%2290%22%20fill%3D%22%23EEEEEE%22%3E%3C%2Frect%3E%3Cg%3E%3Ctext%20x%3D%2213.171875%22%20y%3D%2249.5%22%3EN/A%3C%2Ftext%3E%3C%2Fg%3E%3C%2Fg%3E%3C%2Fsvg%3E');
            const escapedMovieTitle = escapeJsString(movie.title);
            const isAlreadyInRadarr = movie.id && movie.id > 0;
            console.log("executeRadarrSearch - movie.id:", movie.id, "isAlreadyInRadarr:", isAlreadyInRadarr); // AJOUT CONSOLE.LOG
            const idForHandler = isAlreadyInRadarr ? movie.id : movie.tmdbId;
            let buttonText = isAlreadyInRadarr ? "Sélectionner" : "Ajouter & Sélectionner";
            let buttonIcon = "fas fa-check-circle";
            let buttonClass = "btn-success";
            let buttonTitle = `Sélectionner le film: ${movie.title}`;
            if (!isAlreadyInRadarr) {
                 buttonText = "Ajouter & Sélectionner"; buttonIcon = "fas fa-plus-circle"; buttonClass = "btn-info";
                 buttonTitle = `Ajouter le film '${movie.title}' à Radarr et le sélectionner`;
            }

            // Ajout des data-attributes pour le nouveau handler sur #sonarrRadarrResults
            html += `
                <li class="list-group-item" data-media-id="${idForHandler || 0}" data-instance-type="radarr" style="cursor: pointer;">
                    <div class="row align-items-center">
                    <div class="col-auto"><img src="${posterUrl}" alt="Poster" class="img-fluid rounded" style="max-height: 90px;" onerror="this.onerror=null; this.src='https://via.placeholder.com/60x90?text=ImgErr';"></div>
                    <div class="col"><strong>${movie.title}</strong> (${movie.year || 'N/A'})<br><small class="text-muted">Statut: ${movie.status || 'N/A'} | TMDB ID: ${movie.tmdbId || 'N/A'} ${isAlreadyInRadarr ? `| Radarr ID: ${movie.id}` : ''}</small><p class="mb-0 small">${(movie.overview || '').substring(0, 120)}${(movie.overview || '').length > 120 ? '...' : ''}</p></div>
                    <div class="col-auto"><button class="btn ${buttonClass} btn-sm" onclick="handleGenericRadarrMovieSelection(${idForHandler || 0}, '${escapedMovieTitle}', ${isAlreadyInRadarr}, ${movie.year || 0})" title="${buttonTitle}" ${idForHandler ? '' : 'disabled title="ID manquant"'}><i class="${buttonIcon}"></i> ${buttonText}</button></div>
                </div></li>`;
        });
        html += '</ul>';
        resultsDiv.innerHTML = html;
    } catch (error) {
        resultsDiv.innerHTML = ''; // Clear loading spinner
        if(feedbackDiv) feedbackDiv.innerHTML = `<p class="alert alert-danger">Erreur recherche Radarr: ${escapeJsString(error.message)}</p>`;
        else resultsDiv.innerHTML = `<p class="text-danger">Erreur recherche Radarr: ${escapeJsString(error.message)}</p>`;
        console.error("Erreur executeRadarrSearch:", error);
    }
}

function handleGenericSonarrSeriesSelection(mediaId, seriesTitle, isAlreadyInArr, seriesYear) {
    const sonarrModalElement = document.getElementById('sonarrSearchModal');
    if (!sonarrModalElement) return;

    // mediaId ici est l'ID Sonarr si isAlreadyInArr est true, sinon c'est tvdbId pour un nouveau média.
    document.getElementById('sonarrSelectedSeriesId').value = mediaId; // Stocke l'ID pertinent (Sonarr ID ou TVDB ID)
    document.getElementById('sonarrSelectedSeriesTitle').innerText = `Série sélectionnée : ${seriesTitle}`;
    currentlySelectedSonarrSeriesIdInModal = mediaId; // Peut-être renommer ou clarifier son usage

    sonarrModalElement.setAttribute('data-selected-media-id', mediaId); // ID Sonarr ou TVDB ID
    sonarrModalElement.setAttribute('data-selected-media-title', seriesTitle);
    sonarrModalElement.setAttribute('data-is-new-media', !isAlreadyInArr); // true si nouveau, false si existant
    sonarrModalElement.setAttribute('data-selected-media-year', seriesYear || 0); // Stocker l'année

    const modalMapButton = document.getElementById('sonarrModalMapButton');
    const currentAction = sonarrModalElement.getAttribute('data-current-action');

    if (modalMapButton) {
        modalMapButton.disabled = !mediaId;
        if (!isAlreadyInArr && currentAction === 'sftpRetrieveAndMapIndividual') {
            modalMapButton.innerHTML = '<i class="fas fa-plus-download"></i> Rapatrier, Ajouter & Mapper';
            modalMapButton.className = 'btn btn-info'; // Ou une autre couleur pour distinguer
        } else if (currentAction === 'sftpRetrieveAndMapIndividual') { // Média existant pour SFTP
            modalMapButton.innerHTML = '<i class="fas fa-link"></i> Rapatrier & Mapper';
            modalMapButton.className = 'btn btn-primary';
        } else if (!isAlreadyInArr && currentAction === 'mapIndividualStaging') { // Nouveau média pour staging local
            modalMapButton.innerHTML = '<i class="fas fa-plus-circle"></i> Ajouter & Mapper';
            modalMapButton.className = 'btn btn-info';
        } else { // Cas par défaut (ex: staging local, média existant)
            modalMapButton.innerHTML = '<i class="fas fa-link"></i> Mapper à cette Série';
            modalMapButton.className = 'btn btn-primary';
        }
    }

    const feedbackDiv = document.getElementById('sonarrSearchModalFeedbackZone');
    if (feedbackDiv) {
        feedbackDiv.innerHTML = `<p class="alert alert-info mt-2">Série sélectionnée : <strong>${seriesTitle}</strong> (ID: ${mediaId}).<br>
        ${isAlreadyInArr ? 'Cette série est déjà gérée par Sonarr.' : 'Cette série n\'est pas encore dans Sonarr.'}<br>
        Cliquez sur le bouton d'action.</p>`;
    }

    const manualSeasonDiv = document.getElementById('sonarrManualSeasonDiv');
    if (manualSeasonDiv) {
        // Afficher la sélection de saison si c'est un média existant et l'action le permet
        if (isAlreadyInArr && (currentAction === 'mapIndividualStaging' || currentAction === 'mapProblemItem' || currentAction === 'sftpRetrieveAndMapIndividual')) {
            manualSeasonDiv.style.display = 'block';
        } else {
            manualSeasonDiv.style.display = 'none';
        }
    }

    // Les options d'ajout (Root Folder, Quality Profile) pour un *nouveau* média SFTP
    // seront gérées par promptAndExecuteSftpNewMediaAddAndMap
    // Ici, on s'assure juste que le bouton et le feedback sont corrects.
}

function handleGenericRadarrMovieSelection(mediaId, movieTitle, isAlreadyInArr, movieYear) {
    console.log("handleGenericRadarrMovieSelection - isAlreadyInArr:", isAlreadyInArr, "Setting data-is-new-media to:", !isAlreadyInArr); // AJOUT CONSOLE.LOG
    const radarrModalElement = document.getElementById('radarrSearchModal');
    if (!radarrModalElement) return;

    // mediaId ici est l'ID Radarr si isAlreadyInArr est true, sinon c'est tmdbId pour un nouveau média.
    document.getElementById('radarrSelectedMovieId').value = mediaId; // Stocke l'ID pertinent
    document.getElementById('radarrSelectedMovieTitle').innerText = `Film sélectionné : ${movieTitle}`;

    radarrModalElement.setAttribute('data-selected-media-id', mediaId); // Radarr ID ou TMDB ID
    radarrModalElement.setAttribute('data-selected-media-title', movieTitle);
    radarrModalElement.setAttribute('data-is-new-media', !isAlreadyInArr); // true si nouveau, false si existant
    radarrModalElement.setAttribute('data-selected-media-year', movieYear || 0); // Stocker l'année
    console.log("Attribute data-is-new-media set to:", radarrModalElement.getAttribute('data-is-new-media')); // AJOUT CONSOLE.LOG

    const modalMapButton = document.getElementById('radarrModalMapButton');
    const currentAction = radarrModalElement.getAttribute('data-current-action');

    if (modalMapButton) {
        modalMapButton.disabled = !mediaId;
        if (!isAlreadyInArr && currentAction === 'sftpRetrieveAndMapIndividual') {
            modalMapButton.innerHTML = '<i class="fas fa-plus-download"></i> Rapatrier, Ajouter & Mapper';
            modalMapButton.className = 'btn btn-info';
        } else if (currentAction === 'sftpRetrieveAndMapIndividual') { // Média existant pour SFTP
            modalMapButton.innerHTML = '<i class="fas fa-link"></i> Rapatrier & Mapper';
            modalMapButton.className = 'btn btn-primary';
        } else if (!isAlreadyInArr && currentAction === 'mapIndividualStaging') { // Nouveau média pour staging local
            modalMapButton.innerHTML = '<i class="fas fa-plus-circle"></i> Ajouter & Mapper';
            modalMapButton.className = 'btn btn-info';
        } else { // Cas par défaut
            modalMapButton.innerHTML = '<i class="fas fa-link"></i> Mapper à ce Film';
            modalMapButton.className = 'btn btn-primary';
        }
    }

    const feedbackDiv = document.getElementById('radarrSearchModalFeedbackZone');
    if (feedbackDiv) {
        feedbackDiv.innerHTML = `<p class="alert alert-info mt-2">Film sélectionné : <strong>${movieTitle}</strong> (ID: ${mediaId}).<br>
        ${isAlreadyInArr ? 'Ce film est déjà géré par Radarr.' : 'Ce film n\'est pas encore dans Radarr.'}<br>
        Cliquez sur le bouton d'action.</p>`;
    }

    // Les options d'ajout (Root Folder, Quality Profile) pour un *nouveau* média SFTP
    // seront gérées par promptAndExecuteSftpNewMediaAddAndMap
}


async function triggerSonarrManualImportWithSeason(mediaIdFromSelection, seriesTitleForDisplay, userForcedSeason, isNewSeries_OBSOLETE, mediaTitleForAdd_OBSOLETE) {
    const originalItemName = document.getElementById('sonarrOriginalItemName').value;
    const feedbackDiv = document.getElementById('sonarrSearchModalFeedbackZone'); // Use dedicated feedback zone
    const sonarrModalElement = document.getElementById('sonarrSearchModal');
    if (!mediaIdFromSelection && mediaIdFromSelection !== 0) { alert("Aucun ID de série valide."); return; }

    if (feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-info">Import pour '${escapeJsString(originalItemName.split(/[\\/]/).pop())}' vers la série '${escapeJsString(seriesTitleForDisplay)}'...</div>`;
    else { console.warn("sonarrSearchModalFeedbackZone not found for in-modal messages.");}


    const problemTorrentHash = sonarrModalElement ? sonarrModalElement.getAttribute('data-problem-torrent-hash') : null;
    const payload = {
        item_name: originalItemName, is_new_series: isNewSeries,
        problem_torrent_hash: (problemTorrentHash && problemTorrentHash !== '') ? problemTorrentHash : null
    };
    if (isNewSeries) {
        payload.tvdb_id = parseInt(mediaIdFromSelection);
        payload.series_title_for_add = mediaTitleForAdd;
    } else { payload.series_id = parseInt(mediaIdFromSelection); }
    if (userForcedSeason && userForcedSeason.trim() !== '') { payload.user_forced_season = parseInt(userForcedSeason); }

    const modalMapButton = document.getElementById('sonarrModalMapButton');
    if (modalMapButton) modalMapButton.disabled = true;

    try {
        const actionUrl = window.appUrls.sonarrManualImport;
        const response = await fetch(actionUrl, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (!response.ok && !(response.status === 200 && result.action_required)) { throw new Error(result.error || `Erreur HTTP: ${response.status}`); }

        if (result.success === true) {
            if (feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-success">${escapeJsString(result.message) || 'Action initiée.'}</div>`;
            else console.log("Success message (no feedback div):", result.message);
            flashMessageGlobally(result.message || `Action pour '${escapeJsString(originalItemName.split(/[\\/]/).pop())}' initiée.`, 'success');
            setTimeout(() => {
                const modalInstance = bootstrap.Modal.getInstance(sonarrModalElement);
                if (modalInstance) modalInstance.hide(); window.location.reload();
            }, 2500);
        } else if (result.action_required === "resolve_season_episode_mismatch") {
            console.warn("Discordance S/E. UI dédiée nécessaire.", result.details);
            if (feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-warning">Discordance S/E: ${escapeJsString(result.message || '')} <br>Détails: ${escapeJsString(JSON.stringify(result.details))}</div>`;
        } else { throw new Error(result.error || "Erreur inconnue."); }
    } catch (error) {
        if (feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-danger">${escapeJsString(error.message)}</div>`;
        else console.error("Error (no feedback div):", error.message);
        flashMessageGlobally(`Erreur action Sonarr: ${escapeJsString(error.message)}`, 'danger');
    } finally { if (modalMapButton) modalMapButton.disabled = false; }
}

async function triggerRadarrManualImport(radarrMovieId, movieTitleForDisplay) {
    const originalItemName = document.getElementById('radarrOriginalItemName').value;
    const feedbackDiv = document.getElementById('radarrSearchModalFeedbackZone'); // Use dedicated feedback zone
    const radarrModalElement = document.getElementById('radarrSearchModal');
    if (!radarrMovieId || radarrMovieId === 0) { alert("ID film invalide."); return; }

    if(feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-info">Import pour '${escapeJsString(originalItemName.split(/[\\/]/).pop())}' vers '${escapeJsString(movieTitleForDisplay)}'...</div>`;
    else { console.warn("radarrSearchModalFeedbackZone not found for in-modal messages.");}


    const problemTorrentHash = radarrModalElement ? radarrModalElement.getAttribute('data-problem-torrent-hash') : null;
    const payload = { item_name: originalItemName, movie_id: parseInt(radarrMovieId) };
    if (problemTorrentHash && problemTorrentHash !== '') { payload.problem_torrent_hash = problemTorrentHash; }

    const modalMapButton = document.getElementById('radarrModalMapButton');
    if(modalMapButton) modalMapButton.disabled = true;

    try {
        const actionUrl = window.appUrls.radarrManualImport;
        const response = await fetch(actionUrl, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok && result.success) {
            if(feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-success">${escapeJsString(result.message) || 'Import Radarr réussi.'}</div>`;
            else console.log("Success message (no feedback div):", result.message);
            flashMessageGlobally(result.message || `Import pour '${escapeJsString(originalItemName.split(/[\\/]/).pop())}' réussi.`, 'success');
            setTimeout(() => {
                const modalInstance = bootstrap.Modal.getInstance(radarrModalElement);
                if (modalInstance) modalInstance.hide(); window.location.reload();
            }, 2500);
        } else { throw new Error(result.error || "Erreur inconnue (import Radarr)."); }
    } catch (error) {
        if(feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-danger">Erreur: ${escapeJsString(error.message)}</div>`;
        else console.error("Error (no feedback div):", error.message);
        flashMessageGlobally(`Erreur import Radarr: ${escapeJsString(error.message)}`, 'danger');
    } finally { if(modalMapButton) modalMapButton.disabled = false; }
}

async function forceSonarrImport(stagingItemName, seriesId, strategy, targetSeason, targetEpisode, seriesTitleForDisplay, problemTorrentHash = null) {
    const feedbackDiv = document.getElementById('sonarrSearchModalFeedbackZone');
    if (feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-info">Import forcé pour '${escapeJsString(stagingItemName.split(/[\\/]/).pop())}' vers '${escapeJsString(seriesTitleForDisplay)}' (S${targetSeason}E${targetEpisode}) stratégie '${strategy}'...</div>`;

    const payload = {
        item_name: stagingItemName, series_id: seriesId, target_season: targetSeason,
        target_episode: targetEpisode, strategy: strategy
    };
    if (problemTorrentHash) { payload.problem_torrent_hash = problemTorrentHash; }

    try {
        const response = await fetch(window.appUrls.forceSonarrImport, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok && result.success) {
            if (feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-success">${escapeJsString(result.message) || 'Réussi.'}</div>`;
            flashMessageGlobally(result.message || "Importation forcée réussie.", 'success');
            setTimeout(() => {
                const mismatchModal = bootstrap.Modal.getInstance(document.getElementById('sonarrSeasonEpisodeMismatchModal'));
                if (mismatchModal) mismatchModal.hide();
                const sonarrModal = bootstrap.Modal.getInstance(document.getElementById('sonarrSearchModal'));
                if (sonarrModal) sonarrModal.hide();
                window.location.reload();
            }, 3000);
        } else { throw new Error(result.error || "Erreur inconnue (import forcé)."); }
    } catch (error) {
        if (feedbackDiv) feedbackDiv.innerHTML = `<div class="alert alert-danger">Erreur: ${escapeJsString(error.message)}</div>`;
    }
}

// --- Add Torrent Modal Logic ---
function initializeAddTorrentModal() {
    const modalElement = document.getElementById('addTorrentModal');
    if (!modalElement) { console.error("Modal 'addTorrentModal' introuvable !"); return; }
    document.getElementById('addTorrentForm').reset();
    document.getElementById('addTorrentArrSearchSection').style.display = 'none';
    document.getElementById('addTorrentArrSearchResults').innerHTML = '';
    document.getElementById('addTorrentFeedback').innerHTML = '';
    document.getElementById('addTorrentSelectedMediaDisplay').textContent = 'Aucun';
    document.getElementById('addTorrentTargetId').value = '';
    document.getElementById('addTorrentOriginalName').value = '';
    currentAddTorrentAppType = null;
    document.getElementById('addTorrentSonarrNewSeriesOptions').style.display = 'none';
    document.getElementById('addTorrentRadarrNewMovieOptions').style.display = 'none';
    ['sonarrRootFolderSelectForAdd', 'sonarrQualityProfileSelectForAdd', 'radarrRootFolderSelectForAdd', 'radarrQualityProfileSelectForAdd'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.innerHTML = '<option value="" selected disabled>Chargement...</option>'; el.disabled = true; }
    });
    const radarrAvailS = document.getElementById('radarrMinimumAvailabilitySelectForAdd');
    if (radarrAvailS) { radarrAvailS.value = 'announced'; radarrAvailS.disabled = true; }
    document.querySelectorAll('input[name="addTorrentAppType"]').forEach(radio => {
        radio.removeEventListener('change', handleAddTorrentAppTypeChange);
        radio.addEventListener('change', handleAddTorrentAppTypeChange);
    });
    document.getElementById('addTorrentExecuteArrSearchBtn').addEventListener('click', executeArrSearchForAddTorrentModal);
    document.getElementById('torrentFileUpload').addEventListener('change', handleTorrentFileChangeForAddTorrent);
    document.getElementById('torrentMagnetLink').addEventListener('input', handleMagnetLinkInputForAddTorrent);
    document.getElementById('submitAddTorrentBtn').addEventListener('click', handleSubmitAddTorrent);
    document.getElementById('submitAddTorrentBtn').disabled = true;
    modalElement.removeAttribute('data-selected-is-new');
    modalElement.removeAttribute('data-selected-media-id');
    modalElement.removeAttribute('data-selected-media-title');
    modalElement.removeAttribute('data-selected-media-type');
}

function handleAddTorrentAppTypeChange() {
    currentAddTorrentAppType = this.value;
    document.getElementById('addTorrentArrSearchSection').style.display = 'block';
    document.getElementById('addTorrentArrSearchResults').innerHTML = '';
    const searchQueryEl = document.getElementById('addTorrentArrSearchQuery');
    searchQueryEl.value = '';
    searchQueryEl.placeholder = (currentAddTorrentAppType === 'sonarr') ? 'Nom de la série...' : 'Titre du film...';
    document.getElementById('addTorrentSelectedMediaDisplay').textContent = 'Aucun';
    document.getElementById('addTorrentTargetId').value = '';
    document.getElementById('addTorrentSonarrNewSeriesOptions').style.display = 'none';
    document.getElementById('addTorrentRadarrNewMovieOptions').style.display = 'none';
    const torrentFile = document.getElementById('torrentFileUpload').files[0];
    if (torrentFile) { searchQueryEl.value = getCleanedSearchTerm(torrentFile.name); }
    updateSubmitAddTorrentButtonState();
}

async function executeArrSearchForAddTorrentModal() {
    const query = document.getElementById('addTorrentArrSearchQuery').value;
    const resultsDiv = document.getElementById('addTorrentArrSearchResults');
    const feedbackDiv = document.getElementById('addTorrentFeedback'); // Use the main feedback div for this modal
    if(feedbackDiv) feedbackDiv.innerHTML = '';

    if (!resultsDiv) { console.error("Div 'addTorrentArrSearchResults' non trouvée."); return; }
    if (!currentAddTorrentAppType) { resultsDiv.innerHTML = '<p class="text-warning">Sélectionnez Sonarr ou Radarr.</p>'; return; }
    if (!query.trim()) { resultsDiv.innerHTML = '<p class="text-warning">Terme de recherche manquant.</p>'; return; }
    resultsDiv.innerHTML = `<div class="d-flex align-items-center"><strong>Recherche ${currentAddTorrentAppType}...</strong><div class="spinner-border ms-auto"></div></div>`;

    const searchUrl = (currentAddTorrentAppType === 'sonarr') ? window.appUrls.searchSonarrApi : window.appUrls.searchRadarrApi;
    try {
        const response = await fetch(`${searchUrl}?query=${encodeURIComponent(query)}`);
        if (!response.ok) {
            let eD; try { eD = await response.json(); } catch (e) { eD = { error: `Erreur API ${currentAddTorrentAppType}` }; }
            throw new Error(eD.error || `HTTP ${response.status}`);
        }
        const results = await response.json();
        renderArrSearchResultsForAddTorrent(results, currentAddTorrentAppType, 'addTorrentArrSearchResults');
    } catch (error) {
        resultsDiv.innerHTML = ''; // Clear loading
        if(feedbackDiv) feedbackDiv.innerHTML = `<p class="alert alert-danger">Erreur: ${escapeJsString(error.message)}</p>`;
        else resultsDiv.innerHTML = `<p class="text-danger">Erreur: ${escapeJsString(error.message)}</p>`;
    }
}

function renderArrSearchResultsForAddTorrent(results, appType, resultsDivId) {
    const resultsDiv = document.getElementById(resultsDivId);
    if (!resultsDiv) { console.error(`Div résultats (ID: ${resultsDivId}) non trouvée.`); return; }
    if (!results || results.length === 0) { resultsDiv.innerHTML = `<p class="text-muted">Aucun ${appType === 'sonarr' ? 'série' : 'film'} trouvé.</p>`; return; }
    let html = '<ul class="list-group mt-3 list-group-flush">';
    results.forEach(item => {
        const title = escapeJsString(item.title);
        const year = item.year || 'N/A';
        let posterUrl = item.remotePoster || (item.images && item.images.length > 0 ? item.images.find(img => img.coverType === 'poster')?.remoteUrl : null) || 'data:image/svg+xml;charset=UTF-8,%3Csvg%20width%3D%2260%22%20height%3D%2290%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2060%2090%22%20preserveAspectRatio%3D%22none%22%3E%3Cdefs%3E%3Cstyle%20type%3D%22text%2Fcss%22%3E%23holder_1582426688c%20text%20%7B%20fill%3A%23AAAAAA%3Bfont-weight%3Abold%3Bfont-family%3AArial%2C%20Helvetica%2C%20Open%20Sans%2C%20sans-serif%2C%20monospace%3Bfont-size%3A10pt%20%7D%20%3C%2Fstyle%3E%3C%2Fdefs%3E%3Cg%20id%3D%22holder_1582426688c%22%3E%3Crect%20width%3D%2260%22%20height%3D%2290%22%20fill%3D%22%23EEEEEE%22%3E%3C%2Frect%3E%3Cg%3E%3Ctext%20x%3D%2213.171875%22%20y%3D%2249.5%22%3EN/A%3C%2Ftext%3E%3C%2Fg%3E%3C%2Fg%3E%3C%2Fsvg%3E';
        let isAlreadyAdded = false, idForSelection = null, idTypeForDisplay = "", externalIdForDisplay = "", internalIdDisplay = "";
        if (appType === 'sonarr') {
            const sonarrId = parseInt(item.id); isAlreadyAdded = !isNaN(sonarrId) && sonarrId > 0;
            idForSelection = isAlreadyAdded ? sonarrId : item.tvdbId; idTypeForDisplay = "TVDB ID"; externalIdForDisplay = item.tvdbId || 'N/A';
            if (isAlreadyAdded && sonarrId) internalIdDisplay = `| Sonarr ID: ${sonarrId}`;
        } else { /* radarr */
            const radarrId = parseInt(item.id); isAlreadyAdded = !isNaN(radarrId) && radarrId > 0;
            idForSelection = isAlreadyAdded ? radarrId : item.tmdbId; idTypeForDisplay = "TMDB ID"; externalIdForDisplay = item.tmdbId || 'N/A';
            if (isAlreadyAdded && radarrId) internalIdDisplay = `| Radarr ID: ${radarrId}`;
        }
        const buttonText = isAlreadyAdded ? "Sélectionner" : "Ajouter & Sélectionner";
        const buttonIcon = isAlreadyAdded ? "fas fa-check-circle" : "fas fa-plus-circle";
        const buttonClass = isAlreadyAdded ? "btn-success" : "btn-info";
        const buttonTitle = isAlreadyAdded ? `Sélectionner: ${item.title}` : `Ajouter: ${item.title}`;
        html += `
            <li class="list-group-item"><div class="row align-items-center">
                <div class="col-auto" style="width:50px;"><img src="${posterUrl}" alt="Poster" class="img-fluid rounded" style="max-height: 60px;" onerror="this.src='https://via.placeholder.com/40x60?text=Err';"></div>
                <div class="col"><strong>${item.title}</strong> (${year})<br><small class="text-muted">Statut: <span class="fw-bold ${isAlreadyAdded ? 'text-success' : 'text-primary'}">${isAlreadyAdded ? (item.status || 'Géré(e)') : 'Non Ajouté(e)'}</span> | ${idTypeForDisplay}: ${externalIdForDisplay} ${internalIdDisplay}</small></div>
                <div class="col-auto"><button type="button" class="btn ${buttonClass} btn-sm" onclick="selectArrItemForAddTorrent(${idForSelection || 0}, '${title}', '${appType}', ${isAlreadyAdded})" title="${buttonTitle}" ${idForSelection ? '' : 'disabled title="ID manquant"'}><i class="${buttonIcon}"></i> ${buttonText}</button></div>
            </div></li>`;
    });
    html += '</ul>';
    resultsDiv.innerHTML = html;
}

function selectArrItemForAddTorrent(itemId, itemTitle, appType, isAddedBoolean) {
    document.getElementById('addTorrentTargetId').value = itemId;
    document.getElementById('addTorrentSelectedMediaDisplay').innerHTML = `${appType === 'sonarr' ? 'Série' : 'Film'}: <strong>${itemTitle}</strong> (ID: ${itemId})`;
    const addTorrentModalElement = document.getElementById('addTorrentModal');
    addTorrentModalElement.setAttribute('data-selected-is-new', !isAddedBoolean ? 'true' : 'false');
    addTorrentModalElement.setAttribute('data-selected-media-id', itemId);
    addTorrentModalElement.setAttribute('data-selected-media-title', itemTitle);
    addTorrentModalElement.setAttribute('data-selected-media-type', appType);
    const resultsDiv = document.getElementById('addTorrentArrSearchResults');
    const feedbackDiv = document.getElementById('addTorrentFeedback');
    if (resultsDiv) { // Clear search results
        resultsDiv.innerHTML = '';
    }
    if (feedbackDiv) { // Show selection in main feedback area for this modal
        feedbackDiv.innerHTML = `<p class="alert alert-info mt-2"><strong>${itemTitle}</strong> sélectionné.<br>
            ${isAddedBoolean ? 'Média déjà géré.' : 'Nouveau média à ajouter.'}<br>
            ${!isAddedBoolean ? 'Choisir options d\'ajout.' : ''} Prêt.</p>`;
    }
    const sonarrOptionsDiv = document.getElementById('addTorrentSonarrNewSeriesOptions');
    const radarrOptionsDiv = document.getElementById('addTorrentRadarrNewMovieOptions');
    if (sonarrOptionsDiv) sonarrOptionsDiv.style.display = 'none';
    if (radarrOptionsDiv) radarrOptionsDiv.style.display = 'none';

    if (!isAddedBoolean) {
        if (appType === 'sonarr' && sonarrOptionsDiv) {
            sonarrOptionsDiv.style.display = 'block';
            populateSelectFromServer(window.appUrls.getSonarrRootfolders, 'sonarrRootFolderSelectForAdd', 'path', 'path', 'Dossier Racine Sonarr');
            populateSelectFromServer(window.appUrls.getSonarrQualityprofiles, 'sonarrQualityProfileSelectForAdd', 'id', 'name', 'Profil Qualité Sonarr');
        } else if (appType === 'radarr' && radarrOptionsDiv) {
            radarrOptionsDiv.style.display = 'block';
            populateSelectFromServer(window.appUrls.getRadarrRootfolders, 'radarrRootFolderSelectForAdd', 'path', 'path', 'Dossier Racine Radarr');
            populateSelectFromServer(window.appUrls.getRadarrQualityprofiles, 'radarrQualityProfileSelectForAdd', 'id', 'name', 'Profil Qualité Radarr');
            const radarrAvailS = document.getElementById('radarrMinimumAvailabilitySelectForAdd');
            if (radarrAvailS) {
                radarrAvailS.disabled = false;
                radarrAvailS.removeEventListener('change', updateSubmitAddTorrentButtonState);
                radarrAvailS.addEventListener('change', updateSubmitAddTorrentButtonState);
            }
        }
    }
    updateSubmitAddTorrentButtonState();
}

async function populateSelectFromServer(apiUrl, selectElementId, valueField, textField, selectTypeForLog) {
    const selectElement = document.getElementById(selectElementId);
    if (!selectElement) { console.error(`Select (ID: ${selectElementId}) non trouvé.`); return; }
    selectElement.innerHTML = `<option value="">Chargement...</option>`;
    selectElement.disabled = true;
    const errorElement = document.getElementById(selectElementId.replace('SelectForAdd', 'ErrorForAdd'));
    if (errorElement) errorElement.textContent = '';

    try {
        const response = await fetch(apiUrl);
        if (!response.ok) {
            let eD; try { eD = await response.json(); } catch (e) { eD = { error: `Erreur HTTP ${response.status}` }; }
            throw new Error(eD.error);
        }
        const dataItems = await response.json();
        selectElement.innerHTML = `<option value="">-- Choisir ${selectTypeForLog} --</option>`;
        if (dataItems && dataItems.length > 0) {
            dataItems.forEach(item => selectElement.add(new Option(item[textField], item[valueField])));
            selectElement.disabled = false;
            selectElement.removeEventListener('change', updateSubmitAddTorrentButtonState);
            selectElement.addEventListener('change', updateSubmitAddTorrentButtonState);
        } else {
            selectElement.innerHTML = `<option value="">Aucun ${selectTypeForLog.toLowerCase()} trouvé</option>`;
            if (errorElement) errorElement.textContent = `Aucun ${selectTypeForLog.toLowerCase()} disponible.`;
        }
    } catch (error) {
        selectElement.innerHTML = `<option value="">Erreur chargement</option>`;
        if (errorElement) errorElement.textContent = `Erreur: ${escapeJsString(error.message)}`;
    } finally { updateSubmitAddTorrentButtonState(); }
}

function handleTorrentFileChangeForAddTorrent(event) {
    const originalNameInput = document.getElementById('addTorrentOriginalName');
    if (event.target.files.length > 0) {
        const fileName = event.target.files[0].name;
        originalNameInput.value = fileName;
        if (currentAddTorrentAppType) { document.getElementById('addTorrentArrSearchQuery').value = getCleanedSearchTerm(fileName); }
    } else { originalNameInput.value = ''; }
    updateSubmitAddTorrentButtonState();
}

function handleMagnetLinkInputForAddTorrent(event) {
    const magnetLink = event.target.value;
    const originalNameInput = document.getElementById('addTorrentOriginalName');
    const dnMatch = magnetLink.match(/&dn=([^&]+)/);
    if (dnMatch && dnMatch[1]) {
        const decodedName = decodeURIComponent(dnMatch[1]).replace(/\+/g, ' ');
        originalNameInput.value = decodedName;
        if (currentAddTorrentAppType) { document.getElementById('addTorrentArrSearchQuery').value = getCleanedSearchTerm(decodedName); }
    } else { originalNameInput.value = 'magnet_' + Date.now().toString().slice(-6); }
    updateSubmitAddTorrentButtonState();
}

function updateSubmitAddTorrentButtonState() {
    const submitButton = document.getElementById('submitAddTorrentBtn');
    if (!submitButton) return;
    const addTorrentModalElement = document.getElementById('addTorrentModal');
    if (!addTorrentModalElement) { submitButton.disabled = true; return; }

    const isNew = addTorrentModalElement.getAttribute('data-selected-is-new') === 'true';
    const mediaId = document.getElementById('addTorrentTargetId').value;
    const appType = currentAddTorrentAppType;
    let allRequiredOptionsSelected = false;

    if (mediaId) {
        if (isNew) {
            let rootFolderSelected = false;
            let qualityProfileSelected = false;
            let availabilityConditionMet = true; // Default to true (covers Sonarr or cases where dropdown might be missing)

            if (appType === 'sonarr') {
                rootFolderSelected = !!document.getElementById('sonarrRootFolderSelectForAdd')?.value;
                qualityProfileSelected = !!document.getElementById('sonarrQualityProfileSelectForAdd')?.value;
                // For Sonarr, availabilityConditionMet remains true as there is no specific dropdown for it in this context.
            } else if (appType === 'radarr') {
                rootFolderSelected = !!document.getElementById('radarrRootFolderSelectForAdd')?.value;
                qualityProfileSelected = !!document.getElementById('radarrQualityProfileSelectForAdd')?.value;
                availabilityConditionMet = !!document.getElementById('radarrMinimumAvailabilitySelectForAdd')?.value;
            }
            allRequiredOptionsSelected = rootFolderSelected && qualityProfileSelected && availabilityConditionMet;
        } else {
            allRequiredOptionsSelected = true; // For existing media, no extra options needed to enable submit
        }
    }
    const sourceProvided = !!(document.getElementById('torrentMagnetLink').value.trim() || document.getElementById('torrentFileUpload').files[0]);
    submitButton.disabled = !(allRequiredOptionsSelected && sourceProvided && appType);
}

async function handleSubmitAddTorrent() {
    const magnetLink = document.getElementById('torrentMagnetLink').value.trim();
    const torrentFile = document.getElementById('torrentFileUpload').files[0];
    const appType = currentAddTorrentAppType;
    const feedbackDiv = document.getElementById('addTorrentFeedback');
    feedbackDiv.innerHTML = '';

    if (!magnetLink && !torrentFile) { feedbackDiv.innerHTML = '<p class="text-danger">Fichier .torrent ou lien magnet requis.</p>'; return; }
    if (magnetLink && torrentFile) { feedbackDiv.innerHTML = '<p class="text-danger">Choisir fichier OU lien magnet.</p>'; return; }
    if (!appType) { feedbackDiv.innerHTML = '<p class="text-danger">Type de média requis.</p>'; return; }

    const addTorrentModalElement = document.getElementById('addTorrentModal');
    const isNewMedia = addTorrentModalElement.getAttribute('data-selected-is-new') === 'true';
    const mediaIdForPayload = addTorrentModalElement.getAttribute('data-selected-media-id');
    const mediaTitleForAdd = addTorrentModalElement.getAttribute('data-selected-media-title');
    let originalName = document.getElementById('addTorrentOriginalName').value.trim() || (torrentFile ? torrentFile.name : ('magnet_' + Date.now().toString().slice(-6)));

    if (!mediaIdForPayload) { feedbackDiv.innerHTML = '<p class="text-danger">Série/film cible requis.</p>'; return; }

    let torrentFileB64 = null;
    if (torrentFile) { try { torrentFileB64 = await readFileAsBase64(torrentFile); } catch (e) { feedbackDiv.innerHTML = '<p class="text-danger">Erreur lecture fichier.</p>'; return; } }

    const payload = {
        magnet_link: magnetLink || null, torrent_file_b64: torrentFileB64, app_type: appType,
        original_name: originalName, is_new_media: isNewMedia
    };
    if (isNewMedia) {
        payload.external_id = parseInt(mediaIdForPayload); payload.title_for_add = mediaTitleForAdd;
        if (appType === 'sonarr') {
            payload.root_folder_path = document.getElementById('sonarrRootFolderSelectForAdd').value;
            payload.quality_profile_id = parseInt(document.getElementById('sonarrQualityProfileSelectForAdd').value);
        } else { /* radarr */
            payload.root_folder_path = document.getElementById('radarrRootFolderSelectForAdd').value;
            payload.quality_profile_id = parseInt(document.getElementById('radarrQualityProfileSelectForAdd').value);
            payload.minimum_availability = document.getElementById('radarrMinimumAvailabilitySelectForAdd').value;
        }
        if (!payload.root_folder_path || !payload.quality_profile_id) { feedbackDiv.innerHTML = '<p class="text-danger">Options d\'ajout requises.</p>'; return; }
    } else { payload.target_id = parseInt(mediaIdForPayload); }

    const submitButton = document.getElementById('submitAddTorrentBtn');
    if (submitButton) submitButton.disabled = true;
    feedbackDiv.innerHTML = '<p class="text-info">Ajout et pré-association...</p>';

    try {
        const response = await fetch(window.appUrls.rtorrentAddTorrent, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (response.ok && result.success) {
            feedbackDiv.innerHTML = `<p class="alert alert-success">${escapeJsString(result.message)} (Hash: ${escapeJsString(result.torrent_hash || 'N/A')})</p>`;
            setTimeout(() => {
                const modalInstance = bootstrap.Modal.getInstance(addTorrentModalElement);
                if (modalInstance) modalInstance.hide();
                flashMessageGlobally(result.message || "Action terminée.", 'success');
            }, 3000);
        } else { throw new Error(result.error || `Erreur HTTP ${response.status}`); }
    } catch (error) {
        feedbackDiv.innerHTML = `<p class="alert alert-danger">Erreur: ${escapeJsString(error.message)}</p>`;
    } finally { if (submitButton) submitButton.disabled = false; }
}

function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = error => reject(error);
        reader.readAsDataURL(file);
    });
}

// --- Function for Local Staging: Add to *Arr then Map ---
async function promptAndAddArrItemForLocalStaging(searchResultData, arrAppType, originalSearchModalElement) {
    // searchResultData is expected to have at least: id (tvdbId/tmdbId), title
    // originalSearchModalElement is the Sonarr/Radarr search modal (sonarrSearchModal or radarrSearchModal)

    const isSonarr = arrAppType === 'sonarr';
    const actionVerb = isSonarr ? "Ajouter la Série" : "Ajouter le Film";
    const itemTitle = searchResultData.title;
    const externalId = searchResultData.id; // tvdbId for Sonarr, tmdbId for Radarr

    // 1. Identify and prepare the option containers (assuming they exist in _modals.html)
    //    We'll use the IDs from the 'addTorrentModal' for now as placeholders,
    //    hoping the actual _modals.html has similar structures within sonarrSearchModal/radarrSearchModal,
    //    or we will need to adjust these IDs later.
    //    The plan mentioned sftpSonarrNewSeriesOptionsContainer / sftpRadarrNewMovieOptionsContainer.
    //    Let's assume these are the correct IDs for now.

    const optionsContainerId = isSonarr ? 'sftpSonarrNewSeriesOptionsContainer' : 'sftpRadarrNewMovieOptionsContainer';
    const rootFolderSelectId = isSonarr ? 'sftpSonarrRootFolderSelect' : 'sftpRadarrRootFolderSelect';
    const qualityProfileSelectId = isSonarr ? 'sftpSonarrQualityProfileSelect' : 'sftpRadarrQualityProfileSelect';
    const monitoredCheckboxId = isSonarr ? 'sftpSonarrMonitoredCheckbox' : 'sftpRadarrMonitoredCheckbox'; // Assuming these exist
    const seasonFolderCheckboxId = isSonarr ? 'sftpSonarrSeasonFolderCheckbox' : null; // Sonarr specific
    const minimumAvailabilitySelectId = isSonarr ? null : 'sftpRadarrMinimumAvailabilitySelect'; // Radarr specific

    const optionsContainer = document.getElementById(optionsContainerId);
    const feedbackZone = document.getElementById(isSonarr ? 'sonarrSearchModalFeedbackZone' : 'radarrSearchModalFeedbackZone');

    if (!optionsContainer) {
        const msg = `Conteneur d'options (ID: ${optionsContainerId}) non trouvé dans la modale de recherche. Vérifiez _modals.html.`;
        console.error(msg);
        if (feedbackZone) feedbackZone.innerHTML = `<div class="alert alert-danger">${escapeJsString(msg)}</div>`;
        return;
    }

    // Hide search results, show options
    const searchResultsDivId = isSonarr ? 'sonarrSearchResults' : 'radarrSearchResults';
    const searchResultsDiv = document.getElementById(searchResultsDivId);
    if (searchResultsDiv) searchResultsDiv.style.display = 'none';
    optionsContainer.style.display = 'block';
    if (feedbackZone) feedbackZone.innerHTML = `<p class="alert alert-info">Configuration pour l'ajout de : <strong>${escapeJsString(itemTitle)}</strong></p>`;

    // 2. Populate select fields
    if (isSonarr) {
        populateSelectFromServer(window.appUrls.getSonarrRootfolders, rootFolderSelectId, 'path', 'path', 'Dossier Racine Sonarr');
        populateSelectFromServer(window.appUrls.getSonarrQualityprofiles, qualityProfileSelectId, 'id', 'name', 'Profil Qualité Sonarr');
        // Checkboxes: ensure they are visible and set to default (e.g., checked)
        const monitoredCb = document.getElementById(monitoredCheckboxId);
        if (monitoredCb) { monitoredCb.checked = true; monitoredCb.disabled = false; }
        const seasonFolderCb = document.getElementById(seasonFolderCheckboxId);
        if (seasonFolderCb) { seasonFolderCb.checked = true; seasonFolderCb.disabled = false; }

    } else { // Radarr
        populateSelectFromServer(window.appUrls.getRadarrRootfolders, rootFolderSelectId, 'path', 'path', 'Dossier Racine Radarr');
        populateSelectFromServer(window.appUrls.getRadarrQualityprofiles, qualityProfileSelectId, 'id', 'name', 'Profil Qualité Radarr');
        const minAvailabilitySelect = document.getElementById(minimumAvailabilitySelectId);
        if (minAvailabilitySelect) { /* Populate or ensure it's enabled if pre-filled in HTML */ minAvailabilitySelect.disabled = false; }
         // Checkboxes: ensure they are visible and set to default (e.g., checked)
        const monitoredCb = document.getElementById(monitoredCheckboxId);
        if (monitoredCb) { monitoredCb.checked = true; monitoredCb.disabled = false; }
    }

    // 3. Reconfigure the main modal button for this "Add and then Map" step.
    const modalMapButtonId = isSonarr ? 'sonarrModalMapButton' : 'radarrModalMapButton';
    const modalMapButton = document.getElementById(modalMapButtonId);

    if (modalMapButton) {
        modalMapButton.innerHTML = `<i class="fas fa-plus"></i> ${actionVerb} & Procéder au Map`;
        modalMapButton.className = 'btn btn-success'; // Or another distinct class
        modalMapButton.disabled = false; // Should be enabled once options are populated / validated

        modalMapButton.onclick = async function() {
            modalMapButton.disabled = true;
            if(feedbackZone) feedbackZone.innerHTML = `<div class="alert alert-info">Tentative d'ajout à ${arrAppType}...</div>`;

            const rootFolderPath = document.getElementById(rootFolderSelectId).value;
            const qualityProfileId = document.getElementById(qualityProfileSelectId).value;
            const monitored = document.getElementById(monitoredCheckboxId) ? document.getElementById(monitoredCheckboxId).checked : true; // Default to true if not found

            let seasonFolder = true; // Sonarr specific, default true
            if (isSonarr && document.getElementById(seasonFolderCheckboxId)) {
                seasonFolder = document.getElementById(seasonFolderCheckboxId).checked;
            }

            let minimumAvailability = 'announced'; // Radarr specific, default
            if (!isSonarr && document.getElementById(minimumAvailabilitySelectId)) {
                minimumAvailability = document.getElementById(minimumAvailabilitySelectId).value;
            }


            if (!rootFolderPath || !qualityProfileId) {
                const msg = "Veuillez sélectionner un dossier racine et un profil de qualité.";
                if(feedbackZone) feedbackZone.innerHTML = `<div class="alert alert-warning">${escapeJsString(msg)}</div>`;
                alert(msg);
                modalMapButton.disabled = false;
                return;
            }

            const payload = {
                external_id: externalId, // tvdbId or tmdbId
                title: itemTitle,
                year: searchResultData.year || 0, // Pass year if available, else 0. Backend might need to handle this.
                root_folder_path: rootFolderPath,
                quality_profile_id: parseInt(qualityProfileId),
                monitored: monitored,
                app_type: arrAppType
            };

            if (isSonarr) {
                payload.use_season_folder = seasonFolder;
                // Any other Sonarr specific params for add_new_series_to_sonarr
            } else { // Radarr
                payload.minimum_availability = minimumAvailability;
                // Any other Radarr specific params for add_new_movie_to_radarr
            }

            try {
                // This is the new backend route we'll create in Phase B
                const apiUrl = `${window.appUrls.seedboxBase}/api/add-arr-item-and-get-id`; // Utiliser une base URL si possible, ou hardcoder.
                // Si window.appUrls.seedboxBase n'est pas défini, il faudra le hardcoder ou le rendre disponible.
                // Pour l'instant, je vais utiliser une URL relative qui suppose que seedbox_ui_modals.js est servi depuis une page sous /seedbox/
                // ou que window.appUrls.seedboxBase est défini comme '/seedbox' ou ''.
                // Alternative plus sûre pour l'instant si window.appUrls.seedboxBase n'est pas garanti :
                const response = await fetch('/seedbox/api/add-arr-item-and-get-id', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    if(feedbackZone) feedbackZone.innerHTML = `<div class="alert alert-success">${arrAppType === 'sonarr' ? 'Série' : 'Film'} '${escapeJsString(result.new_media_title)}' ajouté avec ID: ${result.new_media_id}. Préparation du mappage...</div>`;

                    // Hide the options container again
                    if (optionsContainer) optionsContainer.style.display = 'none';
                    if (searchResultsDiv) searchResultsDiv.style.display = 'block'; // Or clear it


                    // NOW, proceed to trigger the manual import using the NEWLY created media ID
                    const newMediaId = result.new_media_id;
                    const newMediaTitle = result.new_media_title; // Title as returned by *Arr
                    const originalItemPath = document.getElementById(isSonarr ? 'sonarrOriginalItemName' : 'radarrOriginalItemName').value;

                    if (isSonarr) {
                        // Potentially show season input again if it was hidden by options
                        const manualSeasonDiv = document.getElementById('sonarrManualSeasonDiv');
                        if (manualSeasonDiv) manualSeasonDiv.style.display = 'block';
                        const userForcedSeason = document.getElementById('sonarrManualSeasonInput').value;

                        // Update modal attributes to reflect the newly added (now existing) media
                        originalSearchModalElement.setAttribute('data-selected-media-id', newMediaId);
                        originalSearchModalElement.setAttribute('data-is-new-media', 'false'); // It's no longer new

                        triggerSonarrManualImportWithSeason(newMediaId, newMediaTitle, userForcedSeason);
                    } else { // Radarr
                         // Update modal attributes
                        originalSearchModalElement.setAttribute('data-selected-media-id', newMediaId);
                        originalSearchModalElement.setAttribute('data-is-new-media', 'false');

                        triggerRadarrManualImport(newMediaId, newMediaTitle);
                    }
                    // The trigger functions will handle hiding the modal and reloading on success.
                    // No need to hide originalSearchModalElement here directly unless trigger functions fail early.

                } else {
                    throw new Error(result.error || `Erreur lors de l'ajout à ${arrAppType}.`);
                }
            } catch (error) {
                console.error(`Erreur dans promptAndAddArrItemForLocalStaging pour ${arrAppType}:`, error);
                if(feedbackZone) feedbackZone.innerHTML = `<div class="alert alert-danger">Erreur: ${escapeJsString(error.message)}</div>`;
                modalMapButton.disabled = false; // Re-enable button on error
            }
        };
    } else {
        const msg = `Bouton principal de la modale (ID: ${modalMapButtonId}) non trouvé.`;
        console.error(msg);
        if(feedbackZone) feedbackZone.innerHTML = `<div class="alert alert-danger">${escapeJsString(msg)}</div>`;
    }
}


// ========================================================================== //
// --- *Arr Queue Management Functions ---
// ========================================================================== //

function updateDeleteButtonState(arrType) {
    // This function is now global and relies on the specific structure of queue_manager.html
    const container = document.querySelector('#arr-queue-container');
    if (!container) return; // If the queue manager isn't loaded, do nothing.

    const checkboxes = container.querySelectorAll(`.${arrType}-item-checkbox:checked`);
    const deleteButton = container.querySelector(`button[name="delete_${arrType}_selection"]`);

    if (deleteButton) {
        deleteButton.disabled = checkboxes.length === 0;
    }
}

function toggleSelectAll(arrType, selectAllButton) {
    const container = document.querySelector('#arr-queue-container');
    if (!container) return;

    const checkboxes = container.querySelectorAll(`.${arrType}-item-checkbox`);
    let allSelectedCurrently = checkboxes.length > 0; // Start by assuming true if there are any checkboxes

    checkboxes.forEach(checkbox => {
        if (!checkbox.checked) {
            allSelectedCurrently = false;
        }
    });

    const newCheckedState = !allSelectedCurrently;
    checkboxes.forEach(checkbox => {
        checkbox.checked = newCheckedState;
    });

    updateDeleteButtonState(arrType);

    if(selectAllButton) {
        selectAllButton.textContent = newCheckedState ? 'Tout désélectionner' : 'Tout sélectionner';
    }
}


console.log("seedbox_ui_modals.js loaded successfully and completely.");

// Ajoute ce bloc de code pour gérer la fermeture propre des modales
document.addEventListener('DOMContentLoaded', function() {
    // Cible les deux modales de mapping
    const sonarrModal = document.getElementById('sonarrSearchModal');
    const radarrModal = document.getElementById('radarrSearchModal');

    const handleModalClose = function() {
        // Cherche s'il reste un overlay de modale dans le body
        const backdrops = document.querySelectorAll('.modal-backdrop');
        if (backdrops.length > 0) {
            console.warn('Overlay de modale fantôme détecté. Tentative de suppression manuelle.');
            backdrops.forEach(backdrop => backdrop.remove());
        }

        // Bootstrap ajoute aussi une classe au body qui peut bloquer le scroll
        if (document.body.classList.contains('modal-open')) {
            console.warn('Classe "modal-open" résiduelle détectée. Suppression.');
            document.body.classList.remove('modal-open');
        }
    };

    if (sonarrModal) {
        sonarrModal.addEventListener('hidden.bs.modal', handleModalClose);
    }
    if (radarrModal) {
        radarrModal.addEventListener('hidden.bs.modal', handleModalClose);
    }
});
// [end of app/static/js/seedbox_ui_modals.js]