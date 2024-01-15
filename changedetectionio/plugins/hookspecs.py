import pluggy
from changedetectionio.store import ChangeDetectionStore

hookspec = pluggy.HookspecMarker("eggsample")


@hookspec
def extra_processor():
    """Defines a new fetch method

    :return: a tuples, (machine_name, description)
    """

@hookspec(firstresult=True)
def processor_call(processor_name: str, datastore: ChangeDetectionStore, watch_uuid: str):
    """
    Call processors with processor name
    :param processor_name: as defined in extra_processors
    :return: data?
    """