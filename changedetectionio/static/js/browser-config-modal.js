/**
 * The add/edit browser form as a dialog on the /browsers page.
 *
 * Links marked data-browser-config-modal are ordinary links to the form page; here they are
 * loaded with ?modal=1 instead, which makes the same route answer with just the form
 * (browser-config-modal.html). Saving posts it back the same way:
 *   - JSON {redirect}       -> saved, go there (the overview, which shows the flash message)
 *   - HTML                  -> the form again with its errors, shown in place
 *   - a redirect / an error -> something the dialog can't show (locked, not found), follow it
 */
(function () {
    'use strict';

    const dialog = document.getElementById('browser-config-dialog');
    // No <dialog> support: the links simply open the page version
    if (!dialog || typeof dialog.showModal !== 'function') {
        return;
    }
    const content = dialog.querySelector('.browser-config-dialog-content');

    function modalUrl(href) {
        const url = new URL(href, window.location.href);
        url.searchParams.set('modal', '1');
        url.hash = '';
        return url.toString();
    }

    // The dialog's tabs: one pane visible at a time, chosen by class. Hidden panes are only
    // display:none, so their fields are still submitted.
    function activateTab(paneId) {
        content.querySelectorAll('.browser-dialog-tabs button').forEach(function (tab) {
            const active = tab.dataset.pane === paneId;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        content.querySelectorAll('.tab-pane-inner').forEach(function (pane) {
            pane.classList.toggle('active', pane.id === paneId);
        });
        content.querySelector('.modal-body').scrollTop = 0;
    }

    // Mark the tabs whose pane holds a refused field and return the first of them
    function markErrorTabs() {
        let first = null;
        content.querySelectorAll('.browser-dialog-tabs button').forEach(function (tab) {
            const pane = document.getElementById(tab.dataset.pane);
            const hasError = !!(pane && pane.querySelector('.error'));
            tab.classList.toggle('has-error', hasError);
            if (hasError && !first) {
                first = tab.dataset.pane;
            }
        });
        return first;
    }

    function show(html) {
        // A contextual fragment runs the form's inline script (device / viewport syncing),
        // which innerHTML would not
        content.replaceChildren(document.createRange().createContextualFragment(html));
        if (window.feather) {
            window.feather.replace();
        }
        if (!dialog.open) {
            dialog.showModal();
        }
        // Open on the tab that needs attention, else the first one
        const firstTab = content.querySelector('.browser-dialog-tabs button');
        activateTab(markErrorTabs() || (firstTab && firstTab.dataset.pane));
        const focus = content.querySelector('.tab-pane-inner.active .error input, .tab-pane-inner.active input[type="text"]');
        if (focus) {
            focus.focus();
        }
    }

    async function handle(response, fallbackUrl) {
        const type = response.headers.get('content-type') || '';
        if (type.includes('application/json')) {
            window.location.href = (await response.json()).redirect;
            return;
        }
        if (response.redirected || !response.ok) {
            window.location.href = response.redirected ? response.url : fallbackUrl;
            return;
        }
        show(await response.text());
    }

    document.addEventListener('click', function (event) {
        const link = event.target.closest('a[data-browser-config-modal]');
        // Leave ctrl/shift/middle click alone - "open in a new tab" still gets the page
        if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) {
            return;
        }
        event.preventDefault();
        fetch(modalUrl(link.href), {credentials: 'same-origin'})
            .then(function (response) { return handle(response, link.href); })
            .catch(function () { window.location.href = link.href; });
    });

    content.addEventListener('submit', function (event) {
        const form = event.target;
        event.preventDefault();
        const body = new FormData(form, event.submitter);
        const buttons = form.querySelectorAll('.modal-footer button, .modal-footer input');
        buttons.forEach(function (button) { button.disabled = true; });
        fetch(form.action, {method: 'POST', body: body, credentials: 'same-origin'})
            .then(function (response) { return handle(response, window.location.href); })
            .catch(function () {
                buttons.forEach(function (button) { button.disabled = false; });
            });
    });

    content.addEventListener('click', function (event) {
        if (event.target.closest('[data-browser-dialog-close]')) {
            dialog.close();
        }
        const tab = event.target.closest('.browser-dialog-tabs button');
        if (tab) {
            activateTab(tab.dataset.pane);
        }
    });

    // Drop the form when closed, so a reopened dialog never flashes the previous browser's
    dialog.addEventListener('close', function () {
        content.replaceChildren();
    });
})();
