/**
 * @file
 * Toggles theme between light and dark mode.
 */
$(document).ready(function () {

    $(".toggle-light-mode").on("click", function () {
        const isDark = $("html").attr("data-darkmode") === "true";
        $("html").attr("data-darkmode", !isDark);
        setCookieValue(!isDark);
    });

    // AI mode toggle — persisted in localStorage
    (function initAiMode() {
        const enabled = localStorage.getItem('ai-mode') === 'true';
        $("html").attr("data-ai-mode", enabled ? "true" : "false");
    })();

    $(".toggle-ai-mode").on("click", function () {
        const current = $("html").attr("data-ai-mode") === "true";
        const next = !current;
        $("html").attr("data-ai-mode", next ? "true" : "false");
        localStorage.setItem('ai-mode', next ? 'true' : 'false');
    });

    const setCookieValue = (value) => {
        document.cookie = `css_dark_mode=${value};max-age=31536000;path=/`
    }

    // Search input box behaviour
    const toggle_search = document.getElementById("toggle-search");
    const search_q = document.getElementById("search-q");
    if(search_q) {
      window.addEventListener('keydown', function (e) {
        if (e.altKey == true && e.keyCode == 83) {
          search_q.classList.toggle('expanded');
          search_q.focus();
        }
      });

      search_q.onkeydown = (e) => {
        var key = e.keyCode || e.which;
        if (key === 13) {
          document.searchForm.submit();
        }
      };
      toggle_search.onclick = () => {
        // Could be that they want to search something once text is in there
        if (search_q.value.length) {
          document.searchForm.submit();
        } else {
          // If not..
          search_q.classList.toggle('expanded');
          search_q.focus();
        }
      };
    }

    $('#heart-us').click(function () {
        $("#overlay").toggleClass('visible');
        heartpath.style.fill = document.getElementById("overlay").classList.contains("visible") ? '#ff0000' : 'var(--color-background)';
    });

    setInterval(function () {
        $('body').toggleClass('spinner-active', $.active > 0);
    }, 2000);

});
