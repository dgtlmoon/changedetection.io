#!/usr/bin/python3

# Entry-point for running from the CLI when not installed via Pip, Pip will handle the console_scripts entry_points's from setup.py
# It's recommended to use `pip3 install changedetection.io` and start with `changedetection.py` instead, it will be linkd to your global path.
# or Docker.
# Read more https://github.com/dgtlmoon/changedetection.io/wiki

from changedetectionio import changedetection
import multiprocessing
import signal
import os

def sigterm_handler(_signo, _stack_frame):
    import sys
    print('Shutdown: Got SIGCHLD')
    # https://stackoverflow.com/questions/40453496/python-multiprocessing-capturing-signals-to-restart-child-processes-or-shut-do
    pid, status = os.waitpid(-1, os.WNOHANG | os.WUNTRACED | os.WCONTINUED)

    print('Sub-process: pid %d status %d' % (pid, status))
    if status != 0:
        sys.exit(1)

    raise SystemExit

if __name__ == '__main__':
    signal.signal(signal.SIGCHLD, sigterm_handler)
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
