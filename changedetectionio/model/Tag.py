
from changedetectionio.model import WatchBase


class model(WatchBase):

    def __init__(self, *arg, **kw):
        super(model, self).__init__(*arg, **kw)

        self['overrides_watch'] = kw.get('default', {}).get('overrides_watch')

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']
