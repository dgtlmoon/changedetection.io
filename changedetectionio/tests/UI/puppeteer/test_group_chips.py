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
        # Put in whole, not key by key: the browser driver loses some characters ("<") when it types them
        await page.focus('form#new-watch-form input[name="name"]')
        await page.evaluate("""(title) => { document.querySelector('form#new-watch-form input[name="name"]').value = title; }""", title)
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

        # An existing group has the colours of its label in the watch list. A name that is not a group yet has the
        # colours it will have as one (test_new_name_has_the_colours_it_will_have_as_a_group)
        await _wait_for_coloured_chips(page, 3)
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
        await _wait_for_coloured_chips(page, 2)

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
        await _wait_for_coloured_chips(page, 2)
        await screenshot(page, 'group-chips-add-watch-page', '#watch-group-tag')

    run_in_browser(steps, name='group_chips_on_add_watch_page')


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


# The pink of a label with no colours of its own (--color-text-watch-tag-list), what a new name wrongly had
DEFAULT_LABEL_COLOUR = 'rgba(231, 0, 105, 0.4)'


async def _type_names(page, *names):
    """Each name into the box and Enter. Put in whole (see _add_groups), typing key by key is in the tests above."""
    for name in names:
        await page.focus(BOX)
        await page.evaluate(f"""(name) => {{
            const box = document.querySelector('{BOX}');
            box.value = name;
            box.dispatchEvent(new Event('input', {{bubbles: true}}));
        }}""", name)
        await page.keyboard.press('Escape')   # no suggestion picked by accident
        await page.keyboard.press('Enter')


async def _box_value(page):
    return await page.evaluate(f"""() => document.querySelector('{BOX}').value""")


async def _groups_listed(page):
    """The names in the groups list, as they are written there"""
    await page.goto(site_url('tags.tags_overview_page'))
    return await page.evaluate("""() => [...document.querySelectorAll('.group-overview-table td.title-col a')].map((a) => a.textContent.trim())""")


async def _group_edit_url(page, title):
    await page.goto(site_url('tags.tags_overview_page'))
    url = await page.evaluate("""(title) => {
        const row = [...document.querySelectorAll('.group-overview-table tbody tr')].find((tr) => tr.querySelector('td.title-col a') && tr.querySelector('td.title-col a').textContent.trim() === title);
        return row ? row.querySelector('a[href*="/tags/edit/"]').href : null;
    }""", title)
    assert url, f"The group {title} is in the groups list"
    return url


def test_new_name_has_the_colours_it_will_have_as_a_group(client, live_server, measure_memory_usage, datastore_path, running_app):
    """A name typed in that is not a group yet was always the default pink. Its colours are worked out in the
    browser the way the server does (from the name), so the chip does not change colour when it is saved."""
    names = ['Fresh group', 'Über Größe', '日本語のグループ', '🔥 hot deals', 'x' * 70]

    async def steps(page):
        edit_url = await _add_watch(page, 'chips-new-name-colours')
        await _open_edit_page(page, edit_url)
        await _type_names(page, *names)
        assert await _chips(page) == names

        before_saving = await _chip_colours(page)
        for name in names:
            assert before_saving[name][0] != DEFAULT_LABEL_COLOUR, f"{name!r} has colours of its own"
        assert len({tuple(colours) for colours in before_saving.values()}) > 1, "And not all the same ones"

        await _save(page)
        await _open_edit_page(page, edit_url)
        assert await _chips(page) == names
        # What the server says these groups look like, now that they are groups
        as_groups = await _expected_colours(page, 'light')
        assert {name: as_groups[name] for name in names} == before_saving
        assert await _chip_colours(page) == before_saving

    run_in_browser(steps, name='new_name_colours')


def test_new_name_colours_in_dark_mode(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        edit_url = await _add_watch(page, 'chips-new-name-colours-dark')
        await _open_edit_page(page, edit_url)
        await _type_names(page, 'Dark fresh group')
        before_saving = await _chip_colours(page)
        assert before_saving['Dark fresh group'][0] != DEFAULT_LABEL_COLOUR
        await _save(page)
        await _open_edit_page(page, edit_url)
        assert (await _expected_colours(page, 'dark'))['Dark fresh group'] == before_saving['Dark fresh group']

    run_in_browser(steps, name='new_name_colours_dark', dark_mode=True)


def test_existing_group_is_found_however_it_is_typed(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        await _add_groups(page, ['BMW', 'Bmw Parts', 'Éclair'])
        edit_url = await _add_watch(page, 'chips-capitals')
        await _open_edit_page(page, edit_url)

        # Offered whatever the capitals of what is typed
        for typed in ('bmw', 'BMW', 'bMw', 'MW'):
            await page.type(BOX, typed)
            await _wait_for_suggestions(page, ['BMW', 'Bmw Parts'])
            for _ in typed:
                await page.keyboard.press('Backspace')
        await page.type(BOX, 'éCL')
        await _wait_for_suggestions(page, ['Éclair'])
        for _ in 'éCL':
            await page.keyboard.press('Backspace')

        # Typed out in other capitals, without picking the suggestion: the group there is, as it is written.
        # It used to add a second name, "bmw".
        await _type_names(page, 'bmw', 'BMW PARTS', '  éclair  ')
        assert await _chips(page) == ['BMW', 'Bmw Parts', 'Éclair']
        assert await _sent_value(page) == 'BMW, Bmw Parts, Éclair'
        expected = await _expected_colours(page, 'light')
        assert await _chip_colours(page) == {name: expected[name] for name in ('BMW', 'Bmw Parts', 'Éclair')}

        # The same group again in any capitals is still the same group, and nothing is left to offer
        await _type_names(page, 'Bmw', 'bmw parts')
        assert await _chips(page) == ['BMW', 'Bmw Parts', 'Éclair']
        await page.type(BOX, 'bm')
        await _wait_for_suggestions(page, [])
        for _ in 'bm':
            await page.keyboard.press('Backspace')

        await _save(page)
        listed = await _groups_listed(page)
        assert sorted(name for name in listed if name.lower().startswith('bmw')) == ['BMW', 'Bmw Parts'], "No second group for the other capitals"

    run_in_browser(steps, name='existing_group_any_capitals')


def test_groups_are_kept_when_another_field_has_an_error(client, live_server, measure_memory_usage, datastore_path, running_app):
    """The form comes back with what was sent when it cannot be saved. This field came back holding the word
    "error" in place of its groups, and saving the corrected form put the watch in one group called "error"."""
    async def steps(page):
        await _add_groups(page, ['Kept one', 'Kept two', 'To be taken off'])
        edit_url = await _add_watch(page, 'chips-failed-save')
        await _open_edit_page(page, edit_url)
        await _type_names(page, 'Kept one', 'Kept two', 'To be taken off')
        await _save(page)

        await _open_edit_page(page, edit_url)
        assert await _chips(page) == ['Kept one', 'Kept two', 'To be taken off']
        # A change to the groups in the same save that fails: one off, a new one on, and one still in the box
        await page.click(f'{FIELD} .tag-chip:nth-child(3) .tag-chip-remove')
        await _type_names(page, 'New in the failed save')
        await page.type(BOX, 'Still in the box')
        await page.evaluate("""() => {
            const url = document.querySelector('input[name="url"]');
            url.removeAttribute('required');
            url.value = 'not a url';
        }""")
        await _save(page)

        wanted = ['Kept one', 'Kept two', 'New in the failed save', 'Still in the box']
        assert 'invalid URL' in await page.evaluate("""() => document.body.innerText"""), "The form is back with its error"
        await page.waitForSelector(BOX)
        assert await _chips(page) == wanted
        assert await _sent_value(page) == ', '.join(wanted)
        assert await _box_value(page) == ''
        colours = await _chip_colours(page)
        assert all(colour[0] != DEFAULT_LABEL_COLOUR for colour in colours.values())

        # Nothing was saved, and no group was made for a save that did not happen
        listed = await _groups_listed(page)
        assert 'New in the failed save' not in listed and 'error' not in listed

        # A second failed save in a row keeps them too
        await _open_edit_page(page, edit_url)
        await page.click(f'{FIELD} .tag-chip:nth-child(3) .tag-chip-remove')
        await _type_names(page, 'New in the failed save', 'Still in the box')
        await page.evaluate("""() => { const url = document.querySelector('input[name="url"]'); url.removeAttribute('required'); url.value = 'not a url'; }""")
        await _save(page)
        await page.evaluate("""() => { const url = document.querySelector('input[name="url"]'); url.removeAttribute('required'); url.value = 'still not a url'; }""")
        await _save(page)
        assert await _chips(page) == wanted

        # The URL put right: saved with the groups the form was showing
        await page.evaluate("""() => { document.querySelector('input[name="url"]').value = 'https://example.com/?chips-failed-save-fixed'; }""")
        await _save(page)
        await _open_edit_page(page, edit_url)
        assert await _chips(page) == wanted
        listed = await _groups_listed(page)
        assert 'error' not in [name.lower() for name in listed]
        assert 'New in the failed save' in listed and 'Still in the box' in listed

    run_in_browser(steps, name='groups_kept_when_save_fails')


def test_groups_are_kept_when_another_field_has_an_error_without_javascript(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        edit_url = await _add_watch(page, 'chips-failed-save-no-js')
        await page.goto('about:blank')
        await page.setJavaScriptEnabled(False)
        await page.goto(edit_url + '#general', waitUntil='domcontentloaded')
        plain_field = 'input[type="text"][name="tags"]'
        await page.type(plain_field, 'Plain kept one,  Plain kept two ,')
        await page.evaluate("""() => { const url = document.querySelector('input[name="url"]'); url.removeAttribute('required'); url.value = 'not a url'; }""")
        await _save(page)
        # (textContent: without the script no tab is open after a failed save, so the error is not "visible" text)
        assert 'invalid URL' in await page.evaluate("""() => document.querySelector('ul.errors').textContent""")
        assert await page.evaluate(f"""() => document.querySelector('{plain_field}').value""") == 'Plain kept one, Plain kept two'

    run_in_browser(steps, name='groups_kept_when_save_fails_no_js')


def test_names_that_try_to_break_the_field(client, live_server, measure_memory_usage, datastore_path, running_app):
    """Markup, quotes, a group really called "error", very long names, spaces, lists pasted with gaps in them."""
    markup = '<img src=x onerror="window.chipsRanMarkup=1">'
    quoted = 'He said "hi" & left'
    long_name = 'A very long group name ' * 6

    async def steps(page):
        await _add_groups(page, [markup, 'error'])
        edit_url = await _add_watch(page, 'chips-odd-names')
        await _open_edit_page(page, edit_url)

        # A name that is markup is offered and shown as the text it is
        await page.type(BOX, 'onerror')
        await _wait_for_suggestions(page, [markup])
        await page.click(f'{SUGGESTIONS} li:first-child')
        await _type_names(page, quoted, 'error', long_name)
        # Spaces around a name are not part of it
        await _type_names(page, '   Spaces around   ')
        # Pasted with empty places in the list, names of only spaces, and a name that is already in
        await page.evaluate(f"""() => {{
            const box = document.querySelector('{BOX}');
            box.value = ' , Pasted A ,, ,     ,ERROR, Pasted B,  ';
            box.dispatchEvent(new Event('input', {{bubbles: true}}));
        }}""")

        wanted = [markup, quoted, 'error', long_name.strip(), 'Spaces around', 'Pasted A', 'Pasted B']
        assert await _chips(page) == wanted
        assert await _box_value(page) == ''
        assert not await page.evaluate("""() => window.chipsRanMarkup"""), "A name is never run as markup"
        assert await page.evaluate(f"""() => document.querySelectorAll('{FIELD} img, {FIELD} script').length""") == 0

        # A long name stays inside the field
        widths = await page.evaluate(f"""() => [document.querySelector('{FIELD}').getBoundingClientRect().width,
            Math.max(...[...document.querySelectorAll('{FIELD} .tag-chip')].map((c) => c.getBoundingClientRect().width))]""")
        assert widths[1] <= widths[0]
        await screenshot(page, 'group-chips-odd-names', FIELD)

        await _save(page)
        await _open_edit_page(page, edit_url)
        assert await _chips(page) == wanted
        assert not await page.evaluate("""() => window.chipsRanMarkup""")
        # In the watch list and the groups list too
        await page.goto(site_url('watchlist.index'))
        assert not await page.evaluate("""() => window.chipsRanMarkup""")
        listed = await _groups_listed(page)
        assert not await page.evaluate("""() => window.chipsRanMarkup""")
        assert listed.count('error') == 1 and markup in listed and quoted in listed

    run_in_browser(steps, name='names_that_try_to_break_the_field')


def test_composing_a_character_does_not_end_the_name(client, live_server, measure_memory_usage, datastore_path, running_app):
    """Japanese, Chinese and Korean are typed by composing: Enter there picks the character, it is not Enter on
    the name. The browser marks those key presses, which is what is sent here."""
    async def steps(page):
        edit_url = await _add_watch(page, 'chips-composing')
        await _open_edit_page(page, edit_url)
        await page.focus(BOX)
        await page.evaluate(f"""() => {{
            const box = document.querySelector('{BOX}');
            box.dispatchEvent(new CompositionEvent('compositionstart', {{bubbles: true}}));
            box.value = 'にほん';
            box.dispatchEvent(new InputEvent('input', {{bubbles: true, isComposing: true}}));
            box.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', bubbles: true, cancelable: true, isComposing: true}}));
        }}""")
        assert await _chips(page) == [] and await _box_value(page) == 'にほん', "Still being composed"

        await page.evaluate(f"""() => {{
            const box = document.querySelector('{BOX}');
            box.value = '日本';
            box.dispatchEvent(new CompositionEvent('compositionend', {{bubbles: true, data: '日本'}}));
        }}""")
        assert await _chips(page) == [] and await _box_value(page) == '日本'
        await page.keyboard.press('Enter')
        assert await _chips(page) == ['日本']

    run_in_browser(steps, name='composing_a_character')


def test_group_action_of_the_watch_list(client, live_server, measure_memory_usage, datastore_path, running_app):
    """The "Group" action for the ticked watches is the same field in a dialog."""
    async def steps(page):
        await _add_groups(page, ['Audi'])
        edit_url = await _add_watch(page, 'chips-watch-list-action')
        await page.goto(site_url('watchlist.index'))
        await page.evaluate("""() => {
            const row = [...document.querySelectorAll('tr')].find((tr) => tr.innerText.includes('chips-watch-list-action') && tr.querySelector('input[name="uuids"]'));
            row.querySelector('input[name="uuids"]').click();
        }""")
        await page.click('#checkbox-assign-tag')
        await page.waitForSelector(f'.modal-dialog {BOX}', visible=True)

        # Found in other capitals, here too
        await page.type(BOX, 'audi')
        await _wait_for_suggestions(page, ['Audi'])
        await page.keyboard.press('Escape')   # the suggestions, not the dialog
        await page.waitForSelector(f'.modal-dialog[open] {BOX}', visible=True)
        await page.keyboard.press('Enter')
        await page.type(BOX, 'Made in the dialog')
        await page.keyboard.press('Enter')
        assert await _chips(page) == ['Audi', 'Made in the dialog']
        assert await page.querySelector('.modal-dialog[open]'), "Enter on a name does not confirm the dialog"
        colours = await _chip_colours(page)
        assert all(colour[0] != DEFAULT_LABEL_COLOUR for colour in colours.values())
        await screenshot(page, 'group-chips-watch-list-dialog', '.modal-dialog[open]')
        # A name still in the box when the dialog is confirmed counts too
        await page.type(BOX, 'Left in the dialog box')
        await page.click('.modal-dialog [data-action="confirm"]')

        async def groups_of_the_watch():
            await _open_edit_page(page, edit_url)
            return await _chips(page)

        for _ in range(20):
            chips = await groups_of_the_watch()
            if len(chips) == 3:
                break
        assert sorted(chips) == ['Audi', 'Left in the dialog box', 'Made in the dialog']
        assert (await _groups_listed(page)).count('Audi') == 1

    run_in_browser(steps, name='group_action_of_the_watch_list')


def test_groups_by_url_pattern_are_listed_under_the_field(client, live_server, measure_memory_usage, datastore_path, running_app):
    """A group can apply itself to every watch whose URL matches its pattern. Those are not in the field (the watch
    was not put in them), they are listed under it as labels in the group's colours, each a link to its group."""
    async def steps(page):
        await _add_groups(page, ['By wildcard', 'By plain text', 'Pattern does not match', 'Put in by hand'])
        for title, pattern, colour in (('By wildcard', '*example.com/*pattern-test*', '#1f8a4c'),
                                       ('By plain text', 'PATTERN-TEST', ''),
                                       ('Pattern does not match', '*other-site.org*', ''),
                                       ('Put in by hand', '*pattern-test*', '')):
            await page.goto(await _group_edit_url(page, title))
            await page.evaluate("""(pattern, colour) => {
                document.querySelector('input[name="url_match_pattern"]').value = pattern;
                if (colour) {
                    // "Custom colour" ticked, the colour picked: the page's own script copies it to the field that is sent
                    const tick = document.querySelector('#use_custom_colour');
                    if (!tick.checked) tick.click();
                    const picker = document.querySelector('#tag_colour_picker');
                    picker.value = colour;
                    picker.dispatchEvent(new Event('input', {bubbles: true}));
                    picker.dispatchEvent(new Event('change', {bubbles: true}));
                }
            }""", pattern, colour)
            await _save(page)

        edit_url = await _add_watch(page, 'pattern-test')
        await _open_edit_page(page, edit_url)
        await _type_names(page, 'Put in by hand')
        await _save(page)
        await _open_edit_page(page, edit_url)

        assert await _chips(page) == ['Put in by hand'], "Only the group it was put in is in the field"
        listed = await page.evaluate("""() => [...document.querySelectorAll('.auto-applied-groups a.tag-chip')].map((a) => {
            const style = getComputedStyle(a);
            return {title: a.textContent.trim(), href: a.getAttribute('href'), colours: [style.backgroundColor, style.color], pattern: a.getAttribute('title')};
        })""")
        assert sorted(group['title'] for group in listed) == ['By plain text', 'By wildcard'], "The two whose pattern matches, not the one put in by hand"
        assert 'automatically applied by URL pattern' in await page.evaluate("""() => document.querySelector('.auto-applied-groups').innerText""")

        # In the colours of the group: the one it was given, or the ones from its name
        expected = await _expected_colours(page, 'light')
        by_title = {group['title']: group for group in listed}
        assert by_title['By wildcard']['colours'] == expected['By wildcard']
        assert by_title['By wildcard']['colours'][0] == 'rgb(31, 138, 76)', "The colour the group was given"
        assert by_title['By plain text']['colours'] == expected['By plain text']
        assert by_title['By wildcard']['pattern'] == '*example.com/*pattern-test*'
        await screenshot(page, 'groups-by-url-pattern', '.auto-applied-groups')

        # Each is a link to its group
        assert by_title['By wildcard']['href'] in await _group_edit_url(page, 'By wildcard')
        await _open_edit_page(page, edit_url)
        await click_and_wait_for_new_page(page, '.auto-applied-groups a.tag-chip')
        assert '/tags/edit/' in page.url

        # A watch no pattern matches has no such list
        other = await _add_watch(page, 'no-group-pattern-here')
        await _open_edit_page(page, other)
        assert await page.querySelector('.auto-applied-groups') is None

    run_in_browser(steps, name='groups_by_url_pattern')


def test_group_name_with_a_comma_is_refused_and_an_old_one_is_kept_whole(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        # Not as a new name on the groups page
        await page.goto(site_url('tags.tags_overview_page'))
        await page.focus('form#new-watch-form input[name="name"]')
        await page.evaluate("""() => { document.querySelector('form#new-watch-form input[name="name"]').value = 'Comma, Group'; }""")
        await press_enter_and_wait_for_new_page(page)
        assert 'cannot have a comma' in await page.evaluate("""() => document.body.textContent""")
        assert 'Comma, Group' not in await _groups_listed(page)

        # Nor by renaming a group
        await _add_groups(page, ['To be renamed'])
        await page.goto(await _group_edit_url(page, 'To be renamed'))
        await page.evaluate("""() => { document.querySelector('input[name="title"]').value = 'Renamed, with a comma'; }""")
        await _save(page)
        assert 'cannot have a comma' in await page.evaluate("""() => document.body.textContent""")
        listed = await _groups_listed(page)
        assert 'To be renamed' in listed and 'Renamed, with a comma' not in listed

        # A group that has a comma in its name from before cannot be made here any more, so the field is given one
        # the way the page would: a field of its own with that group in its list and in its value.
        edit_url = await _add_watch(page, 'chips-comma')
        await _open_edit_page(page, edit_url)
        result = await page.evaluate("""() => {
            const form = document.querySelector('input[name="url"]').form;
            form.insertAdjacentHTML('beforeend', `<div id="old-comma-group">
                <input type="text" name="old_groups" id="old_groups" class="tag-chips" list="old_groups-groups" value="First, Sales, EU, sales ,eu, Sales, Last">
                <datalist id="old_groups-groups">
                    <option value="Sales, EU" data-colours='{"light":{"bg":"rgb(1, 2, 3)","color":"rgb(4, 5, 6)"},"dark":{"bg":"rgb(1, 2, 3)","color":"rgb(4, 5, 6)"}}'></option>
                    <option value="Sales" data-colours='{"light":{"bg":"rgb(7, 8, 9)","color":"rgb(4, 5, 6)"},"dark":{"bg":"rgb(7, 8, 9)","color":"rgb(4, 5, 6)"}}'></option>
                </datalist></div>`);
            $('#old_groups').tagChips();
            const chips = [...document.querySelectorAll('#old-comma-group .tag-chip')];
            return {chips: chips.map((chip) => chip.querySelector('.tag-chip-text').textContent),
                    backgrounds: chips.map((chip) => getComputedStyle(chip).backgroundColor),
                    sent: document.querySelector('input[type="hidden"][name="old_groups"]').value};
        }""")
        assert result['chips'] == ['First', 'Sales, EU', 'Sales', 'Last'], "One chip for the group with the comma, not one for each piece"
        assert result['backgrounds'][1] == 'rgb(1, 2, 3)' and result['backgrounds'][2] == 'rgb(7, 8, 9)'
        assert result['sent'] == 'First, Sales, EU, Sales, Last'

    run_in_browser(steps, name='group_name_with_a_comma')


def test_groups_are_found_without_their_accents(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        await _add_groups(page, ['Überwachung', 'Crème brûlée', 'Señal Ñandú', 'Zażółć'])
        edit_url = await _add_watch(page, 'chips-accents')
        await _open_edit_page(page, edit_url)
        for typed, found in (('uberw', 'Überwachung'), ('ÜBERW', 'Überwachung'), ('creme brulee', 'Crème brûlée'),
                             ('nandu', 'Señal Ñandú'), ('zazolc', 'Zażółć'), ('brûl', 'Crème brûlée')):
            await page.type(BOX, typed)
            if found == 'Zażółć':
                # "ł" is a letter of its own, not an "l" with an accent: typed with its accents it is found
                await _wait_for_suggestions(page, [])
                for _ in typed:
                    await page.keyboard.press('Backspace')
                await _type_names(page)   # nothing
                await page.evaluate(f"""() => {{
                    const box = document.querySelector('{BOX}');
                    box.value = 'zazół';
                    box.dispatchEvent(new Event('input', {{bubbles: true}}));
                }}""")
                await _wait_for_suggestions(page, ['Zażółć'])
                await page.evaluate(f"""() => {{
                    const box = document.querySelector('{BOX}');
                    box.value = '';
                    box.dispatchEvent(new Event('input', {{bubbles: true}}));
                }}""")
                continue
            await _wait_for_suggestions(page, [found])
            for _ in typed:
                await page.keyboard.press('Backspace')

        # Picked, it is the group as it is written
        await page.type(BOX, 'creme')
        await _wait_for_suggestions(page, ['Crème brûlée'])
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('Enter')
        assert await _chips(page) == ['Crème brûlée']
        # Typed out without its accents and entered it is a name of its own: for the server that is another group
        await _type_names(page, 'Uberwachung')
        assert await _chips(page) == ['Crème brûlée', 'Uberwachung']

    run_in_browser(steps, name='groups_found_without_accents')


def test_back_button_and_reload_show_what_is_saved(client, live_server, measure_memory_usage, datastore_path, running_app):
    """Browsers put back what was typed in a form when a page is come back to. Here that would be the field's own
    text from before the script took the names out of it."""
    async def steps(page):
        await _add_groups(page, ['Saved one', 'Saved two'])
        edit_url = await _add_watch(page, 'chips-back-button')
        await _open_edit_page(page, edit_url)
        await _type_names(page, 'Saved one', 'Saved two')
        await _save(page)
        await _open_edit_page(page, edit_url)
        assert await _chips(page) == ['Saved one', 'Saved two']

        # Changed but not saved, then away and back
        await page.click(f'{FIELD} .tag-chip:nth-child(1) .tag-chip-remove')
        await _type_names(page, 'Never saved')
        await page.type(BOX, 'half typed')
        await page.goto(site_url('watchlist.index'))
        await page.goBack()
        await page.waitForSelector(BOX, visible=True)

        async def consistent():
            chips, sent, box = await _chips(page), await _sent_value(page), await _box_value(page)
            assert sent == ', '.join(chips), "What is shown is what would be sent"
            assert 'Saved one, Saved two' not in box, "The field's text from before the chips is not put back in the box"
            assert len(chips) == len(set(chips))
            return chips

        chips = await consistent()
        # Either the page as it was left or the page as it is saved, never a mix of the two
        assert chips in (['Saved two', 'Never saved'], ['Saved two', 'Never saved', 'half typed'], ['Saved one', 'Saved two'])

        await page.reload()
        await page.waitForSelector(BOX, visible=True)
        assert await consistent() == ['Saved one', 'Saved two'], "Reloaded: what is saved"
        assert await _box_value(page) == ''
        assert await page.evaluate(f"""() => document.querySelector('{BOX}').getAttribute('autocomplete')""") == 'off'

    run_in_browser(steps, name='back_button_and_reload')


def test_chips_by_touch(client, live_server, measure_memory_usage, datastore_path, running_app):
    """A phone: no mouse and no keyboard shortcuts, everything by tapping."""
    async def steps(page):
        await _add_groups(page, ['Touch one', 'Touch two'])
        edit_url = await _add_watch(page, 'chips-touch')
        await page.emulate(viewport={'width': 390, 'height': 800, 'isMobile': True, 'hasTouch': True, 'deviceScaleFactor': 2},
                           userAgent='Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36')
        await _open_edit_page(page, edit_url)

        # Tapping the field offers the groups, tapping one takes it and keeps the keyboard up for the next
        await page.tap(BOX)
        await page.type(BOX, 'touch')
        await _wait_for_suggestions(page, ['Touch one', 'Touch two'])
        await page.tap(f'{SUGGESTIONS} li:nth-child(2)')
        assert await _chips(page) == ['Touch two']
        assert await page.evaluate(f"""() => document.activeElement === document.querySelector('{BOX}')""")

        await page.type(BOX, 'touch')
        await _wait_for_suggestions(page, ['Touch one'])
        await page.tap(f'{SUGGESTIONS} li:first-child')
        assert await _chips(page) == ['Touch two', 'Touch one']

        # The x of a chip is big enough for a finger, and takes that chip off
        size = await page.evaluate(f"""() => {{ const r = document.querySelector('{FIELD} .tag-chip-remove').getBoundingClientRect(); return [r.width, r.height]; }}""")
        assert size[0] >= 24 and size[1] >= 24, f"The x is {size} pixels"
        await page.tap(f'{FIELD} .tag-chip:nth-child(1) .tag-chip-remove')
        assert await _chips(page) == ['Touch one']

        # Tapping somewhere else with a name typed makes it a chip (there is no Enter to rely on)
        await page.tap(BOX)
        await page.type(BOX, 'Typed on a phone')
        await page.tap('input[name="url"]')
        assert await _chips(page) == ['Touch one', 'Typed on a phone']
        # Nothing sticks out of the screen
        assert await page.evaluate(f"""() => document.querySelector('{FIELD}').getBoundingClientRect().right <= window.innerWidth""")
        await screenshot(page, 'group-chips-phone', FIELD)

    run_in_browser(steps, name='chips_by_touch')


def test_what_a_screen_reader_is_told(client, live_server, measure_memory_usage, datastore_path, running_app):
    """Not a screen reader test (there is none here): the names, roles and states it would read are in the page."""
    async def steps(page):
        await _add_groups(page, ['Read aloud one', 'Read aloud two'])
        edit_url = await _add_watch(page, 'chips-screen-reader')
        await _open_edit_page(page, edit_url)

        def about_the_box():
            return page.evaluate(f"""() => {{
                const box = document.querySelector('{BOX}');
                const list = document.getElementById(box.getAttribute('aria-controls'));
                const active = box.getAttribute('aria-activedescendant');
                return {{role: box.getAttribute('role'), expanded: box.getAttribute('aria-expanded'), autocomplete: box.getAttribute('aria-autocomplete'),
                        label: (document.querySelector('label[for="' + box.id + '"]') || {{}}).textContent,
                        listRole: list && list.getAttribute('role'), options: list ? [...list.querySelectorAll('[role="option"]')].map((o) => o.textContent) : null,
                        selected: list ? [...list.querySelectorAll('[aria-selected="true"]')].map((o) => o.textContent) : null,
                        active: active && document.getElementById(active) && document.getElementById(active).textContent}};
            }}""")

        box = await about_the_box()
        assert box['role'] == 'combobox' and box['autocomplete'] == 'list' and box['expanded'] == 'false'
        assert box['label'] and box['label'].strip(), "The box has a label that is read with it"
        assert box['listRole'] == 'listbox'

        await page.type(BOX, 'read aloud')
        await _wait_for_suggestions(page, ['Read aloud one', 'Read aloud two'])
        box = await about_the_box()
        assert box['expanded'] == 'true' and box['options'] == ['Read aloud one', 'Read aloud two'] and box['selected'] == []

        # The arrow keys say which one is on
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('ArrowDown')
        box = await about_the_box()
        assert box['active'] == 'Read aloud two' and box['selected'] == ['Read aloud two']
        await page.keyboard.press('Enter')
        box = await about_the_box()
        assert box['expanded'] == 'false' and box['active'] is None

        # A chip's x says what it takes off, and changes to the chips are announced
        await _type_names(page, 'Read aloud one')
        chips = await page.evaluate(f"""() => ({{
            live: document.querySelector('{FIELD} .tag-chips-list').getAttribute('aria-live'),
            buttons: [...document.querySelectorAll('{FIELD} .tag-chip-remove')].map((b) => [b.tagName, b.getAttribute('type'), b.getAttribute('aria-label')])}})""")
        assert chips['live'] == 'polite'
        assert chips['buttons'] == [['BUTTON', 'button', 'Remove Read aloud two'], ['BUTTON', 'button', 'Remove Read aloud one']]

        # All of it by keyboard: Tab reaches the x of each chip, Enter on it takes the chip off
        await page.focus(f'{FIELD} .tag-chip:nth-child(1) .tag-chip-remove')
        await page.keyboard.press('Enter')
        assert await _chips(page) == ['Read aloud one']
        assert page.url.split('#')[0] == edit_url, "Enter on the x does not save the form"

    run_in_browser(steps, name='what_a_screen_reader_is_told')
