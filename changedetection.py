#!/usr/bin/python3

# Entry-point for running from the CLI when not installed via PIP, Pip will handle the console_scripts entry_points's from setup.py
# It's recommended to use `pip3 install changedetection.io` and start with `changedetection.py` instead, it sould be linkd to your global path.

from changedetectionio import changedetection

if __name__ == '__main__':
    changedetection.main()
