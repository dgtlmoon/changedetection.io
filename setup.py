#!/usr/bin/env python
import codecs
import os.path
import re
import sys

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))


def read(*parts):
    return codecs.open(os.path.join(here, *parts), 'r').read()


def find_version(*file_paths):
    version_file = read(*file_paths)
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]",
                              version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")


install_requires = open('requirements.txt').readlines()

setup(
    name='changedetection.io',
    version=find_version("changedetectionio", "__init__.py"),
    description='Website change detection and monitoring service, detect changes to web pages and send alerts/notifications.',
    long_description=open('README-pip.md').read(),
    long_description_content_type='text/markdown',
    keywords='website change monitor for changes notification change detection '
             'alerts tracking website tracker change alert website and monitoring',
    entry_points={"console_scripts": ["changedetection.io=changedetectionio:main"]},
    zip_safe=True,
    scripts=["changedetection.py"],
    author='dgtlmoon',
    url='https://changedetection.io',
    packages=['changedetectionio'],
    include_package_data=True,
    install_requires=install_requires,
    license="Apache License 2.0",
    python_requires=">= 3.10",
    classifiers=['Intended Audience :: Customer Service',
                 'Intended Audience :: Developers',
                 'Intended Audience :: Education',
                 'Intended Audience :: End Users/Desktop',
                 'Intended Audience :: Financial and Insurance Industry',
                 'Intended Audience :: Healthcare Industry',
                 'Intended Audience :: Information Technology',
                 'Intended Audience :: Legal Industry',
                 'Intended Audience :: Manufacturing',
                 'Intended Audience :: Other Audience',
                 'Intended Audience :: Religion',
                 'Intended Audience :: Science/Research',
                 'Intended Audience :: System Administrators',
                 'Intended Audience :: Telecommunications Industry',
                 'Topic :: Education',
                 'Topic :: Internet',
                 'Topic :: Internet :: WWW/HTTP :: Indexing/Search',
                 'Topic :: Internet :: WWW/HTTP :: Site Management',
                 'Topic :: Internet :: WWW/HTTP :: Site Management :: Link Checking',
                 'Topic :: Internet :: WWW/HTTP :: Browsers',
                 'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
                 'Topic :: Office/Business',
                 'Topic :: Other/Nonlisted Topic',
                 'Topic :: Scientific/Engineering :: Information Analysis',
                 'Topic :: Text Processing :: Markup :: HTML',
                 'Topic :: Utilities'
                 ],
)
