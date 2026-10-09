import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from changedetectionio.store import file_saving_datastore


def test_load_all_watches_handles_zero_elapsed_time():
    frozen_clock = SimpleNamespace(
        perf_counter=lambda: 1.0,
        time=lambda: 1.0,
    )
    rehydrate_entity = Mock()

    with tempfile.TemporaryDirectory() as datastore_path:
        with patch.object(file_saving_datastore, 'time', frozen_clock):
            watches = file_saving_datastore.load_all_watches(
                datastore_path,
                rehydrate_entity_func=rehydrate_entity,
            )

    assert watches == {}
    rehydrate_entity.assert_not_called()
