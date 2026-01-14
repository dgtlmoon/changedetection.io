from functools import lru_cache
from loguru import logger
from flask_babel import gettext
import importlib
import inspect
import os
import pkgutil

def find_sub_packages(package_name):
    """
    Find all sub-packages within the given package.

    :param package_name: The name of the base package to scan for sub-packages.
    :return: A list of sub-package names.
    """
    package = importlib.import_module(package_name)
    return [name for _, name, is_pkg in pkgutil.iter_modules(package.__path__) if is_pkg]


@lru_cache(maxsize=1)
def find_processors():
    """
    Find all subclasses of DifferenceDetectionProcessor in the specified package.
    Results are cached to avoid repeated discovery.

    :param package_name: The name of the package to scan for processor modules.
    :return: A list of (module, class) tuples.
    """
    package_name = "changedetectionio.processors"  # Name of the current package/module

    processors = []
    sub_packages = find_sub_packages(package_name)
    from changedetectionio.processors.base import difference_detection_processor

    for sub_package in sub_packages:
        module_name = f"{package_name}.{sub_package}.processor"
        try:
            module = importlib.import_module(module_name)

            # Iterate through all classes in the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Only register classes that are actually defined in this module (not imported)
                if (issubclass(obj, difference_detection_processor) and
                    obj is not difference_detection_processor and
                    obj.__module__ == module.__name__):
                    processors.append((module, sub_package))
                    break  # Only need one processor per module
        except (ModuleNotFoundError, ImportError) as e:
            logger.warning(f"Failed to import module {module_name}: {e} (find_processors())")

    # Discover plugin processors via pluggy
    try:
        from changedetectionio.pluggy_interface import plugin_manager
        plugin_results = plugin_manager.hook.register_processor()

        for result in plugin_results:
            if result and isinstance(result, dict):
                processor_module = result.get('processor_module')
                processor_name = result.get('processor_name')

                if processor_module and processor_name:
                    processors.append((processor_module, processor_name))
                    logger.info(f"Registered plugin processor: {processor_name}")
    except Exception as e:
        logger.warning(f"Error loading plugin processors: {e}")

    return processors


def get_parent_module(module):
    module_name = module.__name__
    if '.' not in module_name:
        return None  # Top-level module has no parent
    parent_module_name = module_name.rsplit('.', 1)[0]
    try:
        return importlib.import_module(parent_module_name)
    except Exception as e:
        pass

    return False



def get_custom_watch_obj_for_processor(processor_name):
    from changedetectionio.model import Watch
    watch_class = Watch.model
    processor_classes = find_processors()
    custom_watch_obj = next((tpl for tpl in processor_classes if tpl[1] == processor_name), None)
    if custom_watch_obj:
        # Parent of .processor.py COULD have its own Watch implementation
        parent_module = get_parent_module(custom_watch_obj[0])
        if hasattr(parent_module, 'Watch'):
            watch_class = parent_module.Watch

    return watch_class


def find_processor_module(processor_name):
    """
    Find the processor module by name.

    Args:
        processor_name: Processor machine name (e.g., 'image_ssim_diff')

    Returns:
        module: The processor's parent module, or None if not found
    """
    processor_classes = find_processors()
    processor_tuple = next((tpl for tpl in processor_classes if tpl[1] == processor_name), None)

    if processor_tuple:
        # Return the parent module (the package containing processor.py)
        return get_parent_module(processor_tuple[0])

    return None


def get_processor_module(processor_name):
    """
    Get the actual processor module (with perform_site_check class) by name.
    Works for both built-in and plugin processors.

    Args:
        processor_name: Processor machine name (e.g., 'text_json_diff', 'osint_recon')

    Returns:
        module: The processor module containing perform_site_check, or None if not found
    """
    processor_classes = find_processors()
    processor_tuple = next((tpl for tpl in processor_classes if tpl[1] == processor_name), None)

    if processor_tuple:
        # Return the actual processor module (first element of tuple)
        return processor_tuple[0]

    return None


def get_processor_submodule(processor_name, submodule_name):
    """
    Get an optional submodule from a processor (e.g., 'difference', 'extract', 'preview').
    Works for both built-in and plugin processors.

    Args:
        processor_name: Processor machine name (e.g., 'text_json_diff', 'osint_recon')
        submodule_name: Name of the submodule (e.g., 'difference', 'extract', 'preview')

    Returns:
        module: The submodule if it exists, or None if not found
    """
    processor_classes = find_processors()
    processor_tuple = next((tpl for tpl in processor_classes if tpl[1] == processor_name), None)

    if not processor_tuple:
        return None

    processor_module = processor_tuple[0]
    parent_module = get_parent_module(processor_module)

    if not parent_module:
        return None

    # Try to import the submodule
    try:
        # For built-in processors: changedetectionio.processors.text_json_diff.difference
        # For plugin processors: changedetectionio_osint.difference
        parent_module_name = parent_module.__name__
        submodule_full_name = f"{parent_module_name}.{submodule_name}"
        return importlib.import_module(submodule_full_name)
    except (ModuleNotFoundError, ImportError):
        return None


@lru_cache(maxsize=1)
def get_plugin_processor_metadata():
    """Get metadata from plugin processors."""
    metadata = {}
    try:
        from changedetectionio.pluggy_interface import plugin_manager
        plugin_results = plugin_manager.hook.register_processor()

        for result in plugin_results:
            if result and isinstance(result, dict):
                processor_name = result.get('processor_name')
                meta = result.get('metadata', {})
                if processor_name:
                    metadata[processor_name] = meta
    except Exception as e:
        logger.warning(f"Error getting plugin processor metadata: {e}")
    return metadata


def available_processors():
    """
    Get a list of processors by name and description for the UI elements.
    Can be filtered via DISABLED_PROCESSORS environment variable (comma-separated list).
    :return: A list :)
    """

    processor_classes = find_processors()

    # Check if DISABLED_PROCESSORS env var is set
    disabled_processors_env = os.getenv('DISABLED_PROCESSORS', 'image_ssim_diff').strip()
    disabled_processors = []
    if disabled_processors_env:
        # Parse comma-separated list and strip whitespace
        disabled_processors = [p.strip() for p in disabled_processors_env.split(',') if p.strip()]
        logger.info(f"DISABLED_PROCESSORS set, disabling: {disabled_processors}")

    available = []
    plugin_metadata = get_plugin_processor_metadata()

    for module, sub_package_name in processor_classes:
        # Skip disabled processors
        if sub_package_name in disabled_processors:
            logger.debug(f"Skipping processor '{sub_package_name}' (in DISABLED_PROCESSORS)")
            continue

        # Check if this is a plugin processor
        if sub_package_name in plugin_metadata:
            meta = plugin_metadata[sub_package_name]
            description = gettext(meta.get('name', sub_package_name))
            # Plugin processors start from weight 10 to separate them from built-in processors
            weight = 100 + meta.get('processor_weight', 0)
        else:
            # Try to get the 'name' attribute from the processor module first
            if hasattr(module, 'name'):
                description = gettext(module.name)
            else:
                # Fall back to processor_description from parent module's __init__.py
                parent_module = get_parent_module(module)
                if parent_module and hasattr(parent_module, 'processor_description'):
                    description = gettext(parent_module.processor_description)
                else:
                    # Final fallback to a readable name
                    description = sub_package_name.replace('_', ' ').title()

            # Get weight for sorting (lower weight = higher in list)
            weight = 0  # Default weight for processors without explicit weight

            # Check processor module itself first
            if hasattr(module, 'processor_weight'):
                weight = module.processor_weight
            else:
                # Fall back to parent module (package __init__.py)
                parent_module = get_parent_module(module)
                if parent_module and hasattr(parent_module, 'processor_weight'):
                    weight = parent_module.processor_weight

        available.append((sub_package_name, description, weight))

    # Sort by weight (lower weight = appears first)
    available.sort(key=lambda x: x[2])

    # Return as tuples without weight (for backwards compatibility)
    return [(name, desc) for name, desc, weight in available]


def get_processor_badge_texts():
    """
    Get a dictionary mapping processor names to their list_badge_text values.
    Translations are applied based on the current request locale.

    :return: A dict mapping processor name to badge text (e.g., {'text_json_diff': 'Text', 'restock_diff': 'Restock'})
    """
    processor_classes = find_processors()
    badge_texts = {}

    for module, sub_package_name in processor_classes:
        # Try to get the 'list_badge_text' attribute from the processor module
        if hasattr(module, 'list_badge_text'):
            badge_texts[sub_package_name] = gettext(module.list_badge_text)
        else:
            # Fall back to parent module's __init__.py
            parent_module = get_parent_module(module)
            if parent_module and hasattr(parent_module, 'list_badge_text'):
                badge_texts[sub_package_name] = gettext(parent_module.list_badge_text)

    return badge_texts


def get_processor_descriptions():
    """
    Get a dictionary mapping processor names to their description/name values.
    Translations are applied based on the current request locale.

    :return: A dict mapping processor name to description (e.g., {'text_json_diff': 'Webpage Text/HTML, JSON and PDF changes'})
    """
    processor_classes = find_processors()
    descriptions = {}

    for module, sub_package_name in processor_classes:
        # Try to get the 'name' or 'description' attribute from the processor module first
        if hasattr(module, 'name'):
            descriptions[sub_package_name] = gettext(module.name)
        elif hasattr(module, 'description'):
            descriptions[sub_package_name] = gettext(module.description)
        else:
            # Fall back to parent module's __init__.py
            parent_module = get_parent_module(module)
            if parent_module and hasattr(parent_module, 'processor_description'):
                descriptions[sub_package_name] = gettext(parent_module.processor_description)
            elif parent_module and hasattr(parent_module, 'name'):
                descriptions[sub_package_name] = gettext(parent_module.name)
            else:
                # Final fallback to a readable name
                descriptions[sub_package_name] = sub_package_name.replace('_', ' ').title()

    return descriptions


def generate_processor_badge_colors(processor_name):
    """
    Generate consistent colors for a processor badge based on its name.
    Uses a hash of the processor name to generate pleasing, accessible colors
    for both light and dark modes.

    :param processor_name: The processor name (e.g., 'text_json_diff')
    :return: A dict with 'light' and 'dark' color schemes, each containing 'bg' and 'color'
    """
    import hashlib

    # Generate a consistent hash from the processor name
    hash_obj = hashlib.md5(processor_name.encode('utf-8'))
    hash_int = int(hash_obj.hexdigest()[:8], 16)

    # Generate hue from hash (0-360)
    hue = hash_int % 360

    # Light mode: pastel background with darker text
    light_saturation = 60 + (hash_int % 25)  # 60-85%
    light_lightness = 85 + (hash_int % 10)   # 85-95% - very light
    text_lightness = 25 + (hash_int % 15)    # 25-40% - dark

    # Dark mode: solid, vibrant colors with white text
    dark_saturation = 55 + (hash_int % 20)   # 55-75%
    dark_lightness = 45 + (hash_int % 15)    # 45-60%

    return {
        'light': {
            'bg': f'hsl({hue}, {light_saturation}%, {light_lightness}%)',
            'color': f'hsl({hue}, 50%, {text_lightness}%)'
        },
        'dark': {
            'bg': f'hsl({hue}, {dark_saturation}%, {dark_lightness}%)',
            'color': '#fff'
        }
    }


@lru_cache(maxsize=1)
def get_processor_badge_css():
    """
    Generate CSS for all processor badges with auto-generated colors.
    This creates CSS rules for both light and dark modes for each processor.

    :return: A string containing CSS rules for all processor badges
    """
    processor_classes = find_processors()
    css_rules = []

    for module, sub_package_name in processor_classes:
        colors = generate_processor_badge_colors(sub_package_name)

        # Light mode rule
        css_rules.append(
            f".processor-badge-{sub_package_name} {{\n"
            f"  background-color: {colors['light']['bg']};\n"
            f"  color: {colors['light']['color']};\n"
            f"}}"
        )

        # Dark mode rule
        css_rules.append(
            f"html[data-darkmode=\"true\"] .processor-badge-{sub_package_name} {{\n"
            f"  background-color: {colors['dark']['bg']};\n"
            f"  color: {colors['dark']['color']};\n"
            f"}}"
        )

    return '\n\n'.join(css_rules)

