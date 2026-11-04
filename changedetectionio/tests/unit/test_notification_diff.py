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
    CHANGED_INTO_PLACEMARKER_CLOSED,
    extract_changed_from,
    extract_changed_to,
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

        output = diff.render_diff(before, after, include_equal=False, word_diff=True)
        # Unchanged text should not be wrapped in spans
        self.assertIn('points by user', output)
        self.assertIn('11', output)  # Common prefix is unchanged

        # The inner HTML uses REMOVED_INNER_STYLE and ADDED_INNER_STYLE for character-level highlighting
        expected = f'{REMOVED_PLACEMARKER_OPEN}110{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}111{ADDED_PLACEMARKER_CLOSED} points by user'
        self.assertEqual(output, expected)



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
        output = diff.render_diff(before, after, include_equal=False, case_insensitive=True, word_diff=True)
        

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
        """Test ignore_junk with placemarkers for value changes"""
        before = "Value:  100  points"
        after = "Value: 200 points"

        output = diff.render_diff(before, after, include_equal=False, word_diff=True, ignore_junk=True)
        
        # Should only highlight the actual value change
        self.assertIn(f'{REMOVED_PLACEMARKER_OPEN}100{REMOVED_PLACEMARKER_CLOSED}', output)
        self.assertIn(f'{ADDED_PLACEMARKER_OPEN}200{ADDED_PLACEMARKER_CLOSED}', output)
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

    def test_diff_changed_from_to_word_level(self):
        """Primary use case: extract just the old/new value from a changed line (e.g. price monitoring)"""
        before = "Widget costs $99.99 per month"
        after  = "Widget costs $109.99 per month"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(extract_changed_from(raw), "$99.99")
        self.assertEqual(extract_changed_to(raw),   "$109.99")

    def test_diff_changed_from_to_multiple_changes(self):
        """Multiple changed fragments on different lines are joined with newline.
        An unchanged line between the two changes ensures each is a 1-to-1 replace,
        so word_diff fires per line rather than falling back to multi-line block mode."""
        before = "Price $99\nunchanged\nTax $5"
        after  = "Price $149\nunchanged\nTax $12"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(extract_changed_from(raw), "$99\n$5")
        self.assertEqual(extract_changed_to(raw),   "$149\n$12")

    def test_diff_changed_from_to_adjacent_lines(self):
        """Adjacent changed lines give just the changed values, same as separated lines."""
        before = "Price $99\nTax $5"
        after  = "Price $149\nTax $12"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(extract_changed_from(raw), "$99\n$5")
        self.assertEqual(extract_changed_to(raw),   "$149\n$12")

    def test_word_diff_multiline_replace_pairs_lines(self):
        """A block where every line changed (e.g. a ranked table after a week of games) is
        word-diffed line by line when both sides have the same number of lines, instead of
        dumping the whole old block followed by the whole new block."""
        before = "1 Miami (59) 7-0 1735\n2 Ohio State (10) 6-1 1681\n3 Oregon 6-1 1511"
        after  = "1 Miami (62) 8-0 1740\n2 Georgia (7) 7-1 1648\n3 Oregon (1) 7-1 1540"

        raw = diff.render_diff(before, after, word_diff=True)
        lines = raw.split("\n")

        self.assertEqual(len(lines), 3, "One output line per row, not old block + new block")
        self.assertEqual(lines[0],
                         f'1 Miami {REMOVED_PLACEMARKER_OPEN}(59){REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}(62){ADDED_PLACEMARKER_CLOSED}'
                         f' {REMOVED_PLACEMARKER_OPEN}7-0{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}8-0{ADDED_PLACEMARKER_CLOSED}'
                         f' {REMOVED_PLACEMARKER_OPEN}1735{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}1740{ADDED_PLACEMARKER_CLOSED}')
        self.assertNotIn(CHANGED_PLACEMARKER_OPEN, raw)
        self.assertTrue(lines[1].startswith('2 '), "Unchanged rank token stays unwrapped")
        self.assertTrue(lines[2].startswith('3 '), "Unchanged rank token stays unwrapped")

    def test_word_diff_multiline_replace_identical_lines_left_plain(self):
        """difflib's autojunk stops matching on lines that are very common in long inputs
        (blank lines), so they can land inside a replace block. Identical pairs must be
        output as-is, not as empty change markers."""
        before = "\n".join(f"row {i} old\n" for i in range(150))
        after  = "\n".join(f"row {i} new\n" for i in range(150))

        raw = diff.render_diff(before, after, word_diff=True)

        for open_marker, closed_marker in ((ADDED_PLACEMARKER_OPEN, ADDED_PLACEMARKER_CLOSED),
                                           (REMOVED_PLACEMARKER_OPEN, REMOVED_PLACEMARKER_CLOSED),
                                           (CHANGED_PLACEMARKER_OPEN, CHANGED_PLACEMARKER_CLOSED),
                                           (CHANGED_INTO_PLACEMARKER_OPEN, CHANGED_INTO_PLACEMARKER_CLOSED)):
            self.assertNotIn(f'{open_marker}{closed_marker}', raw)
        lines = raw.split("\n")
        self.assertEqual(lines[0], f'row 0 {REMOVED_PLACEMARKER_OPEN}old{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}new{ADDED_PLACEMARKER_CLOSED}')
        self.assertEqual(lines[1], '')

    def test_diff_changed_from_to_identical_line_inside_paired_block(self):
        """An identical line left inside a paired block is not a change, so it must not
        leak into {{diff_changed_from}} / {{diff_changed_to}}."""
        before = "\n".join(f"row {i} old\n" for i in range(150))
        after  = "\n".join(f"row {i} new\n" for i in range(150))

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertIn("\n\n", raw, "Blank lines land inside the replace block")
        self.assertEqual(extract_changed_from(raw), "\n".join(["old"] * 150))
        self.assertEqual(extract_changed_to(raw),   "\n".join(["new"] * 150))

    def test_word_diff_multiline_replace_unrelated_lines_keep_block_view(self):
        """Same line count doesn't mean line i became line i. A row inserted at the top and
        another dropped at the bottom shifts every row (the numbering doesn't move, so no line
        matches), and no pair resembles its partner, so the block keeps the
        old-lines-then-new-lines view instead of word-diffing neighbours."""
        before = "1 Mango smoothie recipe\n2 Kale salad with walnuts\n3 Lentil soup for winter"
        after  = "1 Banana bread in an hour\n2 Mango smoothie recipe\n3 Kale salad with walnuts"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(raw.split("\n"), [
            f'{CHANGED_PLACEMARKER_OPEN}1 Mango smoothie recipe{CHANGED_PLACEMARKER_CLOSED}',
            f'{CHANGED_PLACEMARKER_OPEN}2 Kale salad with walnuts{CHANGED_PLACEMARKER_CLOSED}',
            f'{CHANGED_PLACEMARKER_OPEN}3 Lentil soup for winter{CHANGED_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}1 Banana bread in an hour{CHANGED_INTO_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}2 Mango smoothie recipe{CHANGED_INTO_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}3 Kale salad with walnuts{CHANGED_INTO_PLACEMARKER_CLOSED}',
        ])

    def test_word_diff_multiline_replace_mixed_similar_and_unrelated(self):
        """Similar pairs are word-diffed in place; an unrelated pair between them keeps
        the line view at its own position."""
        before = "Price $99\nMango smoothie recipe\nTax $5"
        after  = "Price $149\nKale salad with walnuts\nTax $12"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(raw.split("\n"), [
            f'Price {REMOVED_PLACEMARKER_OPEN}$99{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}$149{ADDED_PLACEMARKER_CLOSED}',
            f'{CHANGED_PLACEMARKER_OPEN}Mango smoothie recipe{CHANGED_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}Kale salad with walnuts{CHANGED_INTO_PLACEMARKER_CLOSED}',
            f'Tax {REMOVED_PLACEMARKER_OPEN}$5{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}$12{ADDED_PLACEMARKER_CLOSED}',
        ])

    def test_word_diff_single_line_replace_ignores_similarity(self):
        """A single replaced line is word-diffed however different it is, as before."""
        raw = diff.render_diff("1 Mango smoothie recipe", "1 Banana bread in an hour", word_diff=True)

        self.assertNotIn(CHANGED_PLACEMARKER_OPEN, raw)
        self.assertTrue(raw.startswith(f'1 {REMOVED_PLACEMARKER_OPEN}Mango{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}Banana{ADDED_PLACEMARKER_CLOSED}'))

    def test_word_diff_multiline_replace_over_cap_falls_back(self):
        """Blocks larger than WORD_DIFF_MAX_PAIRED_LINES keep the whole-block view, so a page
        where thousands of lines change doesn't cost thousands of diff_main() calls."""
        cap = diff.WORD_DIFF_MAX_PAIRED_LINES
        at_cap = diff.render_diff("\n".join(f"item {i} old" for i in range(cap)),
                                  "\n".join(f"item {i} new" for i in range(cap)), word_diff=True)
        self.assertNotIn(CHANGED_PLACEMARKER_OPEN, at_cap)
        self.assertEqual(len(at_cap.split("\n")), cap)

        over_cap = diff.render_diff("\n".join(f"item {i} old" for i in range(cap + 1)),
                                    "\n".join(f"item {i} new" for i in range(cap + 1)), word_diff=True)
        lines = over_cap.split("\n")
        self.assertEqual(len(lines), 2 * (cap + 1))
        self.assertEqual(lines[0], f'{CHANGED_PLACEMARKER_OPEN}item 0 old{CHANGED_PLACEMARKER_CLOSED}')
        self.assertEqual(lines[cap + 1], f'{CHANGED_INTO_PLACEMARKER_OPEN}item 0 new{CHANGED_INTO_PLACEMARKER_CLOSED}')
        self.assertNotIn(REMOVED_PLACEMARKER_OPEN, over_cap)

    def test_word_diff_paired_lines_budget_is_per_document(self):
        """The cap covers the whole document, not each block: once it is used up, later blocks keep
        the whole-block view, so many small blocks can't add up to an unbounded number of calls.
        A single replaced line is still word-diffed after the budget is spent."""
        block = diff.WORD_DIFF_MAX_PAIRED_LINES // 2 + 1
        before = [f"first {i} old" for i in range(block)] + ["separator one"] + \
                 [f"second {i} old" for i in range(block)] + ["separator two", "price 10"]
        after = [f"first {i} new" for i in range(block)] + ["separator one"] + \
                [f"second {i} new" for i in range(block)] + ["separator two", "price 12"]

        lines = diff.render_diff("\n".join(before), "\n".join(after), word_diff=True).split("\n")

        # First block fits in the budget and is paired: one line per row, no block markers
        self.assertEqual(len(lines), block + 2 * block + 1)
        self.assertNotIn(CHANGED_PLACEMARKER_OPEN, "\n".join(lines[:block]))
        # Second block would exceed what is left, so it is the old rows then the new rows
        self.assertEqual(lines[block], f'{CHANGED_PLACEMARKER_OPEN}second 0 old{CHANGED_PLACEMARKER_CLOSED}')
        self.assertEqual(lines[2 * block], f'{CHANGED_INTO_PLACEMARKER_OPEN}second 0 new{CHANGED_INTO_PLACEMARKER_CLOSED}')
        # The trailing one-line change is inline, exactly as it renders on its own
        self.assertEqual(lines[-1], diff.render_diff("price 10", "price 12", word_diff=True))

    def test_word_diff_multiline_replace_unequal_lengths_falls_back(self):
        """Different line counts on each side keep the whole-block rendering."""
        before = "alpha one\nbeta two"
        after  = "alpha uno\nbeta dos\ngamma tres"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(raw.split("\n"), [
            f'{CHANGED_PLACEMARKER_OPEN}alpha one{CHANGED_PLACEMARKER_CLOSED}',
            f'{CHANGED_PLACEMARKER_OPEN}beta two{CHANGED_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}alpha uno{CHANGED_INTO_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}beta dos{CHANGED_INTO_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}gamma tres{CHANGED_INTO_PLACEMARKER_CLOSED}',
        ])

    def test_line_diff_multiline_replace_unchanged(self):
        """word_diff=False keeps line-level output for a same-size block."""
        before = "alpha one\nbeta two"
        after  = "alpha uno\nbeta dos"

        raw = diff.render_diff(before, after, word_diff=False)

        self.assertEqual(raw.split("\n"), [
            f'{CHANGED_PLACEMARKER_OPEN}alpha one{CHANGED_PLACEMARKER_CLOSED}',
            f'{CHANGED_PLACEMARKER_OPEN}beta two{CHANGED_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}alpha uno{CHANGED_INTO_PLACEMARKER_CLOSED}',
            f'{CHANGED_INTO_PLACEMARKER_OPEN}beta dos{CHANGED_INTO_PLACEMARKER_CLOSED}',
        ])

    def test_word_diff_multiline_replace_ignore_junk(self):
        """With ignore_junk, whitespace differences inside a paired block are not reported."""
        before = "Price  $99\nTax   $5"
        after  = "Price $149\nTax $12"

        raw = diff.render_diff(before, after, word_diff=True, ignore_junk=True)

        self.assertEqual(raw.split("\n"), [
            f'Price {REMOVED_PLACEMARKER_OPEN}$99{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}$149{ADDED_PLACEMARKER_CLOSED}',
            f'Tax {REMOVED_PLACEMARKER_OPEN}$5{REMOVED_PLACEMARKER_CLOSED}{ADDED_PLACEMARKER_OPEN}$12{ADDED_PLACEMARKER_CLOSED}',
        ])

    def test_diff_changed_from_to_pure_insert_delete(self):
        """Pure line additions/deletions (no inline word diff) are also captured"""
        before = "old line"
        after  = "new line"

        # word_diff=False forces line-level CHANGED markers
        raw = diff.render_diff(before, after, word_diff=False)

        self.assertEqual(extract_changed_from(raw), "old line")
        self.assertEqual(extract_changed_to(raw),   "new line")

    def test_diff_changed_from_to_similar_numbers(self):
        """$90.00 → $9.00 must not produce a partial match like '0.00'.
        The tokenizer splits on whitespace only, so '$90.00' and '$9.00' are
        each a single atomic token — diff never sees their internal characters."""
        before = "for sale $90.00"
        after  = "for sale $9.00"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(extract_changed_from(raw), "$90.00")
        self.assertEqual(extract_changed_to(raw),   "$9.00")

    def test_diff_changed_from_to_whole_line_replaced(self):
        """When every token on the line changed (no common tokens), render_inline_word_diff
        takes the whole_line_replaced path using CHANGED/CHANGED_INTO markers instead of
        REMOVED/ADDED. Extraction must still work via the alternation in the regex."""
        before = "$99"
        after  = "$109"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(extract_changed_from(raw), "$99")
        self.assertEqual(extract_changed_to(raw),   "$109")

    def test_diff_changed_from_to_multiple_words_same_line(self):
        """When multiple words change on the same line all fragments are joined with newline.
        'quick brown fox jumps' -> 'slow brown fox hops' gives 'quick\njumps' / 'slow\nhops'.
        These tokens work best when a single value changes per line."""
        before = "quick brown fox jumps"
        after  = "slow brown fox hops"

        raw = diff.render_diff(before, after, word_diff=True)

        self.assertEqual(extract_changed_from(raw), "quick\njumps")
        self.assertEqual(extract_changed_to(raw),   "slow\nhops")

    def test_diff_changed_from_to_no_change(self):
        """No changes → empty string"""
        content = "nothing changed here"

        raw = diff.render_diff(content, content, word_diff=True)

        self.assertEqual(extract_changed_from(raw), "")
        self.assertEqual(extract_changed_to(raw),   "")


    def test_word_diff_no_prefix_whole_line_replaced(self):
        """When include_change_type_prefix=False, word-level diffs for whole-line
        replacements must not include placemarkers (issue #3816)."""
        before = "73"
        after = "100"

        raw = diff.render_diff(before, after, word_diff=True, include_change_type_prefix=False)

        self.assertNotIn('PLACEMARKER', raw)
        # Should contain just the raw values separated by newline
        self.assertIn('73', raw)
        self.assertIn('100', raw)

    def test_word_diff_no_prefix_inline_changes(self):
        """When include_change_type_prefix=False, inline word-level diffs
        must not include placemarkers (issue #3816)."""
        before = "the price is 50 dollars"
        after = "the price is 75 dollars"

        raw = diff.render_diff(before, after, word_diff=True, include_change_type_prefix=False)

        self.assertNotIn('PLACEMARKER', raw)
        self.assertIn('50', raw)
        self.assertIn('75', raw)

    def test_word_diff_with_prefix_still_wraps(self):
        """Default include_change_type_prefix=True must still wrap tokens."""
        before = "73"
        after = "100"

        raw = diff.render_diff(before, after, word_diff=True, include_change_type_prefix=True)

        self.assertIn('PLACEMARKER', raw)

    def test_word_diff_no_prefix_exact_output(self):
        """Pin exact output for include_change_type_prefix=False to catch regressions.

        Whole-line replacement: old and new values separated by newline, no markers.
        Inline partial replacement: equal tokens kept, changed tokens (both old and new)
        appended without markers — this means old+new are concatenated in place.
        """
        # Whole-line replaced: both values on separate lines, clean
        raw = diff.render_diff('73', '100', word_diff=True, include_change_type_prefix=False)
        self.assertEqual(raw, '73\n100')

        # Inline word replacement: equal context preserved, old+new token concatenated in-place
        raw = diff.render_diff('the price is 50 dollars', 'the price is 75 dollars',
                               word_diff=True, include_change_type_prefix=False)
        self.assertEqual(raw, 'the price is 5075 dollars')

        # Sanity: with prefix the whole-line case is fully wrapped
        raw = diff.render_diff('73', '100', word_diff=True, include_change_type_prefix=True)
        self.assertEqual(raw, '@changed_PLACEMARKER_OPEN73@changed_PLACEMARKER_CLOSED\n'
                               '@changed_into_PLACEMARKER_OPEN100@changed_into_PLACEMARKER_CLOSED')


if __name__ == '__main__':
    unittest.main()
