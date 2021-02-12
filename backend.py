#!/usr/bin/python3

# Launch as a eventlet.wsgi server instance.

import getopt
import sys

import eventlet
import eventlet.wsgi
import backend

def main(argv):
    ssl_mode = False
    port = 5000
    datastore_path = "./datastore"

    try:
        opts, args = getopt.getopt(argv, "sd:p:", "purge")
    except getopt.GetoptError:
        print('backend.py -s SSL enable -p [port]')
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


    # @todo finalise SSL config, but this should get you in the right direction if you need it.

    app = backend.changedetection_app({'datastore_path':datastore_path})
    if ssl_mode:
        eventlet.wsgi.server(eventlet.wrap_ssl(eventlet.listen(('', port)),
                                               certfile='cert.pem',
                                               keyfile='privkey.pem',
                                               server_side=True), app)

    else:
        eventlet.wsgi.server(eventlet.listen(('', port)), backend.changedetection_app())

if __name__ == '__main__':
    main(sys.argv)

#print (__name__)