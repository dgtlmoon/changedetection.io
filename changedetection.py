#!/usr/bin/python3

# Entry-point for running from the CLI when not installed via Pip, Pip will handle the console_scripts entry_points's from setup.py
# It's recommended to use `pip3 install changedetection.io` and start with `changedetection.py` instead, it will be linkd to your global path.
# or Docker.
# Read more https://github.com/dgtlmoon/changedetection.io/wiki

from changedetectionio import changedetection
import multiprocessing
import signal
import sys
import time

parse_process = multiprocessing.Process(target=changedetection.main)
parse_process.daemon = True

# The child (flask app) exited for some reason, so do a shutdown of this wrapper
# Note: this will get triggered even when we send it a SIGTERM to shut down (sigterm_handler)
def sigchld_handler(_signo, _stack_frame):
    print('Shutdown: Got SIGCHLD (child process exited)')
    parse_process.join() # Wait for it to really exit

# This (main process) got a SIGTERM, tell the child (Flask App) to shut down by sending it a SIGTERM also
def sigterm_handler(_signo, _stack_frame):
    print('Shutdown: Got SIGTERM, shutting down Flask app, waiting on shutdown..')
    parse_process.terminate()
    parse_process.join()
    print('Shutdown: Shutdown complete, exiting.')
    sys.exit(1)

# the child-process (from multiprocess.process) should be able to tell the parent one to shutdown (or detect)
# and the parent one is not exiting the child one at the moment

if __name__ == '__main__':

    signal.signal(signal.SIGCHLD, sigchld_handler)
    signal.signal(signal.SIGTERM, sigterm_handler)
    parse_process.start()

    try:
        while True:
            time.sleep(1)
            if not parse_process.is_alive():
                # Process died/crashed for some reason, exit with error set
                sys.exit(1)


    except KeyboardInterrupt:
        #parse_process.terminate() not needed, because this process will issue it to the sub-process anyway
        print ("Exited - CTRL+C")
