$(document).ready(function () {
    // Function to set up button event handlers
    function setupButtonHandlers() {
        // Unbind existing handlers first to prevent duplicates
        $(".addRuleRow, .removeRuleRow, .verifyRuleRow").off("click");
        
        // Add row button handler
        $(".addRuleRow").on("click", function(e) {
            e.preventDefault();
            
            let currentRow = $(this).closest(".fieldlist-row");
            
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
            if ($("#rulesTable .fieldlist-row").length > 1) {
                $(this).closest(".fieldlist-row").remove();
                reindexRules();
            }
        });
        
        // Verify rule button handler
        $(".verifyRuleRow").on("click", function(e) {
            e.preventDefault();
            
            let row = $(this).closest(".fieldlist-row");
            let field = row.find("select[name$='field']").val();
            let operator = row.find("select[name$='operator']").val();
            let value = row.find("input[name$='value']").val();
            
            // Validate that all fields are filled
            if (!field || field === "None" || !operator || operator === "None" || !value) {
                alert("Please fill in all fields (Field, Operator, and Value) before verifying.");
                return;
            }

            
            // Create a rule object
            let rule = {
                field: field,
                operator: operator,
                value: value
            };
            
            // Show a spinner or some indication that verification is in progress
            const $button = $(this);
            const originalHTML = $button.html();
            $button.html("⌛").prop("disabled", true);
            
            // Collect form data - similar to request_textpreview_update() in watch-settings.js
            let formData = new FormData();
            $('#edit-text-filter textarea, #edit-text-filter input').each(function() {
                const $element = $(this);
                const name = $element.attr('name');
                if (name) {
                    if ($element.is(':checkbox')) {
                        formData.append(name, $element.is(':checked') ? $element.val() : false);
                    } else {
                        formData.append(name, $element.val());
                    }
                }
            });
            
            // Also collect select values
            $('#edit-text-filter select').each(function() {
                const $element = $(this);
                const name = $element.attr('name');
                if (name) {
                    formData.append(name, $element.val());
                }
            });


            // Send the request to verify the rule
            $.ajax({
                url: verify_condition_rule_url+"?"+ new URLSearchParams({ rule: JSON.stringify(rule) }).toString(),
                type: "POST",
                data: formData,
                processData: false, // Prevent jQuery from converting FormData to a string
                contentType: false, // Let the browser set the correct content type
                success: function (response) {
                    if (response.status === "success") {
                        if(rule['field'] !== "page_filtered_text") {
                            // A little debug helper for the user
                            $('#verify-state-text').text(`${rule['field']} was value "${response.data[rule['field']]}"`)
                        }
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
                error: function (xhr) {
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
        $("#rulesTable .fieldlist-row").each(function(index) {
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
