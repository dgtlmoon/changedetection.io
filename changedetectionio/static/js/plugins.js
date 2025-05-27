(function ($) {
    /**
     * debounce
     * @param {integer} milliseconds This param indicates the number of milliseconds
     *     to wait after the last call before calling the original function.
     * @param {object} What "this" refers to in the returned function.
     * @return {function} This returns a function that when called will wait the
     *     indicated number of milliseconds after the last call before
     *     calling the original function.
     */
    Function.prototype.debounce = function (milliseconds, context) {
        var baseFunction = this,
            timer = null,
            wait = milliseconds;

        return function () {
            var self = context || this,
                args = arguments;

            function complete() {
                baseFunction.apply(self, args);
                timer = null;
            }

            if (timer) {
                clearTimeout(timer);
            }

            timer = setTimeout(complete, wait);
        };
    };

    /**
     * throttle
     * @param {integer} milliseconds This param indicates the number of milliseconds
     *     to wait between calls before calling the original function.
     * @param {object} What "this" refers to in the returned function.
     * @return {function} This returns a function that when called will wait the
     *     indicated number of milliseconds between calls before
     *     calling the original function.
     */
    Function.prototype.throttle = function (milliseconds, context) {
        var baseFunction = this,
            lastEventTimestamp = null,
            limit = milliseconds;

        return function () {
            var self = context || this,
                args = arguments,
                now = Date.now();

            if (!lastEventTimestamp || now - lastEventTimestamp >= limit) {
                lastEventTimestamp = now;
                baseFunction.apply(self, args);
            }
        };
    };

    $.fn.highlightLines = function (configurations) {
        return this.each(function () {
            const $pre = $(this);
            const textContent = $pre.text();
            const lines = textContent.split(/\r?\n/); // Handles both \n and \r\n line endings

            // Build a map of line numbers to styles
            const lineStyles = {};

            configurations.forEach(config => {
                const {color, lines: lineNumbers} = config;
                lineNumbers.forEach(lineNumber => {
                    lineStyles[lineNumber] = color;
                });
            });

            // Function to escape HTML characters
            function escapeHtml(text) {
                return text.replace(/[&<>"'`=\/]/g, function (s) {
                    return "&#" + s.charCodeAt(0) + ";";
                });
            }

            // Process each line
            const processedLines = lines.map((line, index) => {
                const lineNumber = index + 1; // Line numbers start at 1
                const escapedLine = escapeHtml(line);
                const color = lineStyles[lineNumber];

                if (color) {
                    // Wrap the line in a span with inline style
                    return `<span style="background-color: ${color}">${escapedLine}</span>`;
                } else {
                    return escapedLine;
                }
            });

            // Join the lines back together
            const newContent = processedLines.join('\n');

            // Set the new content as HTML
            $pre.html(newContent);
        });
    };
    $.fn.miniTabs = function (tabsConfig, options) {
        const settings = {
            tabClass: 'minitab',
            tabsContainerClass: 'minitabs',
            activeClass: 'active',
            ...(options || {})
        };

        return this.each(function () {
            const $wrapper = $(this);
            const $contents = $wrapper.find('div[id]').hide();
            const $tabsContainer = $('<div>', {class: settings.tabsContainerClass}).prependTo($wrapper);

            // Generate tabs
            Object.entries(tabsConfig).forEach(([tabTitle, contentSelector], index) => {
                const $content = $wrapper.find(contentSelector);
                if (index === 0) $content.show(); // Show first content by default

                $('<a>', {
                    class: `${settings.tabClass}${index === 0 ? ` ${settings.activeClass}` : ''}`,
                    text: tabTitle,
                    'data-target': contentSelector
                }).appendTo($tabsContainer);
            });

            // Tab click event
            $tabsContainer.on('click', `.${settings.tabClass}`, function (e) {
                e.preventDefault();
                const $tab = $(this);
                const target = $tab.data('target');

                // Update active tab
                $tabsContainer.find(`.${settings.tabClass}`).removeClass(settings.activeClass);
                $tab.addClass(settings.activeClass);

                // Show/hide content
                $contents.hide();
                $wrapper.find(target).show();
            });
        });
    };

    // Object to store ongoing requests by namespace
    const requests = {};

    $.abortiveSingularAjax = function (options) {
        const namespace = options.namespace || 'default';

        // Abort the current request in this namespace if it's still ongoing
        if (requests[namespace]) {
            requests[namespace].abort();
        }

        // Start a new AJAX request and store its reference in the correct namespace
        requests[namespace] = $.ajax(options);

        // Return the current request in case it's needed
        return requests[namespace];
    };

})(jQuery);



function toggleOpacity(checkboxSelector, fieldSelector, inverted) {
    const checkbox = document.querySelector(checkboxSelector);
    const fields = document.querySelectorAll(fieldSelector);

    function updateOpacity() {
        const opacityValue = !checkbox.checked ? (inverted ? 0.6 : 1) : (inverted ? 1 : 0.6);
        fields.forEach(field => {
            field.style.opacity = opacityValue;
        });
    }

    // Initial setup
    updateOpacity();
    checkbox.addEventListener('change', updateOpacity);
}

function toggleVisibility(checkboxSelector, fieldSelector, inverted) {
    const checkbox = document.querySelector(checkboxSelector);
    const fields = document.querySelectorAll(fieldSelector);

    function updateOpacity() {
        const opacityValue = !checkbox.checked ? (inverted ? 'none' : 'block') : (inverted ? 'block' : 'none');
        fields.forEach(field => {
            field.style.display = opacityValue;
        });
    }

    // Initial setup
    updateOpacity();
    checkbox.addEventListener('change', updateOpacity);
}
