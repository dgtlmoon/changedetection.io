/**
 * @file
 * Toggles theme between light and dark mode.
 */
$(document).ready(function () {
    const button = document.getElementById("toggle-light-mode");

    button.onclick = () => {
        const htmlElement = document.getElementsByTagName("html");
        const isDarkMode = htmlElement[0].dataset.darkmode === "true";
        htmlElement[0].dataset.darkmode = !isDarkMode;
        setCookieValue(!isDarkMode);
    };

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
