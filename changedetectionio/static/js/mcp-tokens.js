/**
 * MCP access tokens on the "Access tokens" sub-tab of /settings/ai/mcp: the add / edit overlay and Revoke.
 *
 * Everything goes through jQuery POSTs, so csrf.js attaches the X-CSRFToken header, and every answer carries the
 * re-rendered token list (_mcp-tokens.html) and Overview's status (_mcp-overview-status.html), which are swapped in,
 * so both are always the server's own. A new
 * token comes back once, in the answer to "Add", and is shown in the overlay; the server only keeps its hash.
 */
$(document).ready(function () {
    var dialog = document.getElementById('mcp-token-dialog');
    var $list = $('#mcp-tokens');
    if (!dialog || !$list.length) return;

    var $form = $('#mcp-token-form');
    var $created = $(dialog).find('.mcp-token-created');
    var $errors = $form.find('.mcp-token-errors');
    var defaults = $form.serializeArray();

    // The list and Overview's status (tokens at a glance / "Get started"), both rendered by the server
    function refresh(data) {
        $list.html(data.html);
        $('#mcp-overview-status').html(data.overview_html);
        if (window.feather) feather.replace();
    }

    function failed() {
        alert($list.data('error'));
    }

    function open(title, url, name, permissions, tags) {
        $form[0].reset();
        $form.find('[name="tags"]').prop('checked', false);
        $.each(tags || [], function (_, tag) {
            $form.find('[name="tags"][value="' + tag + '"]').prop('checked', true);
        });
        $.each(defaults, function (_, field) {
            if (field.name.indexOf('perm_') === 0) $form.find('[name="' + field.name + '"][value="' + field.value + '"]').prop('checked', true);
        });
        $.each(permissions || {}, function (area, level) {
            $form.find('[name="perm_' + area + '"][value="' + level + '"]').prop('checked', true);
        });
        $form.find('[name="name"]').val(name || '');
        $form.attr('action', url).find('.modal-title').text(title);
        $errors.empty().prop('hidden', true);
        $form.prop('hidden', false);
        $created.prop('hidden', true);
        dialog.showModal();
        $form.find('[name="name"]').trigger('focus');
    }

    $(document).on('click', '[data-mcp-token-add]', function () {
        open($form.data('title-add'), $form.data('add-url'));
    });

    $list.on('click', '[data-mcp-token-edit]', function () {
        var $token = $(this).closest('.mcp-token');
        open($form.data('title-edit'), $token.data('update-url'), $token.data('name'), $token.data('permissions'), $token.data('tags'));
    });

    $list.on('click', '[data-mcp-token-revoke]', function () {
        var $token = $(this).closest('.mcp-token');
        ModalDialog.confirm({
            type: 'danger',
            title: $list.data('revoke-title'),
            message: '<p><strong>' + _modalEscapeHTML(String($token.data('name'))) + '</strong></p><p>' + _modalEscapeHTML($list.data('revoke-message')) + '</p>',
            confirmText: $list.data('revoke-button'),
            onConfirm: function () {
                $.post($token.data('revoke-url')).done(function (data) { refresh(data); }).fail(failed);
            }
        });
    });

    // Assistants signed in with OAuth (the OAuth sub-tab): only Revoke, they sign in again from the assistant
    var $grants = $('#mcp-oauth-grants');
    $grants.on('click', '[data-mcp-oauth-revoke]', function () {
        var $grant = $(this).closest('.mcp-token');
        ModalDialog.confirm({
            type: 'danger',
            title: $grants.data('revoke-title'),
            message: '<p><strong>' + _modalEscapeHTML(String($grant.data('name'))) + '</strong></p><p>' + _modalEscapeHTML($grants.data('revoke-message')) + '</p>',
            confirmText: $grants.data('revoke-button'),
            onConfirm: function () {
                $.post($grant.data('revoke-url')).done(function (data) {
                    $grants.html(data.html);
                }).fail(function () { alert($grants.data('error')); });
            }
        });
    });

    $form.on('submit', function (e) {
        e.preventDefault();
        var adding = $form.attr('action') === $form.data('add-url');
        $.post($form.attr('action'), $form.serialize())
            .done(function (data) {
                refresh(data);
                if (adding && data.token) {
                    // Shown this once, the server keeps only its hash
                    $('#mcp-new-token').text(data.token);
                    $('#mcp-new-token-env').text('export CDIO_MCP_TOKEN=' + data.token);
                    $form.prop('hidden', true);
                    $created.prop('hidden', false);
                } else {
                    dialog.close();
                }
            })
            .fail(function (xhr) {
                var errors = (xhr.responseJSON || {}).errors;
                if (!errors) return failed();
                $errors.empty();
                $.each(errors, function (_, messages) {
                    $.each(messages, function (_, message) { $('<li>').text(message).appendTo($errors); });
                });
                $errors.prop('hidden', false);
            });
    });

    $(dialog).on('click', '[data-mcp-dialog-close]', function () { dialog.close(); });
    // Closing forgets the shown token, so it isn't left in the page
    dialog.addEventListener('close', function () {
        $('#mcp-new-token, #mcp-new-token-env').text('');
    });
});
