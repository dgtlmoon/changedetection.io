$(document).ready(function () {
    // Function to set up button event handlers
    function setupButtonHandlers() {
        // Unbind existing handlers first to prevent duplicates
        $(".addRuleRow, .removeRuleRow, .verifyRuleRow").off("click");
        
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
        
        // Verify rule button handler
        $(".verifyRuleRow").on("click", function(e) {
            e.preventDefault();
            
            let row = $(this).closest("tr");
            let field = row.find("select[name$='field']").val();
            let operator = row.find("select[name$='operator']").val();
            let value = row.find("input[name$='value']").val();
            
            // Validate that all fields are filled
            if (!field || field === "None" || !operator || operator === "None" || !value) {
                alert("Please fill in all fields (Field, Operator, and Value) before verifying.");
                return;
            }
            
            // Extract the watch UUID from the URL
            const url = window.location.pathname;
            const uuidMatch = url.match(/\/edit\/([^\/]+)/);
            if (!uuidMatch || !uuidMatch[1]) {
                alert("Could not determine the watch UUID. Please save your changes first.");
                return;
            }
            
            const watchUuid = uuidMatch[1];
            
            // Create a rule object
            const rule = {
                field: field,
                operator: operator,
                value: value
            };
            
            // Show a spinner or some indication that verification is in progress
            const $button = $(this);
            const originalHTML = $button.html();
            $button.html("⌛").prop("disabled", true);
            
            // Send the request to verify the rule
            $.ajax({
                url: `/conditions/${watchUuid}/verify-condition-single-rule`,
                type: "POST",
                contentType: "application/json",
                data: JSON.stringify(rule),
                success: function(response) {
                    if (response.status === "success") {
                        if (response.result) {
                            alert("✅ Condition PASSES verification against current snapshot!");
                        } else {
                            alert("❌ Condition FAILS verification against current snapshot.");
                        }
                    } else {
                        alert("Error: " + response.message);
                    }
                    $button.html(originalHTML).prop("disabled", false);
                },
                error: function(xhr) {
                    let errorMsg = "Error verifying condition.";
                    if (xhr.responseJSON && xhr.responseJSON.message) {
                        errorMsg = xhr.responseJSON.message;
                    }
                    alert(errorMsg);
                    $button.html(originalHTML).prop("disabled", false);
                }
            });
        });
    }

    // Function to reindex form elements and re-setup event handlers
    function reindexRules() {
        // Unbind all button handlers first
        $(".addRuleRow, .removeRuleRow, .verifyRuleRow").off("click");
        
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
