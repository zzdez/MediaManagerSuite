$(document).ready(function() {
    $(document).on('click', '#standalone-trailer-search-btn', function(e) {
        e.preventDefault();

        const selectionModal = $('#trailer-selection-modal');

        // Clear any previous context from other searches
        selectionModal.removeData('ratingKey');
        selectionModal.removeData('title');
        selectionModal.removeData('year');
        selectionModal.removeData('mediaType');

        // Clear previous results and input
        selectionModal.find('#trailer-results-container').empty();
        selectionModal.find('#trailer-custom-search-input').val('');

        // Show the modal
        bootstrap.Modal.getOrCreateInstance(selectionModal[0]).show();
    });
});
