"""Tests for bulk operations functionality - CSV import/export."""

import csv
import io
import time


class TestBulkOperationsPage:
    """Test bulk operations page access and rendering."""

    def test_bulk_operations_page_loads(self, client, live_server):
        """Test that bulk operations page loads successfully."""
        response = client.get(
            url='/bulk/bulk',
            follow_redirects=True
        )
        assert response.status_code == 200
        assert b'Bulk Operations' in response.data or b'Import CSV' in response.data

    def test_bulk_operations_shows_stats(self, client, live_server):
        """Test that bulk operations page shows statistics."""
        response = client.get(
            url='/bulk/bulk',
            follow_redirects=True
        )
        assert response.status_code == 200
        # Should show total events and tags count
        assert b'Total Events' in response.data or b'total_watches' in response.data.lower()


class TestCSVTemplate:
    """Test CSV template download."""

    def test_csv_template_download(self, client, live_server):
        """Test downloading CSV template."""
        response = client.get(
            url='/bulk/bulk/template/csv',
            follow_redirects=True
        )
        assert response.status_code == 200
        assert response.content_type == 'text/csv; charset=utf-8'

        # Check content disposition header
        assert 'attachment' in response.headers.get('Content-Disposition', '')
        assert 'events_import_template.csv' in response.headers.get('Content-Disposition', '')

        # Parse CSV content
        content = response.data.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)

        # Check header row
        assert len(rows) >= 1
        header = rows[0]
        assert 'url' in header
        assert 'tags' in header
        assert 'event_name' in header
        assert 'artist' in header
        assert 'venue' in header


class TestCSVExport:
    """Test CSV export functionality."""

    def test_export_all_events_csv(self, client, live_server):
        """Test exporting all events to CSV."""
        # First add a watch
        test_url = 'https://example.com/export-test'
        response = client.post(
            url='/form/add/quickwatch',
            data={'url': test_url, 'tags': '', 'processor': 'text_json_diff'},
            follow_redirects=True
        )
        assert response.status_code == 200

        # Wait for the watch to be added
        time.sleep(0.5)

        # Export all events
        response = client.get(
            url='/bulk/bulk/export/csv',
            follow_redirects=True
        )
        assert response.status_code == 200
        assert response.content_type == 'text/csv; charset=utf-8'

        # Parse and verify CSV
        content = response.data.decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)

        # Should have at least one row
        assert len(rows) >= 1

        # Find our test URL
        found = False
        for row in rows:
            if test_url in row.get('url', ''):
                found = True
                break
        assert found, f"Expected to find {test_url} in export"

    def test_export_csv_headers(self, client, live_server):
        """Test that CSV export has correct headers."""
        response = client.get(
            url='/bulk/bulk/export/csv',
            follow_redirects=True
        )
        assert response.status_code == 200

        content = response.data.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        header = next(reader)

        expected_headers = [
            'url', 'tags', 'event_name', 'artist', 'venue',
            'event_date', 'event_time', 'processor',
            'last_checked', 'last_changed', 'paused'
        ]
        assert header == expected_headers

    def test_export_selected_events(self, client, live_server):
        """Test exporting selected events to CSV."""
        # First add some watches
        test_url_1 = 'https://example.com/export-selected-1'
        test_url_2 = 'https://example.com/export-selected-2'

        for url in [test_url_1, test_url_2]:
            client.post(
                url='/form/add/quickwatch',
                data={'url': url, 'tags': '', 'processor': 'text_json_diff'},
                follow_redirects=True
            )

        time.sleep(0.5)

        # Get the watch list to find UUIDs
        response = client.get(url='/', follow_redirects=True)

        # Extract UUIDs from the page (they're in the table rows)
        # For testing, we'll export with empty selection first
        response = client.post(
            url='/bulk/bulk/export/selected',
            data={'uuids': []},
            follow_redirects=True
        )
        # Should redirect back with flash message when no selection
        assert response.status_code == 200


class TestCSVImport:
    """Test CSV import functionality."""

    def test_import_csv_no_file(self, client, live_server):
        """Test import with no file provided."""
        response = client.post(
            url='/bulk/bulk/import/csv',
            data={},
            follow_redirects=True
        )
        assert response.status_code == 200
        # Should show error message
        assert b'No CSV file' in response.data or b'error' in response.data.lower()

    def test_import_csv_invalid_file_type(self, client, live_server):
        """Test import with non-CSV file."""
        # Create a fake non-CSV file
        data = {'csv_file': (io.BytesIO(b'test content'), 'test.txt')}
        response = client.post(
            url='/bulk/bulk/import/csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert response.status_code == 200
        # Should show error about CSV format
        assert b'CSV' in response.data or b'error' in response.data.lower()

    def test_import_csv_valid_file(self, client, live_server):
        """Test importing a valid CSV file."""
        # Create a valid CSV content
        csv_content = """url,tags,event_name,artist,venue
https://example.com/import-test-1,test-tag,Test Event 1,Test Artist,Test Venue
https://example.com/import-test-2,tag1,Test Event 2,Artist 2,Venue 2
"""
        csv_file = io.BytesIO(csv_content.encode('utf-8'))

        data = {'csv_file': (csv_file, 'test_import.csv')}
        response = client.post(
            url='/bulk/bulk/import/csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert response.status_code == 200
        # Should show success message
        assert b'imported' in response.data.lower()

    def test_import_csv_with_invalid_url(self, client, live_server):
        """Test importing CSV with invalid URL."""
        csv_content = """url,tags,event_name,artist,venue
not-a-valid-url,test-tag,Test Event,Test Artist,Test Venue
"""
        csv_file = io.BytesIO(csv_content.encode('utf-8'))

        data = {'csv_file': (csv_file, 'test_import.csv')}
        response = client.post(
            url='/bulk/bulk/import/csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert response.status_code == 200
        # Should show skipped or error message
        assert b'skipped' in response.data.lower() or b'invalid' in response.data.lower()

    def test_import_csv_empty_rows(self, client, live_server):
        """Test importing CSV with empty URL rows."""
        csv_content = """url,tags,event_name,artist,venue
,test-tag,Test Event,Test Artist,Test Venue
https://example.com/valid-import,tag,Valid Event,Artist,Venue
"""
        csv_file = io.BytesIO(csv_content.encode('utf-8'))

        data = {'csv_file': (csv_file, 'test_import.csv')}
        response = client.post(
            url='/bulk/bulk/import/csv',
            data=data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        assert response.status_code == 200
        # Should import valid row, skip empty
        assert b'imported' in response.data.lower()


class TestBulkOperationsExisting:
    """Test that existing bulk operations still work."""

    def test_bulk_pause_works(self, client, live_server):
        """Test bulk pause functionality exists."""
        # Add a test watch
        test_url = 'https://example.com/bulk-pause-test'
        client.post(
            url='/form/add/quickwatch',
            data={'url': test_url, 'tags': '', 'processor': 'text_json_diff'},
            follow_redirects=True
        )
        time.sleep(0.5)

        # Check the watch list page has pause button
        response = client.get(url='/', follow_redirects=True)
        assert b'Pause' in response.data

    def test_bulk_delete_works(self, client, live_server):
        """Test bulk delete button exists."""
        response = client.get(url='/', follow_redirects=True)
        assert b'Delete' in response.data

    def test_bulk_assign_tag_works(self, client, live_server):
        """Test bulk assign tag button exists."""
        response = client.get(url='/', follow_redirects=True)
        # The tag button text
        assert b'Tag' in response.data

    def test_checkbox_selection_exists(self, client, live_server):
        """Test checkbox selection exists in watch list."""
        # Add a test watch
        test_url = 'https://example.com/checkbox-test'
        client.post(
            url='/form/add/quickwatch',
            data={'url': test_url, 'tags': '', 'processor': 'text_json_diff'},
            follow_redirects=True
        )
        time.sleep(0.5)

        response = client.get(url='/', follow_redirects=True)
        # Should have checkboxes
        assert b'type="checkbox"' in response.data
        # Should have check-all checkbox
        assert b'check-all' in response.data


class TestExportSelectedButton:
    """Test the Export CSV button in bulk operations."""

    def test_export_button_exists(self, client, live_server):
        """Test that Export CSV button exists in watch list."""
        # Add a test watch
        test_url = 'https://example.com/export-btn-test'
        client.post(
            url='/form/add/quickwatch',
            data={'url': test_url, 'tags': '', 'processor': 'text_json_diff'},
            follow_redirects=True
        )
        time.sleep(0.5)

        response = client.get(url='/', follow_redirects=True)
        # Should have export CSV button
        assert b'Export CSV' in response.data


class TestMenuLink:
    """Test bulk operations menu link."""

    def test_bulk_ops_menu_link_exists(self, client, live_server):
        """Test that BULK OPS menu link exists."""
        response = client.get(url='/', follow_redirects=True)
        assert b'BULK OPS' in response.data or b'bulk' in response.data.lower()
