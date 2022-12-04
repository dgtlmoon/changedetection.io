/**
 * @file
 * Toggles theme between light and dark mode.
 */
$(document).ready(function () {
  const url = "/toggle-theme";

  const button = document.getElementsByClassName("toggle-theme")[0];

  button.onclick = () => {
    fetch(url)
      .then(function () {
        const htmlElement = document.getElementsByTagName("html");
        const isDarkMode = htmlElement[0].dataset.darkmode === "true";
        htmlElement[0].dataset.darkmode = !isDarkMode;
        if (isDarkMode) {
          button.classList.remove("dark");
        } else {
          button.classList.add("dark");
        }
      })
      .catch(function (e) {
        console.log("Can't toggle the theme. Error was: ", e);
      });
  };
});
