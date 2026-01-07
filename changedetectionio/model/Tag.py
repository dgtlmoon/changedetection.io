import fnmatch

from changedetectionio.model import watch_base


class model(watch_base):

    def __init__(self, *arg, **kw):
        super().__init__(*arg, **kw)

        self['overrides_watch'] = kw.get('default', {}).get('overrides_watch')
        self['url_match_pattern'] = kw.get('default', {}).get('url_match_pattern', '')

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']

    def matches_url(self, url):
        """
        Check if a URL matches this tag's url_match_pattern.
        Supports wildcard patterns (using * and ?) and substring matching.

        Args:
            url: The URL to check against the pattern

        Returns:
            bool: True if the URL matches the pattern, False otherwise
        """
        pattern = self.get('url_match_pattern', '').strip()
        if not pattern:
            return False

        url_lower = url.lower()
        pattern_lower = pattern.lower()

        # If pattern contains wildcards, use fnmatch
        if '*' in pattern or '?' in pattern:
            return fnmatch.fnmatch(url_lower, pattern_lower)

        # Otherwise, do substring matching
        return pattern_lower in url_lower
