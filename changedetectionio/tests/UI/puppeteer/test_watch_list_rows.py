#!/usr/bin/env python3
"""The watch list is kept current with whole rows: when a watch is updated the server sends its row as the list's own
template draws it, and the page puts it in place of the one it has (realtime.js, "watch_row").

Two tabs of one browser: what is done in the second shows in the list of the first without a reload, and what only
the first tab knows (which rows are ticked) and does (its buttons, its clicks on a row) is still there afterwards.
"""

from .browser import click_and_wait_for_new_page, run_in_browser, screenshot, site_url, wait_until
from .test_group_chips import BOX, _add_watch, _chips, _open_edit_page, _save

# The pink of a label with no colours of its own
DEFAULT_LABEL_COLOUR = 'rgba(231, 0, 105, 0.4)'


def _uuid_of(edit_url):
    return edit_url.rstrip('/').split('/')[-1]


async def _row(page, uuid):
    """What the first tab shows for the watch, read from the page"""
    return await page.evaluate("""(uuid) => {
        const row = document.querySelector('tr[data-watch-uuid="' + uuid + '"]');
        if (!row) return null;
        const icon = row.querySelector('img.favicon');
        return {
            classes: [...row.classList],
            title: (row.querySelector('.watch-title') || {}).innerText,
            groups: [...row.querySelectorAll('.watch-tag-list')].map((a) => ({title: a.textContent.trim(), href: a.getAttribute('href'),
                                                                                colours: [getComputedStyle(a).backgroundColor, getComputedStyle(a).color]})),
            ticked: row.querySelector('input[name="uuids"]').checked,
            edit: row.querySelector('a[href*="/edit/"]').getAttribute('href'),
            icons: row.querySelectorAll('td.watch-controls svg').length,
            unrendered_icons: row.querySelectorAll('i[data-feather]').length,
            date_tooltip: (row.querySelector('td.last-checked') || {}).title || '',
            favicon_src: icon ? (icon.getAttribute('src') || '') : null,
        };
    }""", uuid)


async def _click_on_the_row(page, uuid):
    """A click on the row itself, not on something in it (a click on its text or a button is not a click on the row)"""
    await page.evaluate("""(uuid) => {
        document.querySelector('tr[data-watch-uuid="' + uuid + '"] td.last-changed').dispatchEvent(new MouseEvent('click', {bubbles: true}));
    }""", uuid)


async def _still_the_same_page(page):
    return await page.evaluate("""() => window.listWasNotReloaded === true""")


def test_watch_list_rows_follow_what_happens_elsewhere(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(list_tab):
        first_edit = await _add_watch(list_tab, 'rows-first')
        second_edit = await _add_watch(list_tab, 'rows-second')
        first, second = _uuid_of(first_edit), _uuid_of(second_edit)

        await list_tab.goto(site_url('watchlist.index'))
        await list_tab.evaluate("""() => { window.listWasNotReloaded = true; }""")
        # The realtime connection is up and knows which rows this page shows
        await wait_until(list_tab, "window.cdioSocket && window.cdioSocket.connected", "the realtime connection")
        # One row ticked: that is this tab's own, the server does not know it
        await list_tab.click(f'tr[data-watch-uuid="{first}"] input[name="uuids"]')
        assert (await _row(list_tab, first))['ticked'] is True
        assert '1' in await list_tab.evaluate("""() => document.querySelector('#records-selected').innerText""")

        # In another tab: the first watch gets a group that does not exist yet, and a title
        other_tab = await list_tab.browser.newPage()
        await _open_edit_page(other_tab, first_edit)
        await other_tab.type(BOX, 'Made in the other tab')
        await other_tab.keyboard.press('Enter')
        await other_tab.evaluate("""() => { document.querySelector('input[name="title"]').value = 'Titled in the other tab'; }""")
        await _save(other_tab)

        # The list in the first tab shows both, by itself
        await wait_until(list_tab, f"""[...document.querySelectorAll('tr[data-watch-uuid="{first}"] .watch-tag-list')].some((a) => a.textContent.trim() === 'Made in the other tab')""",
                         "the new group in the row of the list that was already open")
        # (It arrived while the tab was in the background. To the front now: the browser driver cannot click in
        # a tab that is not showing.)
        await list_tab.bringToFront()
        row = await _row(list_tab, first)
        assert await _still_the_same_page(list_tab), "Without a reload"
        assert 'Titled in the other tab' in row['title']
        group = next(g for g in row['groups'] if g['title'] == 'Made in the other tab')
        assert group['colours'][0] != DEFAULT_LABEL_COLOUR, "In the group's colours, though the page was loaded before the group existed"
        assert '?tag=' in group['href']
        live_colours = group['colours']

        # What was the page's own is still there on the row that was put in
        assert row['ticked'] is True, "Still ticked"
        assert '1' in await list_tab.evaluate("""() => document.querySelector('#records-selected').innerText""")
        assert await list_tab.evaluate("""() => document.body.classList.contains('watch-selection-active')""")
        assert row['icons'] >= 2 and row['unrendered_icons'] == 0, "Its icons are drawn"
        assert row['date_tooltip'], "The date tooltip of 'checked' is set"
        assert (await _row(list_tab, second))['ticked'] is False
        await screenshot(list_tab, 'watch-list-row-from-other-tab', f'tr[data-watch-uuid="{first}"]')

        # The buttons of the row that was put in work, here in the list: pause, without leaving the page
        assert 'paused' not in row['classes']
        await list_tab.click(f'tr[data-watch-uuid="{first}"] button.pause-toggle.state-off')
        await wait_until(list_tab, f"""document.querySelector('tr[data-watch-uuid="{first}"]').classList.contains('paused')""", "the row to show as paused")
        assert await _still_the_same_page(list_tab), "Pause in a row that was put in is still done in the page"
        assert (await _row(list_tab, first))['ticked'] is True
        # And back
        await list_tab.click(f'tr[data-watch-uuid="{first}"] button.pause-toggle.state-on')
        await wait_until(list_tab, f"""!document.querySelector('tr[data-watch-uuid="{first}"]').classList.contains('paused')""", "the row to show as not paused")

        # A click on the row itself ticks it (the first row was put in several times by now), and unticks
        await _click_on_the_row(list_tab, first)
        assert (await _row(list_tab, first))['ticked'] is False
        await _click_on_the_row(list_tab, second)
        await _click_on_the_row(list_tab, first)
        assert (await _row(list_tab, first))['ticked'] is True and (await _row(list_tab, second))['ticked'] is True
        assert '2' in await list_tab.evaluate("""() => document.querySelector('#records-selected').innerText""")

        # Taken out of its group in the other tab: the label goes
        await other_tab.bringToFront()
        await _open_edit_page(other_tab, first_edit)
        assert await _chips(other_tab) == ['Made in the other tab']
        await other_tab.click('.tag-chips-field .tag-chip-remove')
        await _save(other_tab)
        await wait_until(list_tab, f"""document.querySelectorAll('tr[data-watch-uuid="{first}"] .watch-tag-list').length === 0""", "the group's label to go")
        assert (await _row(list_tab, first))['ticked'] is True
        assert await _still_the_same_page(list_tab)

        # Back in the group, and the list reloaded: what was shown live is what a reload shows
        await _open_edit_page(other_tab, first_edit)
        await other_tab.type(BOX, 'Made in the other tab')
        await other_tab.keyboard.press('Enter')
        await _save(other_tab)
        await wait_until(list_tab, f"""document.querySelectorAll('tr[data-watch-uuid="{first}"] .watch-tag-list').length === 1""", "the group's label to come back")
        live = await _row(list_tab, first)
        await list_tab.reload()
        reloaded = await _row(list_tab, first)
        assert reloaded['title'] == live['title']
        assert [g['title'] for g in reloaded['groups']] == [g['title'] for g in live['groups']]
        assert reloaded['groups'][0]['colours'] == live_colours == live['groups'][0]['colours']
        assert sorted(c for c in reloaded['classes'] if c not in ('pure-table-odd', 'pure-table-even')) == sorted(c for c in live['classes'] if c not in ('pure-table-odd', 'pure-table-even'))

        await other_tab.close()

    run_in_browser(steps, name='watch_list_rows_follow')


def test_rows_of_a_filtered_list_keep_its_group_in_their_buttons(client, live_server, measure_memory_usage, datastore_path, running_app):
    """A list filtered by a group: Edit and Recheck of its rows come back to that filtered list, also on a row the
    server sent again."""
    async def steps(list_tab):
        edit_url = await _add_watch(list_tab, 'rows-filtered')
        uuid = _uuid_of(edit_url)
        await _open_edit_page(list_tab, edit_url)
        await list_tab.type(BOX, 'Filter group')
        await list_tab.keyboard.press('Enter')
        await _save(list_tab)

        await list_tab.goto(site_url('watchlist.index'))
        group_url = await list_tab.evaluate("""(uuid) => [...document.querySelectorAll('tr[data-watch-uuid="' + uuid + '"] .watch-tag-list')].find((a) => a.textContent.trim() === 'Filter group').href""", uuid)
        tag_uuid = group_url.split('tag=')[1]
        await list_tab.goto(group_url)
        await list_tab.evaluate("""() => { window.listWasNotReloaded = true; }""")
        await wait_until(list_tab, "window.cdioSocket && window.cdioSocket.connected", "the realtime connection")
        before = await _row(list_tab, uuid)
        assert f'tag={tag_uuid}' in before['edit']

        # Something happens to the watch elsewhere
        other_tab = await list_tab.browser.newPage()
        await _open_edit_page(other_tab, edit_url)
        await other_tab.evaluate("""() => { document.querySelector('input[name="title"]').value = 'Renamed while filtered'; }""")
        await _save(other_tab)
        await wait_until(list_tab, f"""(document.querySelector('tr[data-watch-uuid="{uuid}"] .watch-title') || {{}}).innerText.includes('Renamed while filtered')""",
                         "the new title in the filtered list")
        after = await _row(list_tab, uuid)
        assert await _still_the_same_page(list_tab)
        assert f'tag={tag_uuid}' in after['edit'], "Edit still comes back to the filtered list"
        recheck = await list_tab.evaluate("""(uuid) => document.querySelector('tr[data-watch-uuid="' + uuid + '"] td.buttons button[formaction*="checknow"]').getAttribute('formaction')""", uuid)
        assert f'tag={tag_uuid}' in recheck
        await other_tab.close()

    run_in_browser(steps, name='rows_of_a_filtered_list')
