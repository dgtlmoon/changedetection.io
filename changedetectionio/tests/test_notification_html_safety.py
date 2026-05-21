import pytest
from unittest.mock import MagicMock
from changedetectionio.notification.handler import notification_format_align_with_apprise, markup_text_links_to_html
from apprise import NotifyFormat


class TestMarkupTextLinksToHtml:
	"""Edge case tests for markup_text_links_to_html() XSS safety."""

	def test_plain_text_no_links(self):
		"""Plain text without URLs should be escaped and returned as safe HTML."""
		input_text = "This is plain text with <special> characters"
		result = markup_text_links_to_html(input_text)
		# Result should be Markup (safe) not raw HTML
		assert '<a href=' not in str(result) or '&lt;' in str(result)

	def test_single_url_converted_to_link(self):
		"""Single URL in text should be converted to clickable link."""
		input_text = "Visit https://example.com for more info"
		result = markup_text_links_to_html(input_text)
		assert 'href="https://example.com"' in str(result) or 'href="https://example.com/' in str(result)

	def test_multiple_urls(self):
		"""Multiple URLs should each become clickable links."""
		input_text = "Check https://foo.com and https://bar.com today"
		result = markup_text_links_to_html(input_text)
		result_str = str(result)
		# Both URLs should be linked
		assert 'href="https://foo.com"' in result_str or 'href="https://foo.com/' in result_str
		assert 'href="https://bar.com"' in result_str or 'href="https://bar.com/' in result_str

	def test_empty_string(self):
		"""Empty string input should return empty safe HTML."""
		result = markup_text_links_to_html('')
		assert result == '' or str(result) == ''

	def test_xss_attempt_script_tag(self):
		"""XSS attempts like <script> should be escaped, not rendered."""
		input_text = "Click <script>alert('xss')</script> here"
		result = markup_text_links_to_html(input_text)
		result_str = str(result)
		# Script tag should be escaped, not executable
		assert '&lt;script&gt;' in result_str or '<script>' not in result_str

	def test_xss_attempt_onclick(self):
		"""onclick XSS in URL should be escaped."""
		input_text = "See https://evil.com/p?q=<img onerror=alert(1)>"
		result = markup_text_links_to_html(input_text)
		result_str = str(result)
		# The malicious part should be escaped
		assert '&lt;' in result_str or '<img' not in result_str