from .Watch import base_config
import uuid

class model(dict):

    def __init__(self, *arg, **kw):

        self.update(base_config)

        self['uuid'] = str(uuid.uuid4())

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']


        # Goes at the end so we update the default object with the initialiser
        super(model, self).__init__(*arg, **kw)

