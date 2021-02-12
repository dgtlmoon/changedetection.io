#!/usr/bin/python3

# Launch as a eventlet.wsgi server instance.

import getopt
import sys

import eventlet
import eventlet.wsgi
import backend

from backend import store


def main(argv):
    ssl_mode = False
    port = 5000
    datastore_path = "./datastore"

    try:
        opts, args = getopt.getopt(argv, "sd:p:", "purge")
    except getopt.GetoptError:
        print('backend.py -s SSL enable -p [port] -d [datastore path]')
        sys.exit(2)

    for opt, arg in opts:
        #        if opt == '--purge':
        # Remove history, the actual files you need to delete manually.
        #            for uuid, watch in datastore.data['watching'].items():
        #                watch.update({'history': {}, 'last_checked': 0, 'last_changed': 0, 'previous_md5': None})

        if opt == '-s':
            ssl_mode = True

        if opt == '-p':
            port = arg

        if opt == '-d':
            datastore_path = arg


    # Kinda weird to tell them both where `datastore_path` is right..
    app_config = {'datastore_path': datastore_path}
    datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'])
    app = backend.changedetection_app(app_config, datastore)

    if ssl_mode:
        # @todo finalise SSL config, but this should get you in the right direction if you need it.
        eventlet.wsgi.server(eventlet.wrap_ssl(eventlet.listen(('', port)),
                                               certfile='cert.pem',
                                               keyfile='privkey.pem',
                                               server_side=True), app)

    else:
        eventlet.wsgi.server(eventlet.listen(('', port)), app)


if __name__ == '__main__':
    main(sys.argv[1:])
