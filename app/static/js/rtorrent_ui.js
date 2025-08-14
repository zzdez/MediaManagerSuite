$(document).ready(function() {
    // --- GESTION DE LA SÉLECTION ET DES ACTIONS DE MASSE POUR RTORRENT ---

    // A. Logique de sélection et affichage du conteneur d'actions
    $(document).on('change', '#select-all-torrents, .torrent-checkbox', function() {
        const isSelectAll = $(this).is('#select-all-torrents');
        const itemCheckboxes = $('.torrent-checkbox');
        const selectAllCheckbox = $('#select-all-torrents');

        if (isSelectAll) {
            itemCheckboxes.prop('checked', $(this).prop('checked'));
        } else {
            if (!$(this).prop('checked')) {
                selectAllCheckbox.prop('checked', false);
            }
            if ($('.torrent-checkbox:checked').length === itemCheckboxes.length) {
                selectAllCheckbox.prop('checked', true);
            }
        }

        const selectedCount = $('.torrent-checkbox:checked').length;
        const batchActionsContainer = $('#batch-actions-container');
        const selectedItemCountSpan = $('#selected-torrent-count');

        selectedItemCountSpan.text(selectedCount);
        batchActionsContainer.toggle(selectedCount > 0);
    });

    // B. Action de suppression en masse
    $(document).on('click', '#batch-delete-btn', function() {
        const selectedItems = $('.torrent-checkbox:checked');
        const selectedHashes = selectedItems.map(function() {
            return $(this).data('torrent-hash');
        }).get();

        if (selectedHashes.length === 0) {
            alert('Veuillez sélectionner au moins un torrent.');
            return;
        }

        const deleteData = $('#delete-data-checkbox').is(':checked');
        const confirmationMessage = `Êtes-vous sûr de vouloir supprimer ${selectedHashes.length} torrent(s) ?` +
                                  (deleteData ? "\n\nATTENTION : Les données seront également supprimées du disque." : "");

        if (confirm(confirmationMessage)) {
            fetch('/seedbox/rtorrent/batch-action', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    action: 'delete',
                    hashes: selectedHashes,
                    options: {
                        delete_data: deleteData
                    }
                })
            })
            .then(response => response.json())
            .then(data => {
                alert(data.message || 'Action terminée.');
                // Recharger la vue pour voir les changements
                if (typeof loadRtorrentView === 'function') {
                    loadRtorrentView();
                } else {
                    location.reload();
                }
            })
            .catch(error => {
                console.error('Error during batch delete:', error);
                alert('Une erreur est survenue lors de la suppression de masse.');
            });
        }
    });
});
