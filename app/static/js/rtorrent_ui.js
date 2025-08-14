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
                if (typeof loadRtorrentView === 'function') {
                    loadRtorrentView();
                } else {
                    location.reload();
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
});
