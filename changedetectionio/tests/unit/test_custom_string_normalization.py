#!/usr/bin/env python3
from unittest.mock import MagicMock

import unittest
from changedetectionio.processors.restock_diff.processor import perform_site_check
from changedetectionio.store import ChangeDetectionStore

class TestCustomStringNormalization(unittest.TestCase):
    """Test the text normalization logic for custom out-of-stock strings"""
    
    def setUp(self):
        # Create a processor instance for testing
        datastore = MagicMock(spec=ChangeDetectionStore)
        self.processor = perform_site_check(datastore=datastore, watch_uuid='test')
    
    
    def test_normalize_text_for_matching(self):
        """Test the _normalize_text_for_matching method"""
        
        test_cases = [
            # (input, expected_output)
            ("Agotado", "agotado"),
            ("AGOTADO", "agotado"),  # Lowercase
            ("Sin   stock!", "sin stock!"),  # Normalize whitespace
            ("Pronto\t\nestarán\nen stock", "pronto estaran en stock"),  # Multiple whitespace types + accents
            ("¡Temporalmente  AGOTADO!", "¡temporalmente agotado!"),  # Complex case
            ("", ""),  # Empty string
            ("café", "cafe"),  # French accent
            ("naïve", "naive"),  # Multiple accents
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = self.processor._normalize_text_for_matching(input_text)
                self.assertEqual(result, expected, 
                    f"Failed to normalize '{input_text}' -> expected '{expected}', got '{result}'")
    
    def test_check_custom_strings_normalization(self):
        """Test that custom string matching works with normalization"""
        
        test_cases = [
            # (page_text, custom_strings, should_match, description)
            ("AGOTADO", "agotado", True, "uppercase to lowercase"),
            ("Agotado", "agotado", True, "single uppercase to lowercase"),
            ("Sin   stock!", "sin stock", True, "multiple spaces normalized"),
            ("¡Pronto    estarán   en stock!", "pronto estaran en stock", True, "accents + spaces"),
            ("TEMPORALMENTE AGOTADO", "temporalmente agotado", True, "multi-word uppercase"),
            ("Available now", "agotado", False, "no match case"),
            ("", "agotado", False, "empty text"),
            ("agotado", "", False, "empty custom strings"),
        ]
        
        for page_text, custom_strings, should_match, description in test_cases:
            with self.subTest(description=description):
                result = self.processor._check_custom_strings(page_text, custom_strings, "out-of-stock")
                
                if should_match:
                    self.assertIsNotNone(result, 
                        f"Expected match for '{description}': '{page_text}' should match '{custom_strings}'")
                else:
                    self.assertIsNone(result, 
                        f"Expected no match for '{description}': '{page_text}' should not match '{custom_strings}'")
    
    def test_check_custom_strings_multiline(self):
        """Test that multi-line custom strings work properly"""
        
        page_text = "Product status: TEMPORALMENTE AGOTADO"
        custom_strings = """
        sin stock
        agotado
        temporalmente agotado
        """
        
        result = self.processor._check_custom_strings(page_text, custom_strings, "out-of-stock")
        self.assertIsNotNone(result)
        self.assertEqual(result.strip(), "agotado")
    
    def test_get_combined_instock_strings_normalization(self):
        """Test that custom in-stock strings are normalized properly"""
        
        restock_settings = {
            'custom_instock_strings': 'Disponible AHORA\nEn Stock\nDISPONÍBLE'
        }
        
        result = self.processor._get_combined_instock_strings(restock_settings)
        
        # Check that built-in strings are included
        self.assertIn('instock', result)
        self.assertIn('presale', result)
        
        # Check that custom strings are normalized and included
        self.assertIn('disponible ahora', result)
        self.assertIn('en stock', result)
        self.assertIn('disponible', result)  # accent removed


if __name__ == '__main__':
    unittest.main()