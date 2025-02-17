(function ($) {
    $.fn.hashTabs = function (options) {
        var settings = $.extend({
            tabContainer: ".tabs ul",
            tabSelector: "li a",
            tabContent: ".tab-pane-inner",
            activeClass: "active",
            errorClass: ".messages .error",
            bodyClassToggle: "full-width"
        }, options);

        var $tabs = $(settings.tabContainer).find(settings.tabSelector);

        function setActiveTab() {
            var hash = window.location.hash;
            var $activeTab = $tabs.filter("[href='" + hash + "']");

            // Remove active class from all tabs
            $(settings.tabContainer).find("li").removeClass(settings.activeClass);

            // Add active class to selected tab
            if ($activeTab.length) {
                $activeTab.parent().addClass(settings.activeClass);
            }

            // Show the correct content
            $(settings.tabContent).hide();
            if (hash) {
                $(hash).show();
            }
        }

        function focusErrorTab() {
            $tabs.each(function () {
                var tabName = this.hash.replace("#", "");
                if ($("#" + tabName).find(settings.errorClass).length) {
                    window.location.hash = "#" + tabName;
                    return false; // Stop loop on first error tab
                }
            });
        }

        function initializeTabs() {
            if ($(settings.errorClass).length) {
                focusErrorTab();
            } else if (!window.location.hash) {
                window.location.replace($tabs.first().attr("href"));
            } else {
                setActiveTab();
            }
        }

        // Listen for hash changes
        $(window).on("hashchange", setActiveTab);

        // Initialize on page load
        initializeTabs();

        return this; // Enable jQuery chaining
    };
})(jQuery);


$(document).ready(function () {
    $(".tabs").hashTabs();
});