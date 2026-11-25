/**
 * The "Group tag" field of a watch (input.tag-chips, rendered by TagChipsWidget in forms.py together with a
 * <datalist> of every group there is): every group that is in becomes a "chip" with an x, and the box to type
 * in is only ever the ONE name being typed, with the groups that match offered underneath.
 *
 * The field stays what the server always got, a comma separated list of group names:
 *
 *  - a hidden field takes the name of the text field and carries the list
 *  - the text field loses its name (it is not sent); picking a suggestion, a comma, Enter or leaving the
 *    field turns what is in it into a chip. A name that is not a group yet becomes one on save, as before
 *  - Backspace in the empty box takes the last chip off, the x of a chip takes that one off
 *
 * The groups come from the <datalist>, with their colours. The list shown here is our own and not the browser's
 * (the field is taken off the datalist): the browser's cannot show the groups in their colours.
 *
 * Without this script it is the plain text field, with the browser's suggestions from the datalist.
 */
(function ($) {
    function splitNames(text) {
        return String(text || '').split(',').map((name) => name.trim()).filter((name) => name !== '');
    }

    function setColours(element, colours) {
        if (!colours) {
            return;
        }
        element.style.setProperty('--tag-chip-bg', colours.light.bg);
        element.style.setProperty('--tag-chip-color', colours.light.color);
        element.style.setProperty('--tag-chip-dark-bg', colours.dark.bg);
        element.style.setProperty('--tag-chip-dark-color', colours.dark.color);
    }

    function setup(input) {
        const $input = $(input);
        const datalist = document.getElementById($input.attr('list') || '');
        if (!input.name || $input.data('tag-chips-ready')) {
            return;
        }
        $input.data('tag-chips-ready', true);

        // Every group there is: {title, colours}
        const groups = $(datalist).find('option').map(function () {
            let colours = null;
            try {
                colours = JSON.parse(this.getAttribute('data-colours'));
            } catch (e) {
                // Shown in the default colour
            }
            return {title: this.value, colours: colours};
        }).get();
        const coloursOf = {};   // lower case group name -> its colours
        groups.forEach((group) => {
            coloursOf[group.title.toLowerCase()] = group.colours;
        });

        const names = [];
        const placeholder = input.placeholder;
        let suggestions = [];
        let active = -1;

        const $field = $('<div class="tag-chips-field"></div>').insertBefore($input);
        const $chips = $('<span class="tag-chips-list" aria-live="polite"></span>').appendTo($field);
        $field.append($input);
        const $suggestions = $('<ul class="tag-chips-suggestions" role="listbox"></ul>')
            .attr('id', (input.id || input.name) + '-suggestions').appendTo($field).hide();
        const $hidden = $('<input type="hidden">').attr('name', input.name).insertAfter($field);

        // The white-on-transparent look of the field on the "Add a watch" page
        $field.toggleClass('tag-chips-transparent', $input.hasClass('transparent-field'));
        $input.removeAttr('name').removeAttr('list').attr({
            'autocomplete': 'off',
            'role': 'combobox',
            'aria-autocomplete': 'list',
            'aria-expanded': 'false',
            'aria-controls': $suggestions.attr('id'),
        });

        function has(name) {
            return names.some((n) => n.toLowerCase() === name.toLowerCase());
        }

        function render() {
            $chips.empty();
            names.forEach((name, i) => {
                const $chip = $('<span class="tag-chip"></span>')
                    .append($('<span class="tag-chip-text"></span>').text(name))
                    .append($('<button type="button" class="tag-chip-remove">&times;</button>')
                        .attr('aria-label', ($input.attr('data-remove-label') || 'Remove') + ' ' + name)
                        .attr('data-i', i));
                setColours($chip[0], coloursOf[name.toLowerCase()]);
                $chips.append($chip);
            });
            $hidden.val(names.join(', '));
            input.placeholder = names.length ? '' : placeholder;
        }

        function add(name) {
            name = name.trim();
            if (name !== '' && !has(name)) {
                names.push(name);
            }
        }

        // Everything in the box becomes chips
        function commit() {
            splitNames(input.value).forEach(add);
            input.value = '';
            render();
        }

        function renderSuggestions() {
            $suggestions.empty();
            suggestions.forEach((group, i) => {
                const $label = $('<span class="tag-chip"></span>').append($('<span class="tag-chip-text"></span>').text(group.title));
                setColours($label[0], group.colours);
                $('<li role="option"></li>')
                    .attr({'id': $suggestions.attr('id') + '-' + i, 'data-i': i, 'aria-selected': i === active ? 'true' : 'false'})
                    .toggleClass('active', i === active)
                    .append($label)
                    .appendTo($suggestions);
            });
            $suggestions.toggle(suggestions.length > 0);
            $input.attr('aria-expanded', suggestions.length > 0 ? 'true' : 'false');
            if (active >= 0) {
                $input.attr('aria-activedescendant', $suggestions.attr('id') + '-' + active);
                $suggestions.children().get(active).scrollIntoView({block: 'nearest'});
            } else {
                $input.removeAttr('aria-activedescendant');
            }
        }

        function closeSuggestions() {
            suggestions = [];
            active = -1;
            renderSuggestions();
        }

        // The groups with what is typed in their name that are not in the field yet, those that start with it first
        function suggest() {
            const typed = input.value.trim().toLowerCase();
            suggestions = groups
                .filter((group) => group.title.toLowerCase().indexOf(typed) !== -1 && !has(group.title))
                .sort((a, b) => {
                    const aStarts = a.title.toLowerCase().indexOf(typed) === 0;
                    const bStarts = b.title.toLowerCase().indexOf(typed) === 0;
                    return aStarts === bStarts ? a.title.toLowerCase().localeCompare(b.title.toLowerCase()) : (aStarts ? -1 : 1);
                });
            active = -1;
            renderSuggestions();
        }

        function pick(group) {
            add(group.title);
            input.value = '';
            closeSuggestions();
            render();
            input.focus();
        }

        // A click anywhere in the field is a click in the box
        $field.on('click', (e) => {
            if (e.target === $field[0] || e.target === $chips[0]) {
                input.focus();
            }
        });

        $chips.on('click', '.tag-chip-remove', function () {
            names.splice(parseInt($(this).attr('data-i'), 10), 1);
            render();
            input.focus();
        });

        // mousedown would take the focus out of the box, and leaving the box makes a chip of what is typed
        $suggestions.on('mousedown', (e) => e.preventDefault());
        $suggestions.on('click', 'li', function () {
            pick(suggestions[parseInt($(this).attr('data-i'), 10)]);
        });

        $input.on('input', () => {
            // A comma was typed or a list was pasted: what is complete becomes chips, what is after the last
            // comma stays to be typed on
            if (input.value.indexOf(',') !== -1) {
                const cut = input.value.lastIndexOf(',');
                const rest = input.value.slice(cut + 1);
                input.value = input.value.slice(0, cut);
                commit();
                input.value = rest.replace(/^\s+/, '');
            }
            suggest();
        });

        $input.on('focus click', suggest);

        $input.on('keydown', (e) => {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                e.preventDefault();
                if (!suggestions.length) {
                    suggest();
                    return;
                }
                const step = e.key === 'ArrowDown' ? 1 : -1;
                // One step past either end is "none of them", the typed name itself
                active = ((active + 1 + step + suggestions.length + 1) % (suggestions.length + 1)) - 1;
                renderSuggestions();
            } else if (e.key === 'Enter') {
                if (active >= 0) {
                    e.preventDefault();
                    pick(suggestions[active]);
                } else if (input.value.trim() !== '') {
                    // A typed name: a chip, not "save the form"
                    e.preventDefault();
                    closeSuggestions();
                    commit();
                }
            } else if (e.key === 'Escape') {
                if (suggestions.length) {
                    e.preventDefault();
                    e.stopPropagation();
                    closeSuggestions();
                }
            } else if (e.key === 'Backspace' && input.value === '' && names.length) {
                names.pop();
                render();
                suggest();
            }
        });

        // Leaving the box with something typed: that is a name too
        $input.on('blur', () => {
            closeSuggestions();
            if (input.value.trim() !== '') {
                commit();
            }
        });

        // Nothing typed is lost on Save
        $(input.form).on('submit', () => {
            if (input.value.trim() !== '') {
                commit();
            }
        });

        splitNames(input.value).forEach(add);
        input.value = '';
        render();
    }

    $(function () {
        $('input.tag-chips').each(function () {
            setup(this);
        });
    });
})(jQuery);
