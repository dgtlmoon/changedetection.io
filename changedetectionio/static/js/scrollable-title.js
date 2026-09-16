// The watch title in the top menu is a horizontal scroll container (see
// parts/_top_menu.scss), so a long one can be dragged or swiped to read its end.
// The CSS ships a fixed right-hand fade for the no-JS case; once this is
// running, the fade has to follow the scroll instead, or the ending the reader
// just dragged over is the part that is dimmed.
//
// Global rather than part of diff-overview.js: the restock difference page and
// the image-SSIM preview page render the same line and neither loads that file.
$(function () {
    var $title = $('.current-diff-url');
    if (!$title.length) return;
    var el = $title[0];

    function updateFades() {
        // The 1px slack absorbs the sub-pixel gap a fractional layout leaves
        // between scrollWidth and clientWidth, which would otherwise hold
        // fade-right on for a line that is not actually cut off.
        $title
            .toggleClass('fade-left', el.scrollLeft > 1)
            .toggleClass('fade-right', el.scrollLeft + el.clientWidth < el.scrollWidth - 1);
    }

    // The class and the first state are set in the same task, so the no-JS mask
    // is never seen to blink off before its replacement arrives.
    $title.addClass('js-fades').on('scroll', updateFades);
    // Resizing changes what fits without scrolling the line, so the state can
    // become wrong without a scroll event: rotating a phone is the common case.
    $(window).on('resize', updateFades);
    updateFades();
});
