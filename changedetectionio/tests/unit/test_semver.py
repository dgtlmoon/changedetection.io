#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_semver

import re
import unittest


# The SEMVER regex
SEMVER_REGEX = r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"

# Compile the regex
semver_pattern = re.compile(SEMVER_REGEX)

class TestSemver(unittest.TestCase):
    def test_valid_versions(self):
        """Test valid semantic version strings"""
        valid_versions = [
            "1.0.0",
            "0.1.0",
            "0.0.1",
            "1.0.0-alpha",
            "1.0.0-alpha.1",
            "1.0.0-0.3.7",
            "1.0.0-x.7.z.92",
            "1.0.0-alpha+001",
            "1.0.0+20130313144700",
            "1.0.0-beta+exp.sha.5114f85"
        ]
        for version in valid_versions:
            with self.subTest(version=version):
                self.assertIsNotNone(semver_pattern.match(version), f"Version {version} should be valid")

    def test_invalid_versions(self):
        """Test invalid semantic version strings"""
        invalid_versions = [
            "0.48.06",
            "1.0",
            "1.0.0-",
# Seems to pass the semver.org regex?
#            "1.0.0-alpha-",
            "1.0.0+",
            "1.0.0-alpha+",
            "1.0.0-",
            "01.0.0",
            "1.01.0",
            "1.0.01",
            ".1.0.0",
            "1..0.0"
        ]
        for version in invalid_versions:
            with self.subTest(version=version):
                res = semver_pattern.match(version)
                self.assertIsNone(res, f"Version '{version}' should be invalid")

    def test_our_version(self):
        from changedetectionio import get_version
        our_version = get_version()
        self.assertIsNotNone(semver_pattern.match(our_version), f"Our version '{our_version}' should be a valid SEMVER string")


if __name__ == '__main__':
    unittest.main()
