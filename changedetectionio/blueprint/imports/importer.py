from abc import abstractmethod
import time
from wtforms import ValidationError
from loguru import logger
from flask_babel import gettext

from changedetectionio.forms import validate_url


def _jinja_expression_spans(text):
    """Return the (start, end) spans of every Jinja2 expression in `text`.

    Spaces inside a Jinja2 expression are part of the expression, never a
    separator - `{% now 'Europe/Berlin', '%d' %}` contains one.
    """
    from changedetectionio.jinja2_custom import JINJA2_MARKER_PATTERN

    spans = []
    if not text:
        return spans

    for m in JINJA2_MARKER_PATTERN.finditer(text):
        opener = text[m.start():m.start() + 2]
        closer = '%}' if opener == '{%' else '}}'
        end = text.find(closer, m.end())
        if end == -1:
            # Unclosed - it runs to the end of the text
            spans.append((m.start(), len(text)))
            return spans
        spans.append((m.start(), end + 2))

    return spans


def _jinja_expressions_closed(text):
    """True when every Jinja2 expression in `text` is properly closed."""
    from changedetectionio.jinja2_custom import JINJA2_MARKER_PATTERN

    if not text or not JINJA2_MARKER_PATTERN.search(text):
        return True

    for start, end in _jinja_expression_spans(text):
        if end >= len(text) and not text.rstrip().endswith(('%}', '}}')):
            return False

    return True


def _is_complete_url(url_part):
    """True when `url_part` is a whole URL and not a fragment of one.

    A URL may only contain a space inside a Jinja2 expression. When there is no
    Jinja2 in it, the part has to be a syntactically valid URL on its own - which
    rules out a cut-off query string like `https://example.com/?q=hello world`.
    """
    from changedetectionio.jinja2_custom import JINJA2_MARKER_PATTERN
    from changedetectionio import strtobool
    import os

    if not url_part:
        return False

    # Every Jinja2 expression has to be closed, otherwise the URL continues.
    if not _jinja_expressions_closed(url_part):
        return False

    if JINJA2_MARKER_PATTERN.search(url_part):
        # A templated URL can't be syntax checked before it is rendered, so trust
        # the closing check above and let the normal add_watch() validation have
        # the final say.
        return True

    import validators
    allow_simplehost = not strtobool(os.getenv('BLOCK_SIMPLEHOSTS', 'False'))
    try:
        return bool(validators.url(url_part, simple_host=allow_simplehost))
    except Exception:
        return False


def _is_whole_line_a_url(line):
    """True when the entire line is a usable URL, spaces and all.

    `normalize_url_encoding()` is what the app already uses to turn a query
    string with literal spaces into a valid URL, so a line like
    `https://example.com/?q=hello world` is one URL and not a URL plus tags.
    A space in the PATH (`https://example.com tag1`) is not valid and stays a
    separator.

    Lines carrying Jinja2 are never normalised here - encoding would destroy
    the template - so they fall back to being treated as a URL plus tags.
    """
    from changedetectionio.jinja2_custom import JINJA2_MARKER_PATTERN
    from changedetectionio.validate_url import normalize_url_encoding
    import validators

    if JINJA2_MARKER_PATTERN.search(line):
        return False

    try:
        normalised = normalize_url_encoding(line)
        return bool(validators.url(normalised, simple_host=True))
    except Exception as e:
        logger.debug(f"Import URL check failed for '{line}': {e}")
        return False


def split_url_and_tags(line):
    """Split an imported line into (url, tags).

    The import format is `<url> <tags>` where tags are a comma separated list, e.g.
    `https://example.com tag1, tag2`. The old code did `url.split(" ", 1)` which
    truncated any URL that legitimately contains a space:

      * `https://example.com/search?q=website monitoring`  -> the url became
        `https://example.com/search?q=website` and the rest became tags (#1568)
      * `https://example.com/?d={% now 'Europe/Berlin', '%d' %}` -> the url became
        `https://example.com/?d={%` and the rest became tags (#1516)

    A space only separates the URL from the tags when the URL part is COMPLETE and
    what follows reads like a tag list. Every space outside a Jinja2 expression is
    tried as a candidate separator, and the first one where both halves make sense
    wins:

      * the left part is a complete URL (no cut-off query string, no unclosed
        Jinja2 expression)
      * the right part reads like a tag list - a comma separated list, or a single
        word

    A tail with spaces but no comma is NOT a tag list (tags are comma delimited),
    so it stays part of the URL. When the tail is a single word it is still
    ambiguous - `https://example.com/?q=hello world` is one URL, while
    `https://example.com tag1` is a URL plus a tag - so the whole line is only
    treated as a URL when it actually is one.

    When no candidate separator works the whole line is the URL.

    Returns (url, tags) with tags == "" when the line carries no tags.
    """
    line = line.strip()
    if not line:
        return "", ""

    if ' ' not in line:
        return line, ""

    # Spaces inside a Jinja2 expression are part of the expression
    jinja_spans = _jinja_expression_spans(line)

    def inside_jinja(index):
        return any(start < index < end for start, end in jinja_spans)

    for index, char in enumerate(line):
        if char != ' ' or inside_jinja(index):
            continue

        url_part = line[:index].rstrip()
        tag_part = line[index + 1:].strip()

        if not url_part or not tag_part:
            continue

        if not _is_complete_url(url_part):
            continue

        # Tags are comma delimited, so a tail with spaces but no comma is more URL.
        # A single word is ambiguous - see the note in the docstring.
        if ',' not in tag_part and ' ' in tag_part:
            continue

        # Unambiguous tag list (comma separated) - split here.
        if ',' in tag_part:
            return url_part, tag_part

        # Single word tail. Only a tag when the whole line is not itself a URL.
        if _is_whole_line_a_url(line):
            return line, ""

        return url_part, tag_part

    # No separator worked - the whole line is the URL
    return line, ""


class Importer():
    remaining_data = []
    new_uuids = []
    good = 0

    def __init__(self):
        self.new_uuids = []
        self.good = 0
        self.remaining_data = []
        self.import_profile = None
        self.limit_reported = False

    @abstractmethod
    def run(self,
            data,
            flash,
            datastore):
        pass

    def watch_limit_hit(self, datastore, flash):
        """True once PAGE_WATCH_LIMIT leaves no room - the caller must then stop importing.

        Asked before each add_watch() so the limit is reported once for the whole file.
        add_watch() would otherwise flash the same error again for every remaining row.
        """
        if not datastore.watch_limit_reached():
            return False

        if not self.limit_reported:
            self.limit_reported = True
            flash(datastore.watch_limit_message(), 'error')

        return True


class import_url_list(Importer):
    """
    Imports a list, can be in <code>https://example.com tag1, tag2, last tag</code> format
    """
    def run(self,
            data,
            flash,
            datastore,
            processor=None
            ):

        urls = data.split("\n")
        good = 0
        now = time.time()

        if (len(urls) > 5000):
            flash(gettext("Importing 5,000 of the first URLs from your list, the rest can be imported again."))

        for idx, url in enumerate(urls):
            url = url.strip()
            if not len(url):
                continue

            tags = ""

            # 'tags' should be a csv list after the URL
            url, tags = split_url_and_tags(url)

            # Flask wtform validators wont work with basic auth, use validators package
            # Up to 5000 per batch so we dont flood the server
            # @todo validators.url will fail when you add your own IP etc
            if len(url) and 'http' in url.lower() and good < 5000:
                if self.watch_limit_hit(datastore, flash):
                    # Hand back every line we didn't get to (originals, tags included) so they
                    # land in the textarea to retry once there's room
                    self.remaining_data.extend(u.strip() for u in urls[idx:] if u.strip())
                    break

                extras = None
                if processor:
                    extras = {'processor': processor}
                new_uuid = datastore.add_watch(url=url.strip(), tag=tags, save_immediately=False, extras=extras)

                if new_uuid:
                    # Straight into the queue.
                    self.new_uuids.append(new_uuid)
                    good += 1
                    continue

            # Worked past the 'continue' above, append it to the bad list
            if self.remaining_data is None:
                self.remaining_data = []
            self.remaining_data.append(url)

        flash(gettext("{count} Imported from list in {duration}s, {skipped_count} Skipped.").format(count=good, duration=f"{time.time() - now:.2f}", skipped_count=len(self.remaining_data)))


class import_distill_io_json(Importer):
    def run(self,
            data,
            flash,
            datastore,
            ):

        import json
        good = 0
        now = time.time()
        self.new_uuids=[]

        # @todo Use JSONSchema like in the API to validate here.
        
        try:
            data = json.loads(data.strip())
        except json.decoder.JSONDecodeError:
            flash(gettext("Unable to read JSON file, was it broken?"), 'error')
            return

        if not data.get('data'):
            flash(gettext("JSON structure looks invalid, was it broken?"), 'error')
            return

        for d in data.get('data'):
            d_config = json.loads(d['config'])
            extras = {'title': d.get('name', None)}

            if len(d['uri']) and good < 5000:
                if self.watch_limit_hit(datastore, flash):
                    break

                try:
                    # @todo we only support CSS ones at the moment
                    if d_config['selections'][0]['frames'][0]['excludes'][0]['type'] == 'css':
                        extras['subtractive_selectors'] = d_config['selections'][0]['frames'][0]['excludes'][0]['expr']
                except KeyError:
                    pass
                except IndexError:
                    pass
                extras['include_filters'] = []
                try:
                    if d_config['selections'][0]['frames'][0]['includes'][0]['type'] == 'xpath':
                        extras['include_filters'].append('xpath:' + d_config['selections'][0]['frames'][0]['includes'][0]['expr'])
                    else:
                        extras['include_filters'].append(d_config['selections'][0]['frames'][0]['includes'][0]['expr'])
                except KeyError:
                    pass
                except IndexError:
                    pass

                new_uuid = datastore.add_watch(url=d['uri'].strip(),
                                               tag=",".join(d.get('tags', [])),
                                               extras=extras,
                                               save_immediately=False)

                if new_uuid:
                    # Straight into the queue.
                    self.new_uuids.append(new_uuid)
                    good += 1

        flash(gettext("{count} Imported from Distill.io in {duration}s, {skipped_count} Skipped.").format(count=len(self.new_uuids), duration=f"{time.time() - now:.2f}", skipped_count=len(self.remaining_data)))


class import_xlsx_wachete(Importer):

    def run(self,
            data,
            flash,
            datastore,
            ):

        good = 0
        now = time.time()
        self.new_uuids = []

        from openpyxl import load_workbook

        try:
            wb = load_workbook(data)
        except Exception as e:
            # @todo correct except
            flash(gettext("Unable to read export XLSX file, something wrong with the file?"), 'error')
            return

        for row_id, row in enumerate(wb.active.iter_rows(min_row=2), start=2):
            try:
                extras = {}
                data = {}
                for cell in row:
                    if not cell.value:
                        continue
                    column_title = wb.active.cell(row=1, column=cell.column).value.strip().lower()
                    data[column_title] = cell.value

                # Forced switch to webdriver/playwright/etc
                dynamic_wachet = str(data.get('dynamic wachet', '')).strip().lower()  # Convert bool to str to cover all cases
                # libreoffice and others can have it as =FALSE() =TRUE(), or bool(true)
                if 'true' in dynamic_wachet or dynamic_wachet == '1':
                    extras['fetch_backend'] = 'html_webdriver'
                elif 'false' in dynamic_wachet or dynamic_wachet == '0':
                    extras['fetch_backend'] = 'html_requests'

                if data.get('xpath'):
                    # @todo split by || ?
                    extras['include_filters'] = [data.get('xpath')]
                if data.get('name'):
                    extras['title'] = data.get('name').strip()
                if data.get('interval (min)'):
                    minutes = int(data.get('interval (min)'))
                    hours, minutes = divmod(minutes, 60)
                    days, hours = divmod(hours, 24)
                    weeks, days = divmod(days, 7)
                    extras['time_between_check'] = {'weeks': weeks, 'days': days, 'hours': hours, 'minutes': minutes, 'seconds': 0}

                # At minimum a URL is required.
                if data.get('url'):
                    try:
                        validate_url(data.get('url'))
                    except ValidationError as e:
                        logger.error(f">> Import URL error {data.get('url')} {str(e)}")
                        flash(gettext("Error processing row number {}, URL value was incorrect, row was skipped.").format(row_id), 'error')
                        # Don't bother processing anything else on this row
                        continue

                    if self.watch_limit_hit(datastore, flash):
                        break

                    new_uuid = datastore.add_watch(url=data['url'].strip(),
                                                   extras=extras,
                                                   tag=data.get('folder'),
                                                   save_immediately=False)
                    if new_uuid:
                        # Straight into the queue.
                        self.new_uuids.append(new_uuid)
                        good += 1
            except Exception as e:
                logger.error(e)
                flash(gettext("Error processing row number {}, check all cell data types are correct, row was skipped.").format(row_id), 'error')

        flash(gettext("{count} imported from Wachete .xlsx in {duration}s").format(count=len(self.new_uuids), duration=f"{time.time() - now:.2f}"))


class import_xlsx_custom(Importer):

    def run(self,
            data,
            flash,
            datastore,
            ):

        good = 0
        now = time.time()
        self.new_uuids = []

        from openpyxl import load_workbook

        try:
            wb = load_workbook(data)
        except Exception as e:
            # @todo correct except
            flash(gettext("Unable to read export XLSX file, something wrong with the file?"), 'error')
            return

        # @todo cehck atleast 2 rows, same in other method
        from changedetectionio.forms import validate_url
        row_i = 0

        try:
            for row_i, row in enumerate(wb.active.iter_rows(), start=1):
                url = None
                tags = None
                extras = {}

                for cell in row:
                    if not self.import_profile.get(cell.col_idx):
                        continue
                    if not cell.value:
                        continue

                    cell_map = self.import_profile.get(cell.col_idx)

                    cell_val = str(cell.value).strip()  # could be bool

                    if cell_map == 'url':
                        url = cell.value.strip()
                        try:
                            validate_url(url)
                        except ValidationError as e:
                            logger.error(f">> Import URL error {url} {str(e)}")
                            flash(gettext("Error processing row number {}, URL value was incorrect, row was skipped.").format(row_i), 'error')
                            # Don't bother processing anything else on this row
                            url = None
                            break
                    elif cell_map == 'tag':
                        tags = cell.value.strip()
                    elif cell_map == 'include_filters':
                        # @todo validate?
                        extras['include_filters'] = [cell.value.strip()]
                    elif cell_map == 'interval_minutes':
                        hours, minutes = divmod(int(cell_val), 60)
                        days, hours = divmod(hours, 24)
                        weeks, days = divmod(days, 7)
                        extras['time_between_check'] = {'weeks': weeks, 'days': days, 'hours': hours, 'minutes': minutes, 'seconds': 0}
                    else:
                        extras[cell_map] = cell_val

                # At minimum a URL is required.
                if url:
                    if self.watch_limit_hit(datastore, flash):
                        break

                    new_uuid = datastore.add_watch(url=url,
                                                   extras=extras,
                                                   tag=tags,
                                                   save_immediately=False)
                    if new_uuid:
                        # Straight into the queue.
                        self.new_uuids.append(new_uuid)
                        good += 1
        except Exception as e:
            logger.error(e)
            flash(gettext("Error processing row number {}, check all cell data types are correct, row was skipped.").format(row_i), 'error')

        flash(gettext("{count} imported from custom .xlsx in {duration}s").format(count=len(self.new_uuids), duration=f"{time.time() - now:.2f}"))