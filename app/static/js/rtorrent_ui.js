$(document).ready(function() {
    // --- GESTION DE LA SÉLECTION ET DES ACTIONS DE MASSE POUR RTORRENT ---

    function updateBatchActionButtons() {
        const selectedCheckboxes = $('.torrent-checkbox:checked');
        const selectedRows = selectedCheckboxes.closest('tr');
        const selectedCount = selectedCheckboxes.length;

        const batchActionsContainer = $('#batch-actions-container');
        const selectedItemCountSpan = $('#selected-torrent-count');

        selectedItemCountSpan.text(selectedCount);
        batchActionsContainer.toggle(selectedCount > 0);

        if (selectedCount > 0) {
            // Règle: Le bouton apparaît si AU MOINS UN item est éligible.
            const statuses = selectedRows.map((i, row) => $(row).data('mms-status')).get();
            const associations = selectedRows.map((i, row) => $(row).data('association-exists')).get();

            // Toujours visible si quelque chose est sélectionné
            $('#batch-repatriate-btn').show();
            $('#batch-delete-btn').show();

            // Visible si au moins un torrent n'est pas déjà traité
            const canBeMarkedAsProcessed = statuses.some(s => !['completed_manual', 'processed_manual'].includes(s));
            $('#batch-mark-processed-btn').toggle(canBeMarkedAsProcessed);

            // Visible si au moins un a une erreur de rapatriement
            const canRetryRepatriation = statuses.some(s => s === 'error_rapatriation');
            $('#batch-retry-repatriation-btn').toggle(canRetryRepatriation);

            // Visible si au moins une association existe
            const canForget = associations.some(a => a === true);
            $('#batch-forget-btn').toggle(canForget);

            // "Ignorer" est toujours une option possible sur n'importe quel torrent
            $('#batch-ignore-btn').show();

            // Logique pour le bouton Mapper
            const canMap = statuses.some(s => s === 'unknown');
            const mapButton = $('#batch-map-btn');
            mapButton.toggle(canMap);
            if (canMap) {
                if (selectedCount === 1) {
                    mapButton.prop('disabled', false).attr('title', 'Associer ce torrent à un média');
                } else {
                    mapButton.prop('disabled', true).attr('title', 'Le mapping ne peut se faire que sur un seul item à la fois.');
                }
            }
        }
    }

    // A. Logique de sélection et affichage du conteneur d'actions
    $(document).on('change', '#select-all-torrents, .torrent-checkbox', function() {
        const isSelectAll = $(this).is('#select-all-torrents');
        const itemCheckboxes = $('.torrent-checkbox');
        const selectAllCheckbox = $('#select-all-torrents');

        if (isSelectAll) {
            itemCheckboxes.prop('checked', $(this).prop('checked'));
        } else {
            selectAllCheckbox.prop('checked', !itemCheckboxes.not(':checked').length);
        }
        updateBatchActionButtons();
    });

    // B. Logique générique pour les actions de masse
    function handleBatchAction(action, eligibleSelector, confirmMessage, options = {}) {
        const eligibleItems = $('.torrent-checkbox:checked').closest('tr').filter(eligibleSelector);
        const selectedHashes = eligibleItems.find('.torrent-checkbox').map((i, el) => $(el).data('torrent-hash')).get();

        if (selectedHashes.length === 0) {
            alert(`Aucun item éligible pour l'action "${action}".`);
            return;
        }

        const finalConfirmMessage = `${confirmMessage}\n\nCette action affectera ${selectedHashes.length} torrent(s).`;

        if (confirm(finalConfirmMessage)) {
            fetch('/seedbox/rtorrent/batch-action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action, hashes: selectedHashes, options })
            })
            .then(response => response.json())
            .then(data => {
                alert(data.message || 'Action terminée.');
                if (data.status === 'success') {
                    if (typeof loadRtorrentView === 'function') {
                        // This flag seems to be used to control the reload.
                        isRtorrentContentLoaded = false;
                        loadRtorrentView();
                    } else {
                        location.reload();
                    }
                }
            })
            .catch(error => {
                console.error(`Error during batch ${action}:`, error);
                alert(`Une erreur est survenue lors de l'action "${action}".`);
            });
        }
    }

    // C. Écouteurs d'événements pour chaque bouton
    $(document).on('click', '#batch-delete-btn', function() {
        const deleteData = $('#delete-data-checkbox').is(':checked');
        const confirmMessage = `Êtes-vous sûr de vouloir supprimer la sélection ?` +
                               (deleteData ? "\nATTENTION : Les données seront également supprimées du disque." : "");
        handleBatchAction('delete', '*', confirmMessage, { delete_data: deleteData });
    });

    $(document).on('click', '#batch-repatriate-btn', function() {
        handleBatchAction('repatriate', '*', "Rapatrier les torrents sélectionnés vers le staging local ?");
    });

    $(document).on('click', '#batch-mark-processed-btn', function() {
        handleBatchAction('mark_processed', 'tr:not([data-mms-status="completed_manual"],[data-mms-status="processed_manual"])', "Marquer les torrents éligibles comme 'traités' ?");
    });

    $(document).on('click', '#batch-retry-repatriation-btn', function() {
        handleBatchAction('retry_repatriation', 'tr[data-mms-status="error_rapatriation"]', "Réessayer le rapatriement pour les torrents en erreur ?");
    });

    $(document).on('click', '#batch-forget-btn', function() {
        handleBatchAction('forget', 'tr[data-association-exists="true"]', "Oublier l'association pour les torrents sélectionnés ?");
    });

    $(document).on('click', '#batch-ignore-btn', function() {
        handleBatchAction('ignore', '*', "Ignorer définitivement les torrents sélectionnés ? Ils n'apparaîtront plus dans les suivis.");
    });

    $(document).on('click', '#batch-map-btn', function() {
        if ($(this).is(':disabled')) {
            return;
        }
        const selectedCheckbox = $('.torrent-checkbox:checked').first();
        const torrentName = selectedCheckbox.closest('tr').find('.torrent-name').text();

        // Mettre à jour la modale de choix
        $('#torrentNameToMap').text(torrentName);
        $('#torrentNameToMapInput').val(torrentName);

        // Ouvrir la modale de choix
        const mappingChoiceModal = new bootstrap.Modal(document.getElementById('mappingChoiceModal'));
        mappingChoiceModal.show();
    });

    // =================================================================
    // ### PARTIE 2 : TRI DYNAMIQUE DES TABLEAUX ###
    // =================================================================

    function parseSize(sizeStr) {
        if (!sizeStr || typeof sizeStr !== 'string' || sizeStr.toLowerCase() === 'n/a') return 0;

        // Gère les formats comme "1,234.56 Go" ou "1.23 Mo"
        const cleanedStr = sizeStr.replace(/,/g, '.').replace(/\s+/g, '');
        const sizeMatch = cleanedStr.match(/([\d.]+)([a-zA-Z]+)/);

        if (!sizeMatch) {
            // Tente de parser une chaîne qui ne contient que des chiffres (supposée être en octets)
            const numericValue = parseFloat(cleanedStr);
            return isNaN(numericValue) ? 0 : numericValue;
        }

        const value = parseFloat(sizeMatch[1]);
        const unit = sizeMatch[2].toUpperCase();

        switch (unit) {
            case 'TB': case 'TO': return value * 1e12;
            case 'GB': case 'GO': return value * 1e9;
            case 'MB': case 'MO': return value * 1e6;
            case 'KB': case 'KO': return value * 1e3;
            default: return value; // Octets ou unité inconnue
        }
    }

    function sortTable(table, sortBy, sortType, direction) {
        const tbody = table.find('tbody');
        const rows = tbody.find('tr').toArray();
        const cellIndex = table.find(`th.sortable-header[data-sort-by='${sortBy}']`).index();

        if (cellIndex === -1) {
            console.error(`Sort key "${sortBy}" not found in table headers.`);
            return;
        }

        rows.sort(function(a, b) {
            const cellA = $(a).children('td').eq(cellIndex);
            const cellB = $(b).children('td').eq(cellIndex);

            // Prioritize data-sort-value attribute, fallback to cell text
            let valA = cellA.data('sort-value') !== undefined ? String(cellA.data('sort-value')) : cellA.text().trim();
            let valB = cellB.data('sort-value') !== undefined ? String(cellB.data('sort-value')) : cellB.text().trim();

            if (sortType === 'date') {
                // Convert ISO date strings to timestamps for comparison
                valA = new Date(valA).getTime() || 0;
                valB = new Date(valB).getTime() || 0;
            } else if (sortType === 'size') {
                valA = parseSize(valA);
                valB = parseSize(valB);
            } else if (sortType === 'number') {
                valA = parseFloat(valA.replace('%', '').replace(',', '.')) || 0;
                valB = parseFloat(valB.replace('%', '').replace(',', '.')) || 0;
            } else { // 'text' or default
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
    // Utilise un sélecteur plus large pour fonctionner sur les deux pages
    $(document).on('click', '.sortable-header', function() {
        const header = $(this);
        const table = header.closest('table'); // Trouve la table parente
        const sortBy = header.data('sort-by');
        const sortType = header.data('sort-type') || 'text';

        // Détermine la nouvelle direction du tri
        let currentDir = header.data('sort-direction') || 'desc';
        let newDir = currentDir === 'asc' ? 'desc' : 'asc';

        // Stocke la nouvelle direction
        header.data('sort-direction', newDir);

        // Réinitialise les icônes sur tous les en-têtes de la table actuelle
        table.find('.sortable-header').removeClass('sort-asc sort-desc');

        // Applique la classe à l'en-tête cliqué
        header.addClass(newDir === 'asc' ? 'sort-asc' : 'sort-desc');

        // Appelle la fonction de tri
        sortTable(table, sortBy, sortType, newDir === 'asc' ? 1 : -1);
    });
});
