// Click to copy: hovering shows "copy" and a copy icon, clicking copies the element's text and shows "copied". Any
// element with class "click-to-copy"; the labels come from data-copy-label / data-copied-label so they're translated.
// The hint is positioned over its box (top right of a code block, just right of an inline value), never in the page
// flow, so showing it doesn't move anything.
$(document).ready(function () {
    function icon(name) {
        return (window.feather && feather.icons[name]) ? feather.icons[name].toSvg({width: 13, height: 13}) : '';
    }

    $('.click-to-copy').each(function () {
        var $el = $(this);
        var $block = $el.closest('.mcp-snippet');
        var $box = $block.length ? $block : $el.wrap('<span class="click-to-copy-inline"></span>').parent();
        var $hint = $('<span class="click-to-copy-hint" aria-hidden="true"></span>').appendTo($box);

        function label(copied) {
            var text = copied ? ($el.data('copied-label') || 'copied') : ($el.data('copy-label') || 'copy');
            $hint.toggleClass('copied', copied).html($('<span>').text(text).html() + ' ' + icon(copied ? 'check' : 'copy'));
        }
        label(false);
        // Back to "copy" once it has faded out (it lingers 2s, see styles.scss)
        var reset;
        $box.on('mouseleave', function () { reset = setTimeout(function () { label(false); }, 2300); })
            .on('mouseenter', function () { clearTimeout(reset); });

        $box.on('click', function () {
            var text = $el.text();
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(text).then(function () { label(true); });
            } else {
                // Plain http on a LAN address: no clipboard API, select and copy instead
                var range = document.createRange();
                range.selectNode($el[0]);
                window.getSelection().removeAllRanges();
                window.getSelection().addRange(range);
                document.execCommand('copy');
                window.getSelection().removeAllRanges();
                label(true);
            }
        });
    });
});
