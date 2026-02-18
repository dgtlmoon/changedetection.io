import os
import shutil
from pathlib import Path
from loguru import logger

_SENTINEL = object()


class TagsDict(dict):
    """Dict subclass that removes the corresponding tag.json file when a tag is deleted."""

    def __init__(self, *args, datastore_path: str | os.PathLike, **kwargs) -> None:
        self._datastore_path = Path(datastore_path)
        super().__init__(*args, **kwargs)

    def __delitem__(self, key: str) -> None:
        super().__delitem__(key)
        tag_dir = self._datastore_path / key
        try:
            shutil.rmtree(tag_dir)
            logger.info(f"Deleted tag directory for tag {key!r}")
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.error(f"Failed to delete tag directory for tag {key!r}: {e}")

    def pop(self, key: str, default=_SENTINEL):
        """Remove and return tag, deleting its tag.json file. Raises KeyError if missing and no default given."""
        if key in self:
            value = self[key]
            del self[key]
            return value
        if default is _SENTINEL:
            raise KeyError(key)
        return default
