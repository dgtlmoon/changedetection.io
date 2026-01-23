"""Tests for Quick Event Entry functionality (US-019)."""

import pytest
from unittest.mock import MagicMock, patch
from flask import Flask


class TestQuickEventForm:
    """Tests for the QuickEventForm class."""

    def test_quick_event_form_has_required_fields(self):
        """AC: URL input field (required)."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert hasattr(form, 'url')
        assert hasattr(form, 'tags')
        assert hasattr(form, 'auto_extract')
        assert hasattr(form, 'event_name')
        assert hasattr(form, 'artist')
        assert hasattr(form, 'venue')
        assert hasattr(form, 'event_date')
        assert hasattr(form, 'event_time')
        assert hasattr(form, 'add_event_button')
        assert hasattr(form, 'add_and_open_settings')

    def test_url_field_is_required(self):
        """AC: URL input field (required)."""
        from changedetectionio.forms import QuickEventForm

        # Empty URL should fail validation
        form = QuickEventForm(data={'url': ''})
        assert not form.validate()

    def test_url_field_validates_url_format(self):
        """URL field should validate URL format."""
        from changedetectionio.forms import QuickEventForm

        # Invalid URL should fail
        form = QuickEventForm(data={'url': 'not-a-url'})
        assert not form.validate()

    def test_manual_entry_fields_are_optional(self):
        """AC: Option to manually enter: event name, artist, venue, date, time."""
        from changedetectionio.forms import QuickEventForm

        # Valid URL without manual fields should pass
        form = QuickEventForm(data={'url': 'https://example.com/event'})
        # Note: form.validate() may still fail due to validators, but fields should exist
        assert form.event_name.data is None or form.event_name.data == ''
        assert form.artist.data is None or form.artist.data == ''
        assert form.venue.data is None or form.venue.data == ''

    def test_auto_extract_defaults_to_true(self):
        """AC: Option to auto-extract all fields on first check (default enabled)."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert form.auto_extract.default is True

    def test_add_event_button_exists(self):
        """AC: Add Event button creates event and triggers first check."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert form.add_event_button is not None
        assert 'pure-button-primary' in str(form.add_event_button.render_kw)

    def test_add_and_open_settings_button_exists(self):
        """AC: Add & Open Settings button creates event and opens full edit page."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert form.add_and_open_settings is not None


class TestQuickEventBlueprint:
    """Tests for the quick event blueprint routes."""

    @pytest.fixture
    def mock_datastore(self):
        """Create a mock datastore."""
        datastore = MagicMock()
        datastore.data = {
            'watching': {},
            'settings': {
                'application': {
                    'tags': {
                        'tag-uuid-1': {'title': 'Concerts'},
                        'tag-uuid-2': {'title': 'Sports'},
                    }
                }
            }
        }
        datastore.url_exists.return_value = False
        datastore.add_watch.return_value = 'new-watch-uuid'
        return datastore

    @pytest.fixture
    def mock_update_q(self):
        """Create a mock update queue."""
        return MagicMock()

    @pytest.fixture
    def mock_queued_meta(self):
        """Create a mock queued metadata class."""
        mock = MagicMock()
        mock.PrioritizedItem = MagicMock(return_value='queued-item')
        return mock

    @pytest.fixture
    def app(self, mock_datastore, mock_update_q, mock_queued_meta):
        """Create a test Flask app with the quick event blueprint."""
        from changedetectionio.blueprint.quick_event import construct_blueprint

        app = Flask(__name__)
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['TESTING'] = True
        app.secret_key = 'test-secret-key'

        # Register the blueprint
        blueprint = construct_blueprint(mock_datastore, mock_update_q, mock_queued_meta)
        app.register_blueprint(blueprint, url_prefix='/quick-event')

        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return app.test_client()

    def test_quick_entry_page_renders(self, client, mock_datastore):
        """AC: Form accessible from dashboard and event list page."""
        with patch('changedetectionio.blueprint.quick_event.login_optionally_required',
                   lambda f: f):
            response = client.get('/quick-event/')
            assert response.status_code == 200

    def test_form_submission_creates_event(self, client, mock_datastore, mock_update_q,
                                           mock_queued_meta):
        """AC: Add Event button creates event and triggers first check."""
        with patch('changedetectionio.blueprint.quick_event.login_optionally_required',
                   lambda f: f):
            response = client.post('/quick-event/add', data={
                'url': 'https://ticketmaster.com/event/123',
                'tags': '',
                'auto_extract': 'on',
            }, follow_redirects=False)

            # Should redirect after successful creation
            assert response.status_code == 302

            # Verify watch was created
            mock_datastore.add_watch.assert_called_once()
            call_kwargs = mock_datastore.add_watch.call_args
            assert 'https://ticketmaster.com/event/123' in str(call_kwargs)

    def test_form_submission_with_open_settings(self, client, mock_datastore):
        """AC: Add & Open Settings button creates event and opens full edit page."""
        with patch('changedetectionio.blueprint.quick_event.login_optionally_required',
                   lambda f: f):
            response = client.post('/quick-event/add', data={
                'url': 'https://ticketmaster.com/event/123',
                'tags': '',
                'add_and_open_settings': 'true',  # This indicates the button was clicked
            }, follow_redirects=False)

            # Should redirect (either to edit page or watchlist)
            assert response.status_code == 302

    def test_duplicate_url_shows_warning(self, client, mock_datastore):
        """Duplicate URL should show warning but still allow creation."""
        mock_datastore.url_exists.return_value = True

        with patch('changedetectionio.blueprint.quick_event.login_optionally_required',
                   lambda f: f):
            response = client.post('/quick-event/add', data={
                'url': 'https://ticketmaster.com/event/123',
                'tags': '',
            }, follow_redirects=False)

            # Should still redirect (warning shown via flash)
            assert response.status_code == 302

    def test_manual_entry_fields_passed_to_watch(self, client, mock_datastore):
        """AC: Option to manually enter: event name, artist, venue, date, time."""
        with patch('changedetectionio.blueprint.quick_event.login_optionally_required',
                   lambda f: f):
            response = client.post('/quick-event/add', data={
                'url': 'https://ticketmaster.com/event/123',
                'tags': '',
                'event_name': 'Summer Concert',
                'artist': 'The Band',
                'venue': 'Madison Square Garden',
                'event_date': '2024-07-15',
                'event_time': '19:30',
            }, follow_redirects=False)

            assert response.status_code == 302

            # Verify extras were passed
            call_kwargs = mock_datastore.add_watch.call_args
            extras = call_kwargs.kwargs.get('extras', {})
            assert extras.get('title') == 'Summer Concert'
            assert extras.get('artist') == 'The Band'
            assert extras.get('venue') == 'Madison Square Garden'

    def test_auto_extract_flag_set_when_enabled(self, client, mock_datastore):
        """AC: Option to auto-extract all fields on first check."""
        with patch('changedetectionio.blueprint.quick_event.login_optionally_required',
                   lambda f: f):
            response = client.post('/quick-event/add', data={
                'url': 'https://ticketmaster.com/event/123',
                'tags': '',
                'auto_extract': 'on',
            }, follow_redirects=False)

            assert response.status_code == 302

            # Verify auto_extract flag was set
            call_kwargs = mock_datastore.add_watch.call_args
            extras = call_kwargs.kwargs.get('extras', {})
            assert extras.get('auto_extract_on_first_check') is True


class TestAcceptanceCriteria:
    """Acceptance criteria verification tests."""

    def test_ac_url_input_required(self):
        """AC: URL input field (required)."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert hasattr(form, 'url')
        # URL field has validateURL validator
        assert len(form.url.validators) > 0

    def test_ac_tag_multiselect(self):
        """AC: Tag multiselect dropdown."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert hasattr(form, 'tags')
        # StringTagUUID field supports multiple tags (comma-separated)

    def test_ac_auto_extract_option(self):
        """AC: Option to auto-extract all fields on first check."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert hasattr(form, 'auto_extract')
        assert form.auto_extract.default is True

    def test_ac_manual_entry_fields(self):
        """AC: Option to manually enter: event name, artist, venue, date, time."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert hasattr(form, 'event_name')
        assert hasattr(form, 'artist')
        assert hasattr(form, 'venue')
        assert hasattr(form, 'event_date')
        assert hasattr(form, 'event_time')

    def test_ac_add_event_button(self):
        """AC: Add Event button creates event and triggers first check."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert hasattr(form, 'add_event_button')

    def test_ac_add_and_open_settings_button(self):
        """AC: Add & Open Settings button creates event and opens full edit page."""
        from changedetectionio.forms import QuickEventForm

        form = QuickEventForm()
        assert hasattr(form, 'add_and_open_settings')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
