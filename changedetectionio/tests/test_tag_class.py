import re

import pytest
from bs4 import BeautifulSoup
from flask import url_for

from changedetectionio.flask_app import _jinja2_filter_sanitize_tag_class
from changedetectionio.processors import generate_processor_badge_colors


def test_non_ascii_tag_classes_are_distinct():
    titles = ['価格変動', '在庫状況', '空室情報', '价格变动', '재고', '🔔', '!!!', 'tag']
    classes = [_jinja2_filter_sanitize_tag_class(title) for title in titles]

    assert len(set(classes)) == len(titles)
    for title, class_name in zip(titles, classes, strict=True):
        assert re.fullmatch(r'[a-z][a-z0-9-]*', class_name)
        assert _jinja2_filter_sanitize_tag_class(title) == class_name


@pytest.mark.parametrize(
    ('title', 'expected'), [('News', 'news'), ('Sales 2026', 'sales2026'), ('123', 'tag123')]
)
def test_ascii_tag_classes_remain_unchanged(title, expected):
    assert _jinja2_filter_sanitize_tag_class(title) == expected


@pytest.mark.parametrize('endpoint', ['tags.tags_overview_page', 'watchlist.index'])
@pytest.mark.parametrize('custom_colour', [None, '#4f8ef7'])
def test_non_ascii_tag_colours_render_independently(client, endpoint, custom_colour):
    datastore = client.application.config['DATASTORE']
    titles = ['価格変動', '在庫状況', '空室情報']
    for title in titles:
        datastore.add_tag(title)
    if custom_colour:
        tag = next(
            tag
            for tag in datastore.data['settings']['application']['tags'].values()
            if tag['title'] == titles[0]
        )
        tag['tag_colour'] = custom_colour
        tag.commit()

    response = client.get(url_for(endpoint))
    assert response.status_code == 200
    document = BeautifulSoup(response.data, 'html.parser')
    badges = {
        badge.get_text(strip=True): next(
            class_name for class_name in badge['class'] if class_name.startswith('tag-')
        )
        for badge in document.select('a.watch-tag-list, a.button-tag')
        if badge.get_text(strip=True) in titles
    }
    assert len(badges) == len(titles)
    assert len(set(badges.values())) == len(titles)

    css = '\n'.join(style.get_text() for style in document.find_all('style'))
    for title, class_name in badges.items():
        selector = rf'\.watch-tag-list\.{re.escape(class_name)}\s*\{{\s*background-color:\s*'
        if custom_colour and title == titles[0]:
            assert re.search(selector + re.escape(custom_colour), css)
        else:
            colours = generate_processor_badge_colors(title)
            assert re.search(selector + re.escape(colours['light']['bg']), css)
            assert re.search(
                r'html\[data-darkmode="true"\]\s+' + selector + re.escape(colours['dark']['bg']),
                css,
            )
