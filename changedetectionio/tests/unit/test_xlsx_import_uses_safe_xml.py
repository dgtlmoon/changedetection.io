#!/usr/bin/env python3
"""The XLSX import reads XML from an uploaded file. openpyxl only uses the safe XML parser when the
defusedxml package is installed, and silently uses the standard one when it is not."""


def test_openpyxl_uses_the_safe_xml_parser():
    import openpyxl.xml

    assert openpyxl.xml.DEFUSEDXML is True, "defusedxml must be installed, see requirements.txt"
