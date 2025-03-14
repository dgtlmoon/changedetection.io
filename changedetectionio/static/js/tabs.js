// Rewrite this is a plugin.. is all this JS really 'worth it?'

window.addEventListener('hashchange', function () {
    var tabs = document.getElementsByClassName('active');
    while (tabs[0]) {
        tabs[0].classList.remove('active');
        document.body.classList.remove('full-width');
    }
    set_active_tab();
}, false);

var has_errors = document.querySelectorAll(".messages .error");
if (!has_errors.length) {
    if (document.location.hash == "") {
        location.replace(document.querySelector(".tabs ul li:first-child a").hash);
    } else {
        set_active_tab();
    }
} else {
    focus_error_tab();
}

function set_active_tab() {
    document.body.classList.remove('full-width');
    var tab = document.querySelectorAll("a[href='" + location.hash + "']");
    if (tab.length) {
        tab[0].parentElement.className = "active";
    }
}

function focus_error_tab() {
    // time to use jquery or vuejs really,
    // activate the tab with the error
    var tabs = document.querySelectorAll('.tabs li a'), i;
    for (i = 0; i < tabs.length; ++i) {
        var tab_name = tabs[i].hash.replace('#', '');
        var pane_errors = document.querySelectorAll('#' + tab_name + ' .error')
        if (pane_errors.length) {
            document.location.hash = '#' + tab_name;
            return true;
        }
    }
    return false;
}



