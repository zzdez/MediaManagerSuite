// Fichier : app/static/js/plex_editor_ui.js (Version avec Améliorations Ergonomiques)

$(document).ready(function() {

    // ... (PARTIE 1 : GESTION DES FILTRES - INCHANGÉE) ...

    // =================================================================
    // ### PARTIE 2 : GESTION DES ACTIONS SUR LES MÉDIAS ###
    // =================================================================

    const seriesModalElement = document.getElementById('series-management-modal');
    let isMonitoringDirty = false; // Flag pour les changements non sauvegardés

    if (seriesModalElement) {
        const saveMonitoringBtn = $('#save-episodes-monitoring-btn');

        // --- A. Logique Déléguée pour le Setup des Modales ---
        $('#plex-items-container').on('click', function(event) {
            // ... (Logique pour .archive-movie-btn, .archive-show-btn, .reject-show-btn - INCHANGÉE) ...

            // --- SETUP MODALE GÉRER SÉRIE (remise à zéro du flag) ---
            const manageSeriesBtn = event.target.closest('.manage-series-btn');
            if (manageSeriesBtn) {
                isMonitoringDirty = false;
                saveMonitoringBtn.prop('disabled', true);
                // ... (le reste de la logique de chargement de la modale est inchangé)
            }
        });

        // --- B. Logique d'interaction DANS la modale de gestion ---

        // Quand on change le switch d'UNE SAISON (La "Cascade")
        $(seriesModalElement).on('change', '.season-monitor-toggle', function() {
            const toggle = $(this);
            const seasonRow = toggle.closest('.season-row');
            const isMonitored = toggle.is(':checked');

            // Fait l'appel API immédiat pour la saison
            // ... (votre code fonctionnel pour la saison reste ici) ...

            // **LA CASCADE** : Met à jour visuellement tous les épisodes de la saison
            const collapseId = seasonRow.find('[data-bs-toggle="collapse"]').data('bs-target');
            $(collapseId).find('.episode-monitor-toggle').prop('checked', isMonitored).trigger('change');
        });

        // Quand on change le switch d'UN ÉPISODE
        $(seriesModalElement).on('change', '.episode-monitor-toggle', function() {
            isMonitoringDirty = true;
            saveMonitoringBtn.prop('disabled', false);
        });

        //Quand on clique sur le bouton "Sauvegarder Monitoring Épisodes"
        $('#save-episodes-monitoring-btn').on('click', function() {
            // ... (votre code existant pour le fetch vers /api/episodes/update_monitoring est correct)
            // On ajoute simplement la gestion du flag et du bouton à la fin
            // Dans le .then() en cas de succès :
            isMonitoringDirty = false;
            saveMonitoringBtn.prop('disabled', true);
        });

        // Quand on clique sur "Supprimer la Sélection"
        $('#delete-selected-episodes-btn').on('click', function() {
            // ... (votre code fonctionnel pour la suppression reste ici) ...
        });

        // --- C. Le Rappel de Sauvegarde ---
        $(seriesModalElement).on('hide.bs.modal', function (event) {
            if (isMonitoringDirty) {
                if (!confirm("Vous avez des changements de monitoring non sauvegardés pour les épisodes. Êtes-vous sûr de vouloir quitter ?")) {
                    event.preventDefault(); // Annule la fermeture de la modale
                }
            }
        });
    }

    // ... (PARTIE 3 : GESTIONNAIRES DE CONFIRMATION DES AUTRES MODALES - INCHANGÉE) ...
});