/**
 * AI filter assist — sends the user's plain-English description to the
 * server-side /ui/ai-filter/<uuid>/suggest endpoint and pre-fills the
 * Include/Subtract/Trigger/Ignore fields with the model's suggestion.
 *
 * The user still has to hit "Save" on the form — we never write filters
 * without review.
 */
(function () {
  const $ = window.jQuery;
  const btn = document.getElementById('ai-filter-suggest-btn');
  if (!btn) return;

  const prompt = document.getElementById('ai-filter-prompt');
  const status = document.getElementById('ai-filter-status');
  const result = document.getElementById('ai-filter-result');

  function setStatus(msg, isError) {
    status.textContent = msg;
    status.style.color = isError ? 'var(--color-warning, #b00)' : 'inherit';
  }

  function appendLines(textarea, newLines) {
    if (!textarea || !newLines || !newLines.length) return;
    const existing = (textarea.value || '').trim();
    const toAdd = newLines
      .map((l) => String(l).trim())
      .filter((l) => l && existing.indexOf(l) === -1);
    if (!toAdd.length) return;
    textarea.value = (existing ? existing + '\n' : '') + toAdd.join('\n');
  }

  btn.addEventListener('click', async function () {
    const uuid = btn.getAttribute('data-uuid');
    const text = (prompt.value || '').trim();
    if (!text) {
      setStatus('Type what you want to monitor first.', true);
      prompt.focus();
      return;
    }

    btn.disabled = true;
    setStatus('Thinking…', false);
    result.style.display = 'none';
    result.textContent = '';

    try {
      const csrf = (typeof csrftoken === 'string') ? csrftoken : '';
      const r = await fetch(`/ui/ai-filter/${encodeURIComponent(uuid)}/suggest`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf,
        },
        body: JSON.stringify({ request: text }),
      });
      const data = await r.json().catch(() => ({}));

      if (!r.ok) {
        setStatus(data.error || `Request failed (HTTP ${r.status}).`, true);
        return;
      }

      // Pre-fill the textareas the user is about to review.
      const includeEl = document.querySelector('textarea[name="include_filters"]');
      const subtractEl = document.querySelector('textarea[name="subtractive_selectors"]');
      const triggerEl = document.querySelector('textarea[name="trigger_text"]');
      const ignoreEl = document.querySelector('textarea[name="ignore_text"]');

      appendLines(includeEl, data.include_filters);
      appendLines(subtractEl, data.subtractive_selectors);
      appendLines(triggerEl, data.trigger_text);
      appendLines(ignoreEl, data.ignore_text);

      const summary = data.reasoning
        ? `Suggestion applied: ${data.reasoning}`
        : 'Suggestion applied. Review the fields below and hit Save.';
      setStatus(summary, false);

      result.style.display = 'block';
      result.innerHTML =
        '<strong>Model output:</strong><br>' +
        [
          data.include_filters && data.include_filters.length
            ? 'Include filters: <code>' + data.include_filters.map(e => e.replace(/</g,'&lt;')).join(', ') + '</code>'
            : '',
          data.subtractive_selectors && data.subtractive_selectors.length
            ? 'Subtract: <code>' + data.subtractive_selectors.map(e => e.replace(/</g,'&lt;')).join(', ') + '</code>'
            : '',
          data.trigger_text && data.trigger_text.length
            ? 'Trigger text: <code>' + data.trigger_text.map(e => e.replace(/</g,'&lt;')).join(', ') + '</code>'
            : '',
          data.ignore_text && data.ignore_text.length
            ? 'Ignore text: <code>' + data.ignore_text.map(e => e.replace(/</g,'&lt;')).join(', ') + '</code>'
            : '',
        ].filter(Boolean).join('<br>');
    } catch (e) {
      setStatus('Network error: ' + (e && e.message ? e.message : e), true);
    } finally {
      btn.disabled = false;
    }
  });
})();
