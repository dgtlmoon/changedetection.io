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
    from . import restock_diff, text_json_diff
    x=[('text_json_diff', text_json_diff.name), ('restock_diff', restock_diff.name)]
    # @todo Make this smarter with introspection of sorts.
    return x
