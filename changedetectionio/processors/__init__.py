from abc import abstractmethod
import hashlib


class difference_detection_processor():


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @abstractmethod
    def run(self, uuid, skip_when_checksum_same=True):
        update_obj = {'last_notification_error': False, 'last_error': False}
        some_data = 'xxxxx'
        update_obj["previous_md5"] = hashlib.md5(some_data.encode('utf-8')).hexdigest()
        changed_detected = False
        return changed_detected, update_obj, ''.encode('utf-8')


def available_processors():
    from . import restock_diff, text_json_diff
    # @todo Make this smarter with introspection of sorts.
    return {
        'restock_diff': {'name': restock_diff.name, 'description': restock_diff.description},
        'text_json-diff': {'name': text_json_diff.name, 'description': text_json_diff.description}
    }
