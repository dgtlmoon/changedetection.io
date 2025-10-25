#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_notification_diff

import unittest
import os

from changedetectionio import diff
from changedetectionio.diff import (
    REMOVED_PLACEMARKER_OPEN,
    REMOVED_PLACEMARKER_CLOSED,
    ADDED_PLACEMARKER_OPEN,
    ADDED_PLACEMARKER_CLOSED,
    CHANGED_PLACEMARKER_OPEN,
    CHANGED_PLACEMARKER_CLOSED,
    CHANGED_INTO_PLACEMARKER_OPEN,
    CHANGED_INTO_PLACEMARKER_CLOSED
)

# mostly
class TestDiffBuilder(unittest.TestCase):

    def test_expected_diff_output(self):
        base_dir = os.path.dirname(__file__)
        with open(base_dir + "/test-content/before.txt", 'r') as f:
            previous_version_file_contents = f.read()

        with open(base_dir + "/test-content/after.txt", 'r') as f:
            newest_version_file_contents = f.read()

        output = diff.render_diff(previous_version_file_contents=previous_version_file_contents,
                                  newest_version_file_contents=newest_version_file_contents)

        output = output.split("\n")

        # Check that placemarkers are present (they get replaced in apply_service_tweaks)
        self.assertTrue(any(CHANGED_PLACEMARKER_OPEN in line and 'ok' in line for line in output))
        self.assertTrue(any(CHANGED_INTO_PLACEMARKER_OPEN in line and 'xok' in line for line in output))
        self.assertTrue(any(CHANGED_INTO_PLACEMARKER_OPEN in line and 'next-x-ok' in line for line in output))
        self.assertTrue(any(ADDED_PLACEMARKER_OPEN in line and 'and something new' in line for line in output))

        with open(base_dir + "/test-content/after-2.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents)
        output = output.split("\n")
        self.assertTrue(any(REMOVED_PLACEMARKER_OPEN in line and 'for having learned computerese,' in line for line in output))
        self.assertTrue(any(REMOVED_PLACEMARKER_OPEN in line and 'I continue to examine bits, bytes and words' in line for line in output))

        #diff_removed
        with open(base_dir + "/test-content/before.txt", 'r') as f:
            previous_version_file_contents = f.read()

        with open(base_dir + "/test-content/after.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=False)
        output = output.split("\n")
        self.assertTrue(any(CHANGED_PLACEMARKER_OPEN in line and 'ok' in line for line in output))
        self.assertTrue(any(CHANGED_INTO_PLACEMARKER_OPEN in line and 'xok' in line for line in output))
        self.assertTrue(any(CHANGED_INTO_PLACEMARKER_OPEN in line and 'next-x-ok' in line for line in output))
        self.assertFalse(any(ADDED_PLACEMARKER_OPEN in line and 'and something new' in line for line in output))

        #diff_removed
        with open(base_dir + "/test-content/after-2.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=False)
        output = output.split("\n")
        self.assertTrue(any(REMOVED_PLACEMARKER_OPEN in line and 'for having learned computerese,' in line for line in output))
        self.assertTrue(any(REMOVED_PLACEMARKER_OPEN in line and 'I continue to examine bits, bytes and words' in line for line in output))

    def test_expected_diff_patch_output(self):
        base_dir = os.path.dirname(__file__)
        with open(base_dir + "/test-content/before.txt", 'r') as f:
            before = f.read()
        with open(base_dir + "/test-content/after.txt", 'r') as f:
            after = f.read()

        output = diff.render_diff(previous_version_file_contents=before,
                                  newest_version_file_contents=after,
                                  patch_format=True)
        output = output.split("\n")

        self.assertIn('-ok', output)
        self.assertIn('+xok', output)
        self.assertIn('+next-x-ok', output)
        self.assertIn('+and something new', output)

        # @todo test blocks of changed, blocks of added, blocks of removed

    def test_word_level_diff(self):
        """Test word-level diff functionality"""
        before = "The quick brown fox jumps over the lazy dog"
        after = "The fast brown cat jumps over the lazy dog"

        # Test with word_diff enabled
        output = diff.render_diff(before, after, include_equal=False, word_diff=True)
        # Should highlight only changed words, not entire line
        self.assertIn(f'{REMOVED_PLACEMARKER_OPEN}quick{REMOVED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{ADDED_PLACEMARKER_OPEN}fast{ADDED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{REMOVED_PLACEMARKER_OPEN}fox{REMOVED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{ADDED_PLACEMARKER_OPEN}cat{ADDED_PLACEMARKER_CLOSED}', output)
        # Unchanged words should appear without markers
        self.assertIn('brown', output)
        self.assertIn('jumps', output)

        # Test with word_diff disabled (line-level)
        output = diff.render_diff(before, after, include_equal=False, word_diff=False)
        # Should show full line changes
        self.assertIn(f'{CHANGED_PLACEMARKER_OPEN}The quick brown fox jumps over the lazy dog{CHANGED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{CHANGED_INTO_PLACEMARKER_OPEN}The fast brown cat jumps over the lazy dog{CHANGED_INTO_PLACEMARKER_CLOSED}', output)

    def test_word_level_diff_html(self):
        """Test word-level diff with HTML coloring"""
        before = "110 points by user"
        after = "111 points by user"

        output = diff.render_diff(before, after, include_equal=False, word_diff=True, html_colour=True)

        # With html_colour=True and nested highlighting, placemarkers wrap content with inner HTML spans
        # The inner HTML uses REMOVED_INNER_STYLE and ADDED_INNER_STYLE for character-level highlighting
        self.assertIn(CHANGED_PLACEMARKER_OPEN, output)
        self.assertIn(CHANGED_INTO_PLACEMARKER_OPEN, output)
        # Unchanged text should not be wrapped in spans
        self.assertIn('points by user', output)
        self.assertIn('11', output)  # Common prefix is unchanged

    def test_context_lines(self):
        """Test context_lines parameter"""
        before = """Line 1
Line 2
Line 3
Old line
Line 5
Line 6
Line 7
Another old
Line 9
Line 10"""

        after = """Line 1
Line 2
Line 3
New line
Line 5
Line 6
Line 7
Another new
Line 9
Line 10"""

        # Test with no context
        output = diff.render_diff(before, after, include_equal=False, context_lines=0, word_diff=True)
        lines = output.split("\n")
        # Should only show changed lines
        self.assertEqual(len([l for l in lines if l.strip()]), 2)  # Two changed lines
        self.assertIn(f'{REMOVED_PLACEMARKER_OPEN}Old{REMOVED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{ADDED_PLACEMARKER_OPEN}New{ADDED_PLACEMARKER_CLOSED}', output)

        # Test with 1 line of context
        output = diff.render_diff(before, after, include_equal=False, context_lines=1, word_diff=True)
        lines = [l for l in output.split("\n") if l.strip()]
        # Should show changed lines + 1 line before and after each
        self.assertIn('Line 3', output)  # 1 line before first change
        self.assertIn('Line 5', output)  # 1 line after first change
        self.assertIn('Line 7', output)  # 1 line before second change
        self.assertIn('Line 9', output)  # 1 line after second change
        self.assertGreater(len(lines), 2)  # More than just the changed lines

        # Test with 2 lines of context
        output = diff.render_diff(before, after, include_equal=False, context_lines=2, word_diff=True)
        lines = [l for l in output.split("\n") if l.strip()]
        # Should show changed lines + 2 lines before and after each
        self.assertIn('Line 2', output)  # 2 lines before first change
        self.assertIn('Line 6', output)  # 2 lines after first change
        self.assertGreater(len(lines), 6)  # Even more context

    def test_context_lines_with_include_equal(self):
        """Test that context_lines is ignored when include_equal=True"""
        before = """Line 1
Line 2
Changed line
Line 4"""

        after = """Line 1
Line 2
Modified line
Line 4"""

        # With include_equal=True, context_lines should be ignored
        output_with_context = diff.render_diff(before, after, include_equal=True, context_lines=1)
        output_without_context = diff.render_diff(before, after, include_equal=True, context_lines=0)

        # Both should show all lines
        self.assertIn('Line 1', output_with_context)
        self.assertIn('Line 4', output_with_context)
        self.assertIn('Line 1', output_without_context)
        self.assertIn('Line 4', output_without_context)

    def test_case_insensitive_comparison(self):
        """Test case-insensitive diff comparison"""
        before = "The Quick Brown Fox"
        after = "The QUICK brown FOX"

        # With case-sensitive (default), should detect changes
        output = diff.render_diff(before, after, include_equal=False, case_insensitive=False, word_diff=False)
        self.assertIn(f'{CHANGED_PLACEMARKER_OPEN}The Quick Brown Fox{CHANGED_PLACEMARKER_CLOSED}', output)

        # With case-insensitive, should detect no changes
        output = diff.render_diff(before, after, include_equal=False, case_insensitive=True)
        # Should be empty or minimal since texts are equal when ignoring case
        lines = [l for l in output.split("\n") if l.strip()]
        self.assertEqual(len(lines), 0, "Case-insensitive comparison should find no differences")

    def test_case_insensitive_with_real_changes(self):
        """Test case-insensitive comparison with actual content differences"""
        before = "Hello World\nGoodbye WORLD to all my friends and family"
        after = "HELLO world\nGoodbye Friend to all my friends and family"

        # Case-insensitive should only detect the second line change
        output = diff.render_diff(before, after, include_equal=False, case_insensitive=True, word_diff=True)

        # First line should not appear (same when ignoring case)
        self.assertNotIn('Hello', output)
        self.assertNotIn('HELLO', output)

        # Second line should show the word change
        self.assertIn(f'{REMOVED_PLACEMARKER_OPEN}WORLD{REMOVED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{ADDED_PLACEMARKER_OPEN}Friend{ADDED_PLACEMARKER_CLOSED}', output)

    def test_case_insensitive_html_output(self):
        """Test case-insensitive comparison with HTML output"""
        before = "Price: $100"
        after = "PRICE: $200"

        # Case-insensitive should only highlight the price change
        output = diff.render_diff(before, after, include_equal=False, case_insensitive=True, word_diff=True, html_colour=True)

        # With html_colour=True, nested highlighting is used with placemarkers
        # Inner spans show the changes within the line
        self.assertIn(CHANGED_PLACEMARKER_OPEN, output)
        self.assertIn(CHANGED_INTO_PLACEMARKER_OPEN, output)
        self.assertIn('00', output)  # Common suffix unchanged

    def test_ignore_junk_word_diff_enabled(self):
        """Test ignore_junk with word_diff=True"""
        before = "The quick  brown   fox"
        after = "The quick brown fox"

        # Without ignore_junk, should detect whitespace changes
        output = diff.render_diff(before, after, include_equal=False, word_diff=True, ignore_junk=False)
        # Should show some difference (whitespace changes)
        self.assertTrue(len(output.strip()) > 0, "Should detect whitespace changes when ignore_junk=False")

        # With ignore_junk, should ignore whitespace-only changes
        output = diff.render_diff(before, after, include_equal=False, word_diff=True, ignore_junk=True)
        lines = [l for l in output.split("\n") if l.strip()]
        self.assertEqual(len(lines), 0, "Should ignore whitespace-only changes when ignore_junk=True")

    def test_ignore_junk_word_diff_disabled(self):
        """Test ignore_junk with word_diff=False"""
        before = "Hello  World"
        after = "Hello World"

        # Without ignore_junk, should detect line change
        output = diff.render_diff(before, after, include_equal=False, word_diff=False, ignore_junk=False)
        self.assertIn(f'{CHANGED_PLACEMARKER_OPEN}Hello  World{CHANGED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{CHANGED_INTO_PLACEMARKER_OPEN}Hello World{CHANGED_INTO_PLACEMARKER_CLOSED}', output)

        # With ignore_junk enabled and word_diff disabled
        # When ignore_junk is enabled, whitespace is normalized at line level so lines match
        output = diff.render_diff(before, after, include_equal=False, word_diff=False, ignore_junk=True)
        # Lines should be treated as equal
        lines = [l for l in output.split("\n") if l.strip()]
        self.assertEqual(len(lines), 0, "Should ignore whitespace differences at line level")

    def test_ignore_junk_with_real_changes(self):
        """Test ignore_junk doesn't ignore actual word changes"""
        before = "The  quick   brown  fox"
        after = "The quick brown cat"

        output = diff.render_diff(before, after, include_equal=False, word_diff=True, ignore_junk=True)

        # Should still detect the word change (fox -> cat)
        self.assertIn(f'{REMOVED_PLACEMARKER_OPEN}fox{REMOVED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{ADDED_PLACEMARKER_OPEN}cat{ADDED_PLACEMARKER_CLOSED}', output)
        # But shouldn't highlight whitespace differences

    def test_ignore_junk_tabs_vs_spaces(self):
        """Test ignore_junk treats tabs and spaces as equivalent"""
        before = "Column1\tColumn2\tColumn3"
        after = "Column1    Column2    Column3"

        # Without ignore_junk, should detect difference
        output = diff.render_diff(before, after, include_equal=False, word_diff=True, ignore_junk=False)
        self.assertTrue(len(output.strip()) > 0, "Should detect tab vs space differences")

        # With ignore_junk, should ignore tab/space differences
        output = diff.render_diff(before, after, include_equal=False, word_diff=True, ignore_junk=True)
        lines = [l for l in output.split("\n") if l.strip()]
        self.assertEqual(len(lines), 0, "Should ignore tab vs space differences when ignore_junk=True")

    def test_ignore_junk_html_output(self):
        """Test ignore_junk with HTML coloring"""
        before = "Value:  100  points"
        after = "Value: 200 points"

        output = diff.render_diff(before, after, include_equal=False, word_diff=True, html_colour=True, ignore_junk=True)

        # Should only highlight the actual value change
        self.assertIn('100', output)
        self.assertIn('200', output)
        self.assertIn('background-color', output)
        # Should not create separate spans for whitespace changes

    def test_ignore_junk_case_insensitive_combination(self):
        """Test ignore_junk combined with case_insensitive"""
        before = "The  QUICK   Brown  Fox jumps over the lazy dog every day"
        after = "The quick brown FOX jumps over the lazy dog every day"

        # Both enabled: should ignore case and whitespace
        output = diff.render_diff(before, after, include_equal=False, word_diff=True,
                                 case_insensitive=True, ignore_junk=True)
        lines = [l for l in output.split("\n") if l.strip()]
        self.assertEqual(len(lines), 0, "Should ignore both case and whitespace differences")

        # Only case_insensitive: should detect whitespace changes
        output = diff.render_diff(before, after, include_equal=False, word_diff=True,
                                 case_insensitive=True, ignore_junk=False)
        self.assertTrue(len(output.strip()) > 0, "Should detect whitespace changes")

        # Only ignore_junk: should detect case changes
        output = diff.render_diff(before, after, include_equal=False, word_diff=True,
                                 case_insensitive=False, ignore_junk=True)
        # Should detect case differences
        self.assertIn('QUICK', output)
        self.assertIn('quick', output)
        self.assertIn('Brown', output)
        self.assertIn('brown', output)
        # Should show changes (though may be grouped together)
        # Check that placemarkers appear in the output
        self.assertTrue(REMOVED_PLACEMARKER_OPEN in output, "Should show removed text")
        self.assertTrue(ADDED_PLACEMARKER_OPEN in output, "Should show added text")

    def test_ignore_junk_multiline(self):
        """Test ignore_junk with multiple lines"""
        before = """Line 1  with  spaces
Line 2 unchanged
Line 3  with  tabs	and  spaces"""

        after = """Line 1 with spaces
Line 2 unchanged
Line 3 with tabs and spaces"""

        # With ignore_junk, should only show unchanged line when include_equal=True
        output = diff.render_diff(before, after, include_equal=False, word_diff=True, ignore_junk=True)
        lines = [l for l in output.split("\n") if l.strip()]
        # Should be empty since only whitespace changed
        self.assertEqual(len(lines), 0, "Should ignore whitespace changes across multiple lines")

        # Verify Line 2 is not shown as changed
        self.assertNotIn('[-Line 2-]', output)
        self.assertNotIn('[+Line 2+]', output)

if __name__ == '__main__':
    unittest.main()
