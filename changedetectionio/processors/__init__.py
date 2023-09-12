from abc import abstractmethod
import hashlib


class difference_detection_processor():


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @abstractmethod
    def run(self, uuid, skip_when_checksum_same=True, preferred_proxy=None):
        update_obj = {'last_notification_error': False, 'last_error': False}
        some_data = 'xxxxx'
        update_obj["previous_md5"] = hashlib.md5(some_data.encode('utf-8')).hexdigest()
        changed_detected = False
        return changed_detected, update_obj, ''.encode('utf-8')


def available_processors():
    import importlib
    import pkgutil

    from . import restock_diff, text_json_diff

    processors = [('text_json_diff', text_json_diff.name), ('restock_diff', restock_diff.name)]

    discovered_plugins = {
        name: importlib.import_module(name)
        for finder, name, ispkg
        in pkgutil.iter_modules()
        if name.startswith('changedetectionio-plugin-')
    }

    try:
        for name, plugin in discovered_plugins.items():
            if hasattr(plugin, 'processors'):
                for machine_name, desc in plugin.processors.items():
                    processors.append((machine_name, desc))
    except Exception as e:
        print (f"Problem fetching one or more plugins")

    return processors
