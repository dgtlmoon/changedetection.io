#!/usr/bin/env python3
"""The "Group tag" field of a watch, used in a real browser (static/js/tag-chips.js).

Each group in the field is a chip, the existing groups are suggested while typing, and what is saved is the
comma separated list of names the field always sent - which is also all it is without JavaScript.

The application runs as a process of its own (the running_app fixture), so everything here goes through its
pages like a person would: nothing is put into or read from the datastore directly.
"""

import json

from .browser import click_and_wait_for_new_page, press_enter_and_wait_for_new_page, run_in_browser, screenshot, site_url, wait_until

FIELD = '.tag-chips-field'
BOX = f'{FIELD} input.tag-chips'
SUGGESTIONS = f'{FIELD} .tag-chips-suggestions'


async def _add_groups(page, titles):
    await page.goto(site_url('tags.tags_overview_page'))
    for title in titles:
        await page.type('form#new-watch-form input[name="name"]', title)
        # Enter, not a click on Save: the "Tag added" message of the group before can be lying over the button
        await press_enter_and_wait_for_new_page(page)


async def _add_watch(page, marker):
    """Through the form above the watch list. Returns the address of the new watch's edit page."""
    await page.goto(site_url('watchlist.index'))
    # Never fetched, every watch of the application under test is paused
    await page.type('#new-watch-form input[name="url"]', f'https://example.com/?{marker}')
    await click_and_wait_for_new_page(page, '#add-watch-go')
    edit_url = await page.evaluate('''(marker) => {
        const row = [...document.querySelectorAll('tr')].find((tr) => tr.innerText.includes(marker) && tr.querySelector('a[href*="/edit/"]'));
        return row ? row.querySelector('a[href*="/edit/"]').href : null;
    }''', marker)
    assert edit_url, "The new watch is in the list with a link to edit it"
    return edit_url.split('#')[0]


async def _open_edit_page(page, edit_url):
    await page.goto(edit_url)
    await page.waitForSelector(BOX, visible=True)


async def _chips(page):
    return await page.evaluate(f'''() => [...document.querySelectorAll('{FIELD} .tag-chips-list .tag-chip-text')].map((e) => e.textContent)''')


async def _sent_value(page):
    """What the form would send for the field"""
    return await page.evaluate('''() => document.querySelector('input[type="hidden"][name="tags"]').value''')


async def _suggestions(page):
    return await page.evaluate(f'''() => {{
        const list = document.querySelector('{SUGGESTIONS}');
        return list.offsetParent === null ? [] : [...list.querySelectorAll('li')].map((li) => li.textContent);
    }}''')


async def _wait_for_suggestions(page, expected):
    try:
        await wait_until(page, f'''JSON.stringify((() => {{
            const list = document.querySelector('{SUGGESTIONS}');
            return list.offsetParent === null ? [] : [...list.querySelectorAll('li')].map((li) => li.textContent);
        }})()) === JSON.stringify({json.dumps(expected)})''', "suggestions")
    except AssertionError:
        raise AssertionError(f"Expected the suggestions {expected}, the list shows {await _suggestions(page)}")


async def _wait_for_coloured_chips(page, how_many):
    await wait_until(page, f'''document.querySelectorAll('{FIELD} .tag-chips-list .tag-chip[style*="--tag-chip-bg"]').length === {how_many}''',
                     f"{how_many} chips in the colours of their group")


async def _save(page):
    await click_and_wait_for_new_page(page, '#save_button')


async def _chip_colours(page):
    """{name: [background, text colour]} as the browser paints the chips"""
    return await page.evaluate(f'''() => Object.fromEntries([...document.querySelectorAll('{FIELD} .tag-chips-list .tag-chip')].map((chip) => {{
        const style = getComputedStyle(chip);
        return [chip.querySelector('.tag-chip-text').textContent, [style.backgroundColor, style.color]];
    }}))''')


async def _expected_colours(page, mode):
    """{name: [background, text colour]} of every group as the page was given them for light or dark, painted by the browser"""
    return await page.evaluate('''(mode) => {
        const probe = document.body.appendChild(document.createElement('span'));
        const painted = {};
        for (const option of document.querySelectorAll('datalist#tags-groups option')) {
            const colours = JSON.parse(option.getAttribute('data-colours'));
            probe.style.backgroundColor = colours[mode].bg;
            probe.style.color = colours[mode].color;
            const style = getComputedStyle(probe);
            painted[option.value] = [style.backgroundColor, style.color];
        }
        probe.remove();
        return painted;
    }''', mode)


def test_groups_as_chips_with_suggestions(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        await _add_groups(page, ['Alpha news', 'Alphabet', 'Beta'])
        edit_url = await _add_watch(page, 'chips-with-suggestions')
        await _open_edit_page(page, edit_url)
        assert await _chips(page) == [] and await _sent_value(page) == ''

        # Typing part of a name offers the groups with that in their name, a click on one makes it a chip
        await page.type(BOX, 'alp')
        await _wait_for_suggestions(page, ['Alpha news', 'Alphabet'])
        assert await page.evaluate(f'''() => !document.querySelector('{BOX}').hasAttribute('list')'''), "Our list, not the browser's own from the datalist as well"
        await screenshot(page, 'group-chips-suggestions', FIELD, room_below=110)
        await page.click(f'{SUGGESTIONS} li:first-child')
        assert await _chips(page) == ['Alpha news']
        assert await page.evaluate(f'''() => document.activeElement === document.querySelector('{BOX}') && document.activeElement.value === \'\'''') , "The cursor is back in the empty box for the next group"

        # A group that is in already is not offered again. The keyboard picks one too
        await page.type(BOX, 'alp')
        await _wait_for_suggestions(page, ['Alphabet'])
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('Enter')
        assert await _chips(page) == ['Alpha news', 'Alphabet']

        # A comma ends a name, Enter ends a name (and does not save the form): several groups, one field
        await page.type(BOX, 'Beta,')
        assert await _chips(page) == ['Alpha news', 'Alphabet', 'Beta']
        await page.type(BOX, 'Brand new group')
        await page.keyboard.press('Enter')
        assert await _chips(page) == ['Alpha news', 'Alphabet', 'Beta', 'Brand new group']
        assert page.url.split('#')[0] == edit_url, "Enter on a typed name does not save the form"

        # The same group again, however it is typed, is not there twice
        await page.type(BOX, 'bETA')
        await page.keyboard.press('Enter')
        assert await _chips(page) == ['Alpha news', 'Alphabet', 'Beta', 'Brand new group']

        # Pasted in one go
        await page.evaluate(f'''() => {{
            const box = document.querySelector('{BOX}');
            box.value = 'Pasted one, Pasted two, Past';
            box.dispatchEvent(new Event('input', {{bubbles: true}}));
        }}''')
        assert await _chips(page) == ['Alpha news', 'Alphabet', 'Beta', 'Brand new group', 'Pasted one', 'Pasted two']
        assert await page.evaluate(f'''() => document.querySelector('{BOX}').value''') == 'Past', "What is after the last comma is still being typed"
        for _ in 'Past':
            await page.keyboard.press('Backspace')

        # Backspace in the empty box takes the last chip off, the x of a chip takes that one off
        await page.keyboard.press('Backspace')
        assert await _chips(page) == ['Alpha news', 'Alphabet', 'Beta', 'Brand new group', 'Pasted one']
        await page.keyboard.press('Backspace')
        await page.click(f'{FIELD} .tag-chip:nth-child(2) .tag-chip-remove')
        assert await _chips(page) == ['Alpha news', 'Beta', 'Brand new group']
        assert await _sent_value(page) == 'Alpha news, Beta, Brand new group'

        # Escape closes the suggestions and leaves what was typed
        await page.type(BOX, 'alp')
        await _wait_for_suggestions(page, ['Alphabet'])
        await page.keyboard.press('Escape')
        await _wait_for_suggestions(page, [])
        assert await page.evaluate(f'''() => document.querySelector('{BOX}').value''') == 'alp'
        for _ in 'alp':
            await page.keyboard.press('Backspace')

        # An existing group has the colours of its label in the watch list, a name that is not a group yet the default
        await _wait_for_coloured_chips(page, 2)
        expected = await _expected_colours(page, 'light')
        colours = await _chip_colours(page)
        assert colours['Alpha news'] == expected['Alpha news'] and colours['Beta'] == expected['Beta']
        assert colours['Alpha news'] != colours['Beta'] != colours['Brand new group']
        await screenshot(page, 'group-chips-light', FIELD)

        # A name still in the box when Save is clicked is not lost
        await page.type(BOX, 'Left in the box')
        await _save(page)

        await _open_edit_page(page, edit_url)
        assert await _chips(page) == ['Alpha news', 'Beta', 'Brand new group', 'Left in the box']

        # The names that were not groups were made into groups, the one taken off again was left alone
        await page.goto(site_url('tags.tags_overview_page'))
        listed = await page.evaluate('''() => document.body.innerText''')
        for title in ('Alpha news', 'Alphabet', 'Beta', 'Brand new group', 'Left in the box'):
            assert title in listed
        assert 'Pasted one' not in listed and 'Pasted two' not in listed

        # Every chip off and saved: the watch is in no group
        await _open_edit_page(page, edit_url)
        for _ in range(4):
            await page.click(f'{FIELD} .tag-chip-remove')
        assert await _sent_value(page) == ''
        await _save(page)
        await _open_edit_page(page, edit_url)
        assert await _chips(page) == []

    run_in_browser(steps, name='groups_as_chips_with_suggestions')


def test_group_chips_in_dark_mode(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        await _add_groups(page, ['Night shift', 'Nightly builds'])
        edit_url = await _add_watch(page, 'chips-dark-mode')
        await _open_edit_page(page, edit_url)
        assert await page.evaluate('''() => document.documentElement.getAttribute('data-darkmode')''') == 'true'

        await page.type(BOX, 'Night shift,Not a group yet,night')
        await _wait_for_suggestions(page, ['Nightly builds'])
        await _wait_for_coloured_chips(page, 1)

        # The dark colours of the group, not the light ones
        dark, light = await _expected_colours(page, 'dark'), await _expected_colours(page, 'light')
        assert dark['Night shift'] != light['Night shift']
        assert (await _chip_colours(page))['Night shift'] == dark['Night shift']

        # The field and the list of suggestions are dark like the inputs around them
        painted = await page.evaluate(f'''() => ({{
            field: getComputedStyle(document.querySelector('{FIELD}')).backgroundColor,
            url_input: getComputedStyle(document.querySelector('input[name="url"]')).backgroundColor,
            suggestions: getComputedStyle(document.querySelector('{SUGGESTIONS}')).backgroundColor,
            page: getComputedStyle(document.body).backgroundColor,
        }})''')
        assert painted['field'] == painted['url_input']
        assert painted['suggestions'] != 'rgb(255, 255, 255)'
        await screenshot(page, 'group-chips-dark', FIELD, room_below=80)

    run_in_browser(steps, name='group_chips_in_dark_mode', dark_mode=True)


def test_group_chips_on_add_watch_page(client, live_server, measure_memory_usage, datastore_path, running_app):
    """The same field on the "Add a watch" page, on its coloured panel."""
    async def steps(page):
        await _add_groups(page, ['Gamma rays'])
        await page.goto(site_url('add_watch_ui.add_watch_ui_index'))
        await page.waitForSelector(BOX, visible=True)

        await page.type(BOX, 'gam')
        await _wait_for_suggestions(page, ['Gamma rays'])
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('Enter')
        await page.type(BOX, 'Another one,')
        assert await _chips(page) == ['Gamma rays', 'Another one']
        assert await _sent_value(page) == 'Gamma rays, Another one'
        await _wait_for_coloured_chips(page, 1)
        await screenshot(page, 'group-chips-add-watch-page', '#watch-group-tag')

    run_in_browser(steps, name='group_chips_on_add_watch_page')


def test_group_dialog_can_remove_existing_groups(client, live_server, measure_memory_usage, datastore_path, running_app):
    """The watch list's "Group" dialog has "Also remove any existing group assigned", which is never ticked when
    the dialog opens."""
    tick = '.modal-dialog[open] input[name="bulk_groups_replace"]'

    async def steps(page):
        await _add_groups(page, ['Was in this', 'Moved to this'])
        edit_url = await _add_watch(page, 'chips-dialog-remove-existing')
        await _open_edit_page(page, edit_url)
        await page.type(BOX, 'Was in this')
        await page.keyboard.press('Enter')
        await _save(page)

        async def open_dialog():
            await page.goto(site_url('watchlist.index'))
            # By its edit link: once it has been checked the row shows the page's title, not the address it was added by
            await page.evaluate("""(uuid) => {
                const row = [...document.querySelectorAll('tr')].find((tr) => tr.querySelector('a[href*="/edit/' + uuid + '"]') && tr.querySelector('input[name="uuids"]'));
                const box = row.querySelector('input[name="uuids"]');
                if (!box.checked) box.click();
            }""", edit_url.rstrip('/').split('/')[-1])
            await page.click('#checkbox-assign-tag')
            await page.waitForSelector(f'.modal-dialog[open] {BOX}', visible=True)

        async def groups_of_the_watch(expected):
            for _ in range(20):
                await _open_edit_page(page, edit_url)
                chips = await _chips(page)
                if sorted(chips) == sorted(expected):
                    return chips
            return chips

        # Not ticked to begin with, and its label is what is clicked
        await open_dialog()
        assert await page.evaluate(f"""() => document.querySelector('{tick}').checked""") is False
        assert 'Also remove any existing group assigned' in await page.evaluate("""() => document.querySelector('.modal-dialog[open] .bulk-group-replace').innerText""")

        # Ticked and then the dialog cancelled: nothing happens, and it is not ticked the next time
        await page.click('.modal-dialog[open] .bulk-group-replace')
        assert await page.evaluate(f"""() => document.querySelector('{tick}').checked""") is True
        await page.type(BOX, 'Moved to this')
        await page.click('.modal-dialog[open] [data-action="cancel"]')
        assert await groups_of_the_watch(['Was in this']) == ['Was in this']
        await open_dialog()
        assert await page.evaluate(f"""() => document.querySelector('{tick}').checked""") is False

        # Left unticked: added to the group it is in
        await page.type(BOX, 'Moved to this')
        await screenshot(page, 'group-dialog-remove-existing', '.modal-dialog[open]')
        await page.click('.modal-dialog[open] [data-action="confirm"]')
        assert sorted(await groups_of_the_watch(['Was in this', 'Moved to this'])) == ['Moved to this', 'Was in this']

        # Ticked: only the group named
        await open_dialog()
        await page.type(BOX, 'moved to this')
        await page.click(tick)
        await page.click('.modal-dialog[open] [data-action="confirm"]')
        assert await groups_of_the_watch(['Moved to this']) == ['Moved to this']
        await page.goto(site_url('tags.tags_overview_page'))
        assert 'Was in this' in await page.evaluate("""() => document.querySelector('.group-overview-table').innerText"""), "The group itself is still there"

    run_in_browser(steps, name='group_dialog_remove_existing')


def test_group_field_without_javascript(client, live_server, measure_memory_usage, datastore_path, running_app):
    """Without the script it is the text field of comma separated group names, and saves the same."""
    async def steps(page):
        edit_url = await _add_watch(page, 'chips-without-javascript')

        # Scripts are switched off on an empty page: the watch list's own scripts are running, and with them
        # stopped in mid-air the browser does not leave that page
        await page.goto('about:blank')
        await page.setJavaScriptEnabled(False)
        # Without the script that opens the first tab, a tab shows when the address points at it
        # (pyppeteer is not told the page has finished loading with scripts off, the document itself is enough)
        await page.goto(edit_url + '#general', waitUntil='domcontentloaded')
        assert await page.querySelector(FIELD) is None, "No chips without the script"
        plain_field = 'input[type="text"][name="tags"]'
        assert await page.evaluate(f'''() => document.querySelector('{plain_field}').list.options.length''') >= 1, "The browser's own suggestions, from the datalist"
        await page.type(plain_field, 'Plain one, Plain two')
        await screenshot(page, 'group-field-without-javascript', plain_field)
        await _save(page)

        await page.goto(edit_url + '#general', waitUntil='domcontentloaded')
        assert await page.evaluate(f'''() => document.querySelector('{plain_field}').value''') == 'Plain one, Plain two'

        # And with the script back, the same two groups as chips
        await page.setJavaScriptEnabled(True)
        # (by way of another page: from "#general" to the same address without it nothing is loaded)
        await page.goto(site_url('watchlist.index'))
        await _open_edit_page(page, edit_url)
        assert await _chips(page) == ['Plain one', 'Plain two']

    run_in_browser(steps, name='group_field_without_javascript')
