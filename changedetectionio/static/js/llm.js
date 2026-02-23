/* llm.js — LLM Connections management (settings page)
 * Depends on: jQuery (global), LLM_CONNECTIONS + LLM_I18N injected by Jinja2 template.
 */
(function ($) {
    'use strict';

    // Provider presets: [value, label, model, api_base, tpm]
    // tpm = tokens-per-minute limit (0 = unlimited / local).
    // Defaults reflect free-tier or conservative tier-1 limits.
    var LLM_PRESETS = [
        ['openai-mini',      'OpenAI — gpt-4o-mini',             'gpt-4o-mini',                              '',                          200000],
        ['openai-4o',        'OpenAI — gpt-4o',                  'gpt-4o',                                   '',                           30000],
        ['anthropic-haiku',  'Anthropic — claude-3-haiku',       'anthropic/claude-3-haiku-20240307',        '',                          100000],
        ['anthropic-sonnet', 'Anthropic — claude-3-5-sonnet',    'anthropic/claude-3-5-sonnet-20241022',     '',                           40000],
        ['groq-8b',          'Groq — llama-3.1-8b-instant',      'groq/llama-3.1-8b-instant',               '',                            6000],
        ['groq-70b',         'Groq — llama-3.3-70b-versatile',   'groq/llama-3.3-70b-versatile',            '',                            6000],
        ['gemini-flash',     'Google — gemini-1.5-flash',        'gemini/gemini-1.5-flash',                 '',                         1000000],
        ['mistral-small',    'Mistral — mistral-small',          'mistral/mistral-small-latest',            '',                          500000],
        ['deepseek',         'DeepSeek — deepseek-chat',         'deepseek/deepseek-chat',                  '',                           50000],
        ['openrouter',       'OpenRouter (custom model)',         'openrouter/',                             '',                           20000],
        ['ollama-llama',     'Ollama — llama3.1 (local)',        'ollama/llama3.1',    'http://localhost:11434',     0],
        ['ollama-mistral',   'Ollama — mistral (local)',         'ollama/mistral',     'http://localhost:11434',     0],
        ['lmstudio',         'LM Studio (local)',                'openai/local',       'http://localhost:1234/v1',   0],
    ];

    var presetMap = {};
    $.each(LLM_PRESETS, function (_, p) { presetMap[p[0]] = p; });

    function escHtml(s) {
        return $('<div>').text(String(s)).html();
    }

    function maskKey(k) {
        if (!k) return '<span style="color:var(--color-grey-700)">—</span>';
        return escHtml(k.substring(0, 4)) + '••••';
    }

    function serialise() {
        $('#llm-connections-json').val(JSON.stringify(LLM_CONNECTIONS));
    }

    function renderTable() {
        var $tbody = $('#llm-connections-tbody');
        $tbody.empty();
        var ids = Object.keys(LLM_CONNECTIONS);
        if (!ids.length) {
            $tbody.html('<tr class="llm-empty"><td colspan="6">' + escHtml(LLM_I18N.noConnections) + '</td></tr>');
            return;
        }
        $.each(ids, function (_, id) {
            var c   = LLM_CONNECTIONS[id];
            var tpm = parseInt(c.tokens_per_minute || 0, 10);
            var tpmLabel = tpm ? tpm.toLocaleString() : '<span style="color:var(--color-grey-700)">∞</span>';
            $tbody.append(
                '<tr>' +
                '<td class="llm-col-def">' +
                    '<input type="radio" class="llm-default-radio" name="llm_default_radio"' +
                    ' title="' + escHtml(LLM_I18N.setDefault) + '"' +
                    (c.is_default ? ' checked' : '') +
                    ' data-id="' + escHtml(id) + '">' +
                '</td>' +
                '<td class="llm-col-name">'  + escHtml(c.name)  + '</td>' +
                '<td class="llm-col-model">' + escHtml(c.model) + '</td>' +
                '<td class="llm-col-key">'   + maskKey(c.api_key) + '</td>' +
                '<td class="llm-col-tpm">'   + tpmLabel + '</td>' +
                '<td class="llm-col-del">' +
                    '<button type="button" class="llm-del"' +
                    ' title="' + escHtml(LLM_I18N.remove) + '"' +
                    ' data-id="' + escHtml(id) + '">×</button>' +
                '</td>' +
                '</tr>'
            );
        });
    }

    $(function () {
        // Event delegation on tbody — survives re-renders
        $('#llm-connections-tbody')
            .on('change', '.llm-default-radio', function () {
                var chosen = String($(this).data('id'));
                $.each(LLM_CONNECTIONS, function (k) {
                    LLM_CONNECTIONS[k].is_default = (k === chosen);
                });
                serialise();
            })
            .on('click', '.llm-del', function () {
                var id = String($(this).data('id'));
                delete LLM_CONNECTIONS[id];
                var remaining = Object.keys(LLM_CONNECTIONS);
                if (remaining.length && !remaining.some(function (k) { return LLM_CONNECTIONS[k].is_default; })) {
                    LLM_CONNECTIONS[remaining[0]].is_default = true;
                }
                renderTable();
                serialise();
            });

        // Preset dropdown pre-fills add form
        $('#llm-preset').on('change', function () {
            var p = presetMap[$(this).val()];
            if (!p) return;
            $('#llm-add-name').val(p[1].replace(/\s*—.*/, '').trim());
            $('#llm-add-model').val(p[2]);
            $('#llm-add-base').val(p[3]);
            $('#llm-add-tpm').val(p[4] !== undefined ? p[4] : 0);
            $('#llm-add-key').val('');
        });

        // Add connection
        $('#llm-btn-add').on('click', function () {
            var name  = $.trim($('#llm-add-name').val());
            var model = $.trim($('#llm-add-model').val());
            var key   = $.trim($('#llm-add-key').val());
            var base  = $.trim($('#llm-add-base').val());
            var tpm   = parseInt($('#llm-add-tpm').val(), 10) || 0;
            if (!name || !model) {
                alert(LLM_I18N.nameModelRequired);
                return;
            }
            var id = 'llm-' + Date.now();
            var isFirst = !Object.keys(LLM_CONNECTIONS).length;
            LLM_CONNECTIONS[id] = {
                name: name, model: model, api_key: key, api_base: base,
                tokens_per_minute: tpm, is_default: isFirst
            };
            $('#llm-preset, #llm-add-name, #llm-add-model, #llm-add-key, #llm-add-base').val('');
            $('#llm-add-tpm').val('0');
            renderTable();
            serialise();
        });

        // Show/hide API key visibility
        $('#llm-key-toggle').on('click', function () {
            var $inp = $('#llm-add-key');
            if ($inp.attr('type') === 'password') {
                $inp.attr('type', 'text');
                $(this).text(LLM_I18N.hide);
            } else {
                $inp.attr('type', 'password');
                $(this).text(LLM_I18N.show);
            }
        });

        // Serialise connections to hidden field before form submit
        $('form.settings').on('submit', serialise);

        // Init
        renderTable();
        serialise();
    });

}(jQuery));
