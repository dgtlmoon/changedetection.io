
from changedetectionio.model import watch_base

class model(watch_base):

    def __init__(self, *arg, **kw):

        super(model, self).__init__(*arg, **kw)

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']


