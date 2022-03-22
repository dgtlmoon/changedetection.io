#!/usr/bin/python3

# Entry-point for running from the CLI when not installed via PIP
# Pip will handle the console_scripts entry_points's from setup.py
from changedetectionio import changedetection

if __name__ == '__main__':
    changedetection.main()
