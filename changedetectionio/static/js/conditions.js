$(document).ready(function () {
    // Function to set up button event handlers
    function setupButtonHandlers() {
        // Unbind existing handlers first to prevent duplicates
        $(".addRuleRow, .removeRuleRow").off("click");
        
        // Add row button handler
        $(".addRuleRow").on("click", function(e) {
            e.preventDefault();
            
            let currentRow = $(this).closest("tr");
            
            // Clone without events
            let newRow = currentRow.clone(false);
            
            // Reset input values in the cloned row
            newRow.find("input").val("");
            newRow.find("select").prop("selectedIndex", 0);
            
            // Insert the new row after the current one
            currentRow.after(newRow);
            
            // Reindex all rows
            reindexRules();
        });
        
        // Remove row button handler
        $(".removeRuleRow").on("click", function(e) {
            e.preventDefault();
            
            // Only remove if there's more than one row
            if ($("#rulesTable tbody tr").length > 1) {
                $(this).closest("tr").remove();
                reindexRules();
            }
        });
    }

    // Function to reindex form elements and re-setup event handlers
    function reindexRules() {
        // Unbind all button handlers first
        $(".addRuleRow, .removeRuleRow").off("click");
        
        // Reindex all form elements
        $("#rulesTable tbody tr").each(function(index) {
            $(this).find("select, input").each(function() {
                let oldName = $(this).attr("name");
                let oldId = $(this).attr("id");

                if (oldName) {
                    let newName = oldName.replace(/\d+/, index);
                    $(this).attr("name", newName);
                }

                if (oldId) {
                    let newId = oldId.replace(/\d+/, index);
                    $(this).attr("id", newId);
                }
            });
        });
        
        // Reattach event handlers after reindexing
        setupButtonHandlers();
    }

    // Initial setup of button handlers
    setupButtonHandlers();
});
