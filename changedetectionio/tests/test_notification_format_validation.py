import pytest
from changedetectionio.notification.handler import notification_format_align_with_apprise
from apprise import NotifyFormat


class TestNotificationFormatValidation:
	"""
	Tests for notification_format_align_with_apprise() edge cases.
	Validates the function handles format strings correctly per issue #4119.
	"""

	def test_empty_format_returns_text(self):
		"""Empty string should return TEXT (default fallback)."""
		result = notification_format_align_with_apprise('')
		assert result == NotifyFormat.TEXT.value

	def test_none_format_returns_text(self):
		"""None should return TEXT (default fallback)."""
		result = notification_format_align_with_apprise(None)
		assert result == NotifyFormat.TEXT.value

	def test_htmlcolor_normalizes_to_html(self):
		"""htmlcolor format (changedetection default) should normalize to HTML for apprise."""
		result = notification_format_align_with_apprise('htmlcolor')
		assert result == NotifyFormat.HTML.value

	def test_html_normalizes_to_html(self):
		"""Explicit html format should remain HTML."""
		result = notification_format_align_with_apprise('html')
		assert result == NotifyFormat.HTML.value

	def test_text_normalizes_to_text(self):
		"""text format should remain TEXT."""
		result = notification_format_align_with_apprise('text')
		assert result == NotifyFormat.TEXT.value

	def test_markdown_normalizes_to_markdown(self):
		"""markdown format should normalize to MARKDOWN for apprise."""
		result = notification_format_align_with_apprise('markdown')
		assert result == NotifyFormat.MARKDOWN.value

	def test_unknown_format_defaults_to_text(self):
		"""Unknown format strings should fallback to TEXT."""
		result = notification_format_align_with_apprise('unknownformat')
		assert result == NotifyFormat.TEXT.value

	def test_case_insensitive_html(self):
		"""Format matching should be case-insensitive for the prefix check."""
		result = notification_format_align_with_apprise('HTML')
		assert result == NotifyFormat.HTML.value

	def test_case_insensitive_text(self):
		"""Format matching should be case-insensitive."""
		result = notification_format_align_with_apprise('TEXT')
		assert result == NotifyFormat.TEXT.value

	def test_system_default_marker_uses_text(self):
		"""USE_SYSTEM_DEFAULT sentinel value should fallback to TEXT."""
		from changedetectionio.model import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
		result = notification_format_align_with_apprise(USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH)
		# The sentinel is not a valid format for apprise, so it defaults to TEXT
		assert result == NotifyFormat.TEXT.value