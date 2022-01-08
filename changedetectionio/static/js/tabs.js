// Rewrite this is a plugin.. is all this JS really 'worth it?'

// display correct label and messages for minutes or seconds 
document.addEventListener("DOMContentLoaded", function(event) {
	use_seconds_change();
});
window.addEventListener('hashchange', function() {
  var tabs = document.getElementsByClassName('active');
  while (tabs[0]) {
    tabs[0].classList.remove('active');
  }
  set_active_tab();
}, false);

var has_errors=document.querySelectorAll(".messages .error");
if (!has_errors.length) {
    if (document.location.hash == "" ) {
        document.location.hash = "#general";
        document.getElementById("default-tab").className = "active";
    } else {
        set_active_tab();
    }
} else {
  focus_error_tab();
}


function set_active_tab() {
  var tab=document.querySelectorAll("a[href='"+location.hash+"']");
  if (tab.length) {
    tab[0].parentElement.className="active";
  }
    // hash could move the page down
    window.scrollTo(0, 0);
}

function focus_error_tab() {
  // time to use jquery or vuejs really,
  // activate the tab with the error
    var tabs = document.querySelectorAll('.tabs li a'),i;
    for (i = 0; i < tabs.length; ++i) {
      var tab_name=tabs[i].hash.replace('#','');
      var pane_errors=document.querySelectorAll('#'+tab_name+' .error');
      if (pane_errors.length) {
        document.location.hash = '#'+tab_name;
        return true;
      }
    }
    return false;
}

function use_seconds_change() {
	// var isChecked = document.querySelectorAll('input[id="use_seconds"]:checked').length
	// var labelIntegerField = document.querySelector("label[for=minutes_between_check]");
	// var msgDefault = document.getElementById("minutes-message-default");
	// var msgNonDefault = document.getElementById("minutes-message-non-default");
    // var msgWarning = document.getElementById("seconds-warning");
	// if (isChecked) {
		// labelIntegerField.innerHTML = "Maximum time in seconds until recheck";
		// try {
			// msgDefault.style.display = "none";
		// } catch(error) {
			//continue, won't be present if not default interval
		// }
		// try {
			// msgNonDefault.style.display = "none";
		// } catch(error) {
			//continue, won't be present if not default interval
		// }
		// msgWarning.style.display = "";
	// }
    // else {
		// labelIntegerField.innerHTML = "Maximum time in minutes until recheck";
		// try {
			// msgDefault.style.display = "";
		// } catch(error) {
			//continue, won't be present if not default interval
		// }
		// try {
			// msgNonDefault.style.display = "";
		// } catch(error) {
			//continue, won't be present if not default interval
		// }
		// msgWarning.style.display = "none";
    // }
}