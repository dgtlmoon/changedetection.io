#!/usr/bin/env python3
"""The form above the watch list ("Web page URL ... Watch") has a group field, the same chips field as a watch's
"Group tag". It shows with the other options once a URL is typed, and starts with the open group in it when the
list is filtered by one."""

from .browser import click_and_wait_for_new_page, run_in_browser, screenshot, site_url, wait_until
from .test_group_chips import _add_groups, _chips, _open_edit_page

FORM = '#new-watch-form'
FIELD = f'{FORM} .tag-chips-field'
BOX = f'{FIELD} input.tag-chips'


async def _form_chips(page):
    return await page.evaluate(f"""() => [...document.querySelectorAll('{FIELD} .tag-chip-text')].map((e) => e.textContent)""")


async def _edit_url_of(page, marker):
    url = await page.evaluate("""(marker) => {
        const row = [...document.querySelectorAll('tr')].find((tr) => tr.innerText.includes(marker) && tr.querySelector('a[href*="/edit/"]'));
        return row ? row.querySelector('a[href*="/edit/"]').href.split('#')[0] : null;
    }""", marker)
    assert url, f"The watch added for {marker} is in the list"
    return url


def test_quick_add_form_has_a_group_field(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        await _add_groups(page, ['Quick existing'])
        await page.goto(site_url('watchlist.index'))

        # With the other options: there once a URL is typed
        assert await page.evaluate(f"""() => document.querySelector('#quick-watch-group').offsetParent === null"""), "Not shown before a URL is typed"
        await page.type(f'{FORM} input[name="url"]', 'https://example.com/?quick-add-groups')
        await page.waitForSelector(BOX, visible=True)

        # An existing group from the suggestions, and a new one
        await page.type(BOX, 'quick ex')
        await wait_until(page, f"""[...document.querySelectorAll('{FIELD} .tag-chips-suggestions li')].map((li) => li.textContent).join() === 'Quick existing'""", "the group to be suggested")
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('Enter')
        await page.type(BOX, 'Quick new')
        await page.keyboard.press('Enter')
        assert await _form_chips(page) == ['Quick existing', 'Quick new']
        assert await page.evaluate("""() => window.location.pathname""") in ('/', ''), "Enter on a group name does not send the form"
        # In line with its label, inside the form
        layout = await page.evaluate(f"""() => {{
            const label = document.querySelector('#quick-watch-group label').getBoundingClientRect();
            const field = document.querySelector('{FIELD}').getBoundingClientRect();
            const form = document.querySelector('{FORM}').getBoundingClientRect();
            return {{sameLine: Math.abs((label.top + label.height / 2) - (field.top + field.height / 2)) < 8, inside: field.right <= form.right + 1 && field.left > label.right}};
        }}""")
        assert layout == {'sameLine': True, 'inside': True}
        await screenshot(page, 'quick-add-group', '#add-watch-ui')

        # A third name still in the box when "Watch" is clicked counts too
        await page.type(BOX, 'Quick left in the box')
        await click_and_wait_for_new_page(page, '#add-watch-go')
        edit_url = await _edit_url_of(page, 'quick-add-groups')
        await _open_edit_page(page, edit_url)
        # (a watch's groups are not kept in the order they were given)
        assert sorted(await _chips(page)) == ['Quick existing', 'Quick left in the box', 'Quick new']

        # No group named: the watch is in none
        await page.goto(site_url('watchlist.index'))
        await page.type(f'{FORM} input[name="url"]', 'https://example.com/?quick-add-no-group')
        await click_and_wait_for_new_page(page, '#add-watch-go')
        await _open_edit_page(page, await _edit_url_of(page, 'quick-add-no-group'))
        assert await _chips(page) == []

    run_in_browser(steps, name='quick_add_group_field')


def test_quick_add_from_inside_a_group_starts_with_that_group(client, live_server, measure_memory_usage, datastore_path, running_app):
    async def steps(page):
        await _add_groups(page, ['Open group'])
        await page.goto(site_url('tags.tags_overview_page'))
        group_list = await page.evaluate("""() => [...document.querySelectorAll('.group-overview-table td.title-col a')].find((a) => a.textContent.trim() === 'Open group').href""")
        await page.goto(group_list)

        await page.type(f'{FORM} input[name="url"]', 'https://example.com/?quick-add-inside-group')
        await page.waitForSelector(BOX, visible=True)
        assert await _form_chips(page) == ['Open group'], "The group the list is filtered by is in the field already"
        await page.type(BOX, 'And another')
        await page.keyboard.press('Enter')
        await click_and_wait_for_new_page(page, '#add-watch-go')

        assert 'tag=' in page.url, "Back in the list of that group"
        edit_url = await _edit_url_of(page, 'quick-add-inside-group')
        await _open_edit_page(page, edit_url)
        assert sorted(await _chips(page)) == ['And another', 'Open group']

        # The open group can be taken out of the field: the new watch is then only where it was put
        await page.goto(group_list)
        await page.type(f'{FORM} input[name="url"]', 'https://example.com/?quick-add-not-in-open-group')
        await page.waitForSelector(BOX, visible=True)
        await page.click(f'{FIELD} .tag-chip-remove')
        await page.type(BOX, 'And another')
        await page.keyboard.press('Enter')
        await click_and_wait_for_new_page(page, '#add-watch-go')
        await page.goto(site_url('watchlist.index'))
        await _open_edit_page(page, await _edit_url_of(page, 'quick-add-not-in-open-group'))
        assert await _chips(page) == ['And another']

    run_in_browser(steps, name='quick_add_inside_group')
