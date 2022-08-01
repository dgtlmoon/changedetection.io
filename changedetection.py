#!/usr/bin/python3

# Entry-point for running from the CLI when not installed via Pip, Pip will handle the console_scripts entry_points's from setup.py
# It's recommended to use `pip3 install changedetection.io` and start with `changedetection.py` instead, it will be linkd to your global path.
# or Docker.
# Read more https://github.com/dgtlmoon/changedetection.io/wiki

from changedetectionio import changedetection
import multiprocessing

if __name__ == '__main__':

    # The only way I could find to get Flask to shutdown, is to wrap it and then rely on the subsystem issuing SIGTERM/SIGKILL
    parse_process = multiprocessing.Process(target=changedetection.main)
    parse_process.daemon = True
    parse_process.start()
    import time

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        #parse_process.terminate() not needed, because this process will issue it to the sub-process anyway
        print ("Exited - CTRL+C")
