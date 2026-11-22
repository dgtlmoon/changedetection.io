/**
 * "Replace existing MCP Note" on the MCP Note sub-tab of /settings/ai/mcp: copies the built-in note (the textarea's
 * placeholder) into the textarea, so it can be changed instead of written from scratch. Asks first when there is
 * already a note in it.
 */
document.addEventListener('click', function (event) {
    var button = event.target.closest('[data-mcp-note-copy]');
    if (!button) return;
    var textarea = document.getElementById(button.getAttribute('data-mcp-note-copy'));
    if (!textarea) return;
    if (textarea.value.trim() && textarea.value !== textarea.placeholder && !window.confirm(button.getAttribute('data-confirm'))) return;
    textarea.value = textarea.placeholder;
    textarea.focus();
});
