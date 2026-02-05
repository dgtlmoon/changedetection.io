
from changedetectionio.model import watch_base


class model(watch_base):

    def __init__(self, *arg, **kw):
        # Store datastore reference (optional for Tags, but good for consistency)
        self.__datastore = kw.get('__datastore')
        if kw.get('__datastore'):
            del kw['__datastore']

        super(model, self).__init__(*arg, **kw)

        self['overrides_watch'] = kw.get('default', {}).get('overrides_watch')

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']
