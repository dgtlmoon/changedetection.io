#!/usr/bin/env python3

from .. import conftest

#def pytest_addoption(parser):
#    parser.addoption("--url_suffix", action="store", default="identifier for request")


#def pytest_generate_tests(metafunc):
#    # This is called for every test. Only get/set command line arguments
#    # if the argument is specified in the list of test "fixturenames".
#    option_value = metafunc.config.option.url_suffix
#    if 'url_suffix' in metafunc.fixturenames and option_value is not None:
#        metafunc.parametrize("url_suffix", [option_value])