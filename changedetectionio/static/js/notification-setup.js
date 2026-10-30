// Notification setup widget (templates/_common_fields.html): pick an Apprise service, fill in its
// fields, and the server builds the URL (blueprint/settings/notifications, notification/apprise_form.py).
// "Add to list" appends it to the notification URLs textarea via appendNotificationUrl() from
// notifications.js, the textarea stays the source of truth.
$(function () {
    var $w = $('#notification-setup');
    if (!$w.length) return;

    var t = $w.data('i18n') || {};
    var $search = $('#ns-search'), $results = $('#ns-results'), $card = $w.find('.ns-card');
    var $url = $card.find('.ns-url'), $add = $card.find('.ns-add'), $msg = $card.find('.ns-message');
    var services = null, current = null, builtUrl = null, buildTimer = null, buildSeq = 0, active = -1;

    // ---- Service search ----

    function loadServices(done) {
        if (services) return done();
        $.getJSON($w.data('services-url'), function (data) {
            services = data;
            done();
        });
    }

    // Shown before anything is typed
    var POPULAR = ['mailtos', 'discord', 'tgram', 'slack', 'ntfys', 'jsons', 'workflow', 'matrixs', 'gotifys', 'pover'];

    // 0 = name starts with it, 1 = a word in the name or the scheme starts with it (punctuation ignored,
    // so "email" finds "Custom e-mail"), 2 = anywhere in the name
    function rank(s, q) {
        var name = s.name.toLowerCase();
        if (name.indexOf(q) === 0) return 0;
        var bare = q.replace(/[^a-z0-9]+/g, '');
        var words = name.split(/\s+/);
        if (s.schema.indexOf(q) === 0 || (' ' + name.replace(/[^a-z0-9]+/g, ' ')).indexOf(' ' + q) !== -1 ||
            $.grep(words, function (w) { return w.replace(/[^a-z0-9]+/g, '').indexOf(bare) === 0; }).length) return 1;
        return name.indexOf(q) !== -1 ? 2 : -1;
    }

    function showResults() {
        var q = $.trim($search.val()).toLowerCase();
        var matches;
        if (!q) {
            matches = $.map(POPULAR, function (schema) {
                return $.grep(services, function (s) { return s.schema === schema; })[0] || null;
            });
        } else {
            matches = $.grep(services, function (s) { return rank(s, q) !== -1; });
            matches.sort(function (a, b) { return rank(a, q) - rank(b, q); });  // stable, keeps A-Z within a rank
        }
        matches = matches.slice(0, 8);

        $results.empty();
        if (!matches.length) {
            $results.append($('<li class="ns-empty"></li>').text(t.noMatches || 'No matching service'));
        }
        $.each(matches, function (i, s) {
            $('<li role="option"></li>').attr('data-schema', s.schema)
                .append($('<span></span>').text(s.name), $('<code></code>').text(s.schema + '://'))
                .appendTo($results);
        });
        active = matches.length ? 0 : -1;
        highlight();
        $results.prop('hidden', false);
        $search.attr('aria-expanded', 'true');
    }

    function hideResults() {
        $results.prop('hidden', true);
        $search.attr('aria-expanded', 'false');
    }

    function highlight() {
        $results.children('[data-schema]').removeClass('active').eq(active).addClass('active');
    }

    $search.on('focus input', function () { loadServices(showResults); });

    $search.on('keydown', function (e) {
        var count = $results.children('[data-schema]').length;
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            if (!count) return;
            active = (active + (e.key === 'ArrowDown' ? 1 : count - 1)) % count;
            highlight();
        } else if (e.key === 'Enter') {
            e.preventDefault();  // never submit the settings form from here
            var schema = $results.children('[data-schema]').eq(active).data('schema');
            if (schema) pick(schema);
        } else if (e.key === 'Escape') {
            hideResults();
        }
    });

    // mousedown, not click: it fires before the search box loses focus
    $results.on('mousedown', 'li[data-schema]', function (e) {
        e.preventDefault();
        pick($(this).data('schema'));
    });
    $search.on('blur', function () { setTimeout(hideResults, 100); });

    // ---- Service form ----

    function pick(schema) {
        hideResults();
        $.getJSON($w.data('service-url').replace('__SCHEMA__', encodeURIComponent(schema)), renderCard);
    }

    function fieldInput(f) {
        var $wrap = $('<div class="ns-field"></div>').attr('data-key', f.key).attr('data-type', f.type);
        var id = 'ns-f-' + f.key;

        if (f.type === 'checkbox') {
            var $cb = $('<input type="checkbox">').attr('id', id).prop('checked', !!f.default);
            return $wrap.addClass('ns-check').append($cb, $('<label></label>').attr('for', id).text(f.label));
        }

        var $label = $('<label></label>').attr('for', id).text(f.label).toggleClass('ns-required', !!f.required);
        var $input;
        if (f.type === 'select') {
            $input = $('<select></select>');
            if (!f.required && f.default === undefined) $input.append('<option value=""></option>');
            $.each(f.values, function (i, v) { $input.append($('<option></option>').val(v).text(v)); });
            if (f.default !== undefined) $input.val(String(f.default));
        } else if (f.type === 'headers') {
            $input = $('<textarea rows="2"></textarea>').attr('placeholder', t.headersHint || 'One per line, Name=Value');
        } else {
            var type = {password: 'password', number: 'number', email: 'email'}[f.type] || 'text';
            $input = $('<input>').attr({type: type, autocomplete: type === 'password' ? 'new-password' : 'off'});
            if (f.type === 'list') $input.attr('placeholder', t.commaSeparated || 'Separate several with commas');
            if (f.min !== undefined) $input.attr('min', f.min);
            if (f.max !== undefined) $input.attr('max', f.max);
        }
        return $wrap.append($label, $input.attr('id', id));
    }

    function renderCard(form) {
        current = form;
        builtUrl = null;
        $card.find('.ns-name').text(form.name);
        $card.find('.ns-schema').text(form.schema + '://');
        $card.find('.ns-help').attr('href', form.setup_url || '#').toggle(!!form.setup_url);

        var $fields = $card.find('.ns-fields').first().empty();
        $.each(form.fields, function (i, f) { $fields.append(fieldInput(f)); });

        var $options = $card.find('.ns-options-body').empty();
        if (form.secure_toggle) {
            $options.append(fieldInput({key: '__secure', label: t.secure || 'Secure connection (TLS)', type: 'checkbox', default: true}));
        }
        $.each(form.options, function (i, f) { $options.append(fieldInput(f)); });
        $.each(form.kwargs, function (i, k) {
            $options.append(fieldInput({key: '__kw_' + k.key, label: k.label, type: 'headers'}).attr('data-kwarg', k.key));
        });
        $card.find('.ns-options').prop('open', false).toggle($options.children().length > 0);

        $url.text('').attr('title', '');
        $add.prop('disabled', true);
        $msg.removeClass('error ok').text(t.fillIn || 'Fill in the fields to build the URL');
        $card.prop('hidden', false);
        $fields.find('input, select, textarea').first().trigger('focus');
    }

    function collect() {
        var values = {}, extra = {}, secure = true;
        $card.find('.ns-field').each(function () {
            var $f = $(this), key = $f.data('key'), $input = $f.find('input, select, textarea');
            if ($f.data('type') === 'checkbox') {
                if (key === '__secure') secure = $input.prop('checked');
                else values[key] = $input.prop('checked');
            } else if ($f.data('kwarg')) {
                var pairs = {};
                $.each(($input.val() || '').split('\n'), function (i, line) {
                    var at = line.indexOf('=');
                    if (at > 0) pairs[$.trim(line.slice(0, at))] = $.trim(line.slice(at + 1));
                });
                extra[$f.data('kwarg')] = pairs;
            } else if ($.trim($input.val())) {
                values[key] = $input.val();
            }
        });
        return {schema: current.schema, values: values, secure: secure, extra: extra};
    }

    function build() {
        var seq = ++buildSeq;
        $.ajax({
            type: 'POST',
            url: $w.data('build-url'),
            contentType: 'application/json',
            data: JSON.stringify(collect()),
            dataType: 'json'
        }).always(function (data, status, xhr) {
            if (seq !== buildSeq) return;  // a newer build is on its way
            var res = (data && data.responseJSON) || data || {};
            if (res.url) {
                builtUrl = res.url;
                $url.text(res.url_masked).attr('title', res.url_masked);
                $msg.removeClass('error ok').text('');
            } else {
                builtUrl = null;
                $url.text('').attr('title', '');
                var text = res.missing ? (t.required || 'Required') + ': ' + res.missing.join(', ') : (res.error || '');
                $msg.removeClass('ok').addClass('error').text(text);
            }
            $add.prop('disabled', !builtUrl);
        });
    }

    $card.on('input change', 'input, select, textarea', function () {
        clearTimeout(buildTimer);
        buildTimer = setTimeout(build, 300);
    });

    // Enter in a field would submit the whole settings form
    $card.on('keydown', 'input', function (e) {
        if (e.key === 'Enter') e.preventDefault();
    });

    $add.on('click', function () {
        if (!builtUrl) return;
        appendNotificationUrl(builtUrl);
        $card.prop('hidden', true);
        $search.val('');
        current = builtUrl = null;
        $msg.text('');
        $w.find('.ns-added').remove();
        $('<span class="ns-added"></span>').text(t.added || 'Added to the list below')
            .insertAfter($w.find('.ns-search-wrap')).delay(2500).fadeOut(400, function () { $(this).remove(); });
    });

    $card.find('.ns-close').on('click', function (e) {
        e.preventDefault();
        $card.prop('hidden', true);
        current = builtUrl = null;
    });
});
