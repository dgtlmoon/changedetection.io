
if (document.location.hash == "" ) {
    document.location.hash = "#general";
    document.getElementById("default-tab").className = "active";
} else {
    set_active_tab();
}


function set_active_tab() {
  var tab=document.querySelectorAll("a[href='"+location.hash+"']");
  if (tab.length) {
    tab[0].parentElement.className="active";
  }
}


window.addEventListener('hashchange', function() {
  var tabs = document.getElementsByClassName('active');
  while (tabs[0]) {
    tabs[0].classList.remove('active')
  }
  set_active_tab();
}, false);

