#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_notification_diff

import unittest
import os

from changedetectionio import diff

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


        self.assertIn('(changed) ok', output)
        self.assertIn('(into) xok', output)
        self.assertIn('(into) next-x-ok', output)
        self.assertIn('(added) and something new', output)

        with open(base_dir + "/test-content/after-2.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents)
        output = output.split("\n")
        self.assertIn('(removed) for having learned computerese,', output)
        self.assertIn('(removed) I continue to examine bits, bytes and words', output)

        #diff_removed
        with open(base_dir + "/test-content/before.txt", 'r') as f:
            previous_version_file_contents = f.read()

        with open(base_dir + "/test-content/after.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=False)
        output = output.split("\n")
        self.assertIn('(changed) ok', output)
        self.assertIn('(into) xok', output)
        self.assertIn('(into) next-x-ok', output)
        self.assertNotIn('(added) and something new', output)

        #diff_removed
        with open(base_dir + "/test-content/after-2.txt", 'r') as f:
            newest_version_file_contents = f.read()
        output = diff.render_diff(previous_version_file_contents, newest_version_file_contents, include_equal=False, include_removed=True, include_added=False)
        output = output.split("\n")
        self.assertIn('(removed) for having learned computerese,', output)
        self.assertIn('(removed) I continue to examine bits, bytes and words', output)

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
        self.assertIn('[-quick-]', output)
        self.assertIn('[+fast+]', output)
        self.assertIn('[-fox-]', output)
        self.assertIn('[+cat+]', output)
        # Unchanged words should appear without markers
        self.assertIn('brown', output)
        self.assertIn('jumps', output)

        # Test with word_diff disabled (line-level)
        output = diff.render_diff(before, after, include_equal=False, word_diff=False)
        # Should show full line changes
        self.assertIn('(changed)', output)
        self.assertIn('(into)', output)

    def test_word_level_diff_html(self):
        """Test word-level diff with HTML coloring"""
        before = "110 points by user"
        after = "111 points by user"

        output = diff.render_diff(before, after, include_equal=False, word_diff=True, html_colour=True)

        # Should highlight only the changed word (110 -> 111)
        self.assertIn('<span style="background-color: #fadad7; color: #b30000;" title="Removed">110</span>', output)
        self.assertIn('<span style="background-color: #eaf2c2; color: #406619;" title="Added">111</span>', output)
        # Unchanged text should not be wrapped in spans
        self.assertIn('points by user', output)

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
        self.assertIn('[-Old-]', output)
        self.assertIn('[+New+]', output)

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
        self.assertIn('(changed)', output)

        # With case-insensitive, should detect no changes
        output = diff.render_diff(before, after, include_equal=False, case_insensitive=True)
        # Should be empty or minimal since texts are equal when ignoring case
        lines = [l for l in output.split("\n") if l.strip()]
        self.assertEqual(len(lines), 0, "Case-insensitive comparison should find no differences")

    def test_case_insensitive_with_real_changes(self):
        """Test case-insensitive comparison with actual content differences"""
        before = "Hello World\nGoodbye WORLD"
        after = "HELLO world\nGoodbye Friend"

        # Case-insensitive should only detect the second line change
        output = diff.render_diff(before, after, include_equal=False, case_insensitive=True, word_diff=True)

        # First line should not appear (same when ignoring case)
        self.assertNotIn('Hello', output)
        self.assertNotIn('HELLO', output)

        # Second line should show the word change
        self.assertIn('[-WORLD-]', output)
        self.assertIn('[+Friend+]', output)

    def test_case_insensitive_html_output(self):
        """Test case-insensitive comparison with HTML output"""
        before = "Price: $100"
        after = "PRICE: $200"

        # Case-insensitive should only highlight the price change
        output = diff.render_diff(before, after, include_equal=False, case_insensitive=True, word_diff=True, html_colour=True)

        # Should highlight the changed number
        self.assertIn('100', output)
        self.assertIn('200', output)
        self.assertIn('background-color', output)

if __name__ == '__main__':
    unittest.main()
