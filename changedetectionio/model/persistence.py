"""
Entity persistence mixin for Watch and Tag models.

Provides file-based persistence using atomic writes.
"""

import functools
import inspect


@functools.lru_cache(maxsize=None)
def _determine_entity_type(cls):
    """
    Determine entity type from class hierarchy (cached at class level).

    Args:
        cls: The class to inspect

    Returns:
        str: Entity type ('watch', 'tag', etc.)

    Raises:
        ValueError: If entity type cannot be determined
    """
    for base_class in inspect.getmro(cls):
        module_name = base_class.__module__
        if module_name.startswith('changedetectionio.model.'):
            # Get last part after dot: "changedetectionio.model.Watch" -> "watch"
            return module_name.split('.')[-1].lower()

    raise ValueError(
        f"Cannot determine entity type for {cls.__module__}.{cls.__name__}. "
        f"Entity must inherit from a class in changedetectionio.model (Watch or Tag)."
    )


class EntityPersistenceMixin:
    """
    Mixin providing file persistence for watch_base subclasses (Watch, Tag, etc.).

    This mixin provides the _save_to_disk() method required by watch_base.commit().
    It automatically determines the correct filename and size limits based on class hierarchy.

    Usage:
        class model(EntityPersistenceMixin, watch_base):  # in Watch.py
            pass

        class model(EntityPersistenceMixin, watch_base):  # in Tag.py
            pass
    """

    def _save_to_disk(self, data_dict, uuid):
        """
        Save entity to disk using atomic write.

        Implements the abstract method required by watch_base.commit().
        Automatically determines filename and size limits from class hierarchy.

        Args:
            data_dict: Dictionary to save
            uuid: UUID for logging

        Raises:
            ValueError: If entity type cannot be determined from class hierarchy
        """
        # Import here to avoid circular dependency
        from changedetectionio.store.file_saving_datastore import save_entity_atomic

        # Determine entity type (cached at class level, not instance level)
        entity_type = _determine_entity_type(self.__class__)

        # Set filename and size limits based on entity type
        filename = f'{entity_type}.json'
        max_size_mb = 10 if entity_type == 'watch' else 1

        # Save using generic function
        save_entity_atomic(
            self.data_dir,
            uuid,
            data_dict,
            filename=filename,
            entity_type=entity_type,
            max_size_mb=max_size_mb
        )
