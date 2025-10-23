// app/config_ui/static/js/mapping_config.js

document.addEventListener('DOMContentLoaded', () => {
    const addMappingBtn = document.getElementById('add-mapping-btn');
    const saveMappingsBtn = document.getElementById('save-mappings-btn');
    const mappingsTableBody = document.getElementById('mappings-table-body');
    const template = document.getElementById('mapping-row-template');

    // Gérer l'ajout d'une nouvelle règle
    addMappingBtn.addEventListener('click', () => {
        const clone = template.content.cloneNode(true);
        mappingsTableBody.appendChild(clone);
    });

    // Gérer la suppression d'une règle (via délégation d'événement)
    mappingsTableBody.addEventListener('click', (event) => {
        if (event.target.closest('.delete-mapping-btn')) {
            event.target.closest('tr').remove();
        }
    });

    // Gérer la sauvegarde de la configuration
    saveMappingsBtn.addEventListener('click', () => {
        const spinner = saveMappingsBtn.querySelector('.spinner-border');
        const mappings = [];
        const rows = mappingsTableBody.querySelectorAll('tr');

        // Geler le bouton
        saveMappingsBtn.disabled = true;
        spinner.classList.remove('d-none');

        // Parcourir chaque ligne pour construire l'objet de configuration
        rows.forEach(row => {
            const librarySelect = row.querySelector('.mapping-library');
            const rootFolderSelect = row.querySelector('.mapping-root-folder');
            const mediaTypeInput = row.querySelector('.mapping-media-type');

            const libraryName = librarySelect.value;
            const rootFolder = rootFolderSelect.value;
            const mediaType = mediaTypeInput.value.trim().toUpperCase();

            // N'ajouter que les règles complètes et valides
            if (libraryName && rootFolder && mediaType) {
                mappings.push({
                    library_name: libraryName,
                    root_folder: rootFolder,
                    media_type: mediaType
                });
            }
        });

        // Envoyer les données à l'API
        fetch('/configuration/api/mappings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ mappings: mappings }),
        })
        .then(response => response.json().then(data => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
            if (ok) {
                alert('Configuration du mapping sauvegardée avec succès !');
                // Optionnel : recharger la page pour confirmer
                window.location.reload();
            } else {
                throw new Error(data.message || 'Une erreur est survenue lors de la sauvegarde.');
            }
        })
        .catch(error => {
            console.error('Erreur de sauvegarde:', error);
            alert(`Erreur: ${error.message}`);
        })
        .finally(() => {
            // Dégeler le bouton
            saveMappingsBtn.disabled = false;
            spinner.classList.add('d-none');
        });
    });
});
