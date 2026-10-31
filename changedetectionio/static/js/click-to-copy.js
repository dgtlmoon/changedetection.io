// Click to copy, the way the API key on /settings works: hovering shows "copy", clicking copies the
// element's text and shows "copied". Any element with class "click-to-copy"; the labels come from
// data-copy-label / data-copied-label so they're translated.
$(document).ready(function () {
    $('.click-to-copy').each(function () {
        var $el = $(this);
        var $hint = $('<span class="click-to-copy-hint"></span>').hide().insertAfter($el.closest('.mcp-snippet').length ? $el.closest('.mcp-snippet') : $el);

        $el.hover(
            function () { $hint.text($el.data('copy-label') || 'copy').fadeIn(); },
            function () { $hint.hide(); }
        ).click(function () {
            var text = $el.text();
            var done = function () { $hint.text($el.data('copied-label') || 'copied').show(); };
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(done);
            } else {
                // Plain http on a LAN address: no clipboard API, select and copy instead
                var range = document.createRange();
                range.selectNode($el[0]);
                window.getSelection().removeAllRanges();
                window.getSelection().addRange(range);
                document.execCommand('copy');
                window.getSelection().removeAllRanges();
                done();
            }
        });
    });
});
