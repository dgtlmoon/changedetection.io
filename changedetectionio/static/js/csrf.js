// Attach the CSRF token to every state-changing jQuery request.
//
// Applied at script-execution time, NOT inside $(document).ready(). That matters: pages carry
// inline <script> blocks that register their own ready handlers while the document is still
// parsing, whereas this file is loaded with `defer` and therefore runs afterwards. jQuery
// invokes ready callbacks in registration order, so a ready handler registered by an inline
// block always runs BEFORE one registered here - and any POST it fires would go out with no
// token and come back "400 The CSRF token is missing".
//
// That is exactly what happened to the AI summary on /diff once its start call became a POST
// (#4467): diff.html's inline $(function(){...}) calls llmSummary.fetch() immediately.
//
// $.ajaxSetup needs no DOM, so doing it now closes the window entirely - deferred scripts all
// run before DOMContentLoaded, so the setup is in place before any ready handler can fire.
$.ajaxSetup({
    beforeSend: function (xhr, settings) {
        if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type) && !this.crossDomain) {
            xhr.setRequestHeader("X-CSRFToken", csrftoken)
        }
    }
});
