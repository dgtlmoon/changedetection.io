/**
 * @file
 * Toggles theme between light and dark mode.
 */
$(document).ready(function () {
  const button = document.getElementsByClassName("toggle-theme")[0];

  button.onclick = () => {
    const htmlElement = document.getElementsByTagName("html");
    const isDarkMode = htmlElement[0].dataset.darkmode === "true";
    htmlElement[0].dataset.darkmode = !isDarkMode;
    if (isDarkMode) {
      button.classList.remove("dark");
      setCookieValue(false);
    } else {
      button.classList.add("dark");
      setCookieValue(true);
    }
  };

  const setCookieValue = (value) => {
    document.cookie = `css_dark_mode=${value};max-age=31536000`
  }
});
