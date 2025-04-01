#!/usr/bin/env python3

import ctypes
import gc
import re
import psutil
import sys
import threading
import importlib
from loguru import logger

def memory_cleanup(app=None):
    """
    Perform comprehensive memory cleanup operations and log memory usage
    at each step with nicely formatted numbers.
    
    Args:
        app: Optional Flask app instance for clearing Flask-specific caches
        
    Returns:
        str: Status message
    """
    # Get current process
    process = psutil.Process()
    
    # Log initial memory usage with nicely formatted numbers
    current_memory = process.memory_info().rss / 1024 / 1024
    logger.debug(f"Memory cleanup started - Current memory usage: {current_memory:,.2f} MB")

    # 1. Standard garbage collection - force full collection on all generations
    gc.collect(0)  # Collect youngest generation
    gc.collect(1)  # Collect middle generation
    gc.collect(2)  # Collect oldest generation

    # Run full collection again to ensure maximum cleanup
    gc.collect()
    current_memory = process.memory_info().rss / 1024 / 1024
    logger.debug(f"After full gc.collect() - Memory usage: {current_memory:,.2f} MB")
    

    # 3. Call libc's malloc_trim to release memory back to the OS
    libc = ctypes.CDLL("libc.so.6")
    libc.malloc_trim(0)
    current_memory = process.memory_info().rss / 1024 / 1024
    logger.debug(f"After malloc_trim(0) - Memory usage: {current_memory:,.2f} MB")
    
    # 4. Clear Python's regex cache
    re.purge()
    current_memory = process.memory_info().rss / 1024 / 1024
    logger.debug(f"After re.purge() - Memory usage: {current_memory:,.2f} MB")

    # 5. Reset thread-local storage
    # Create a new thread local object to encourage cleanup of old ones
    threading.local()
    current_memory = process.memory_info().rss / 1024 / 1024
    logger.debug(f"After threading.local() - Memory usage: {current_memory:,.2f} MB")

    # 6. Clear sys.intern cache if Python version supports it
    try:
        sys.intern.clear()
        current_memory = process.memory_info().rss / 1024 / 1024
        logger.debug(f"After sys.intern.clear() - Memory usage: {current_memory:,.2f} MB")
    except (AttributeError, TypeError):
        logger.debug("sys.intern.clear() not supported in this Python version")
    
    # 7. Clear XML/lxml caches if available
    try:
        # Check if lxml.etree is in use
        lxml_etree = sys.modules.get('lxml.etree')
        if lxml_etree:
            # Clear module-level caches
            if hasattr(lxml_etree, 'clear_error_log'):
                lxml_etree.clear_error_log()
            
            # Check for _ErrorLog and _RotatingErrorLog objects and clear them
            for obj in gc.get_objects():
                if hasattr(obj, '__class__') and hasattr(obj.__class__, '__name__'):
                    class_name = obj.__class__.__name__
                    if class_name in ('_ErrorLog', '_RotatingErrorLog', '_DomainErrorLog') and hasattr(obj, 'clear'):
                        try:
                            obj.clear()
                        except (AttributeError, TypeError):
                            pass
                    
                    # Clear Element objects which can hold references to documents
                    elif class_name in ('_Element', 'ElementBase') and hasattr(obj, 'clear'):
                        try:
                            obj.clear()
                        except (AttributeError, TypeError):
                            pass
            
            current_memory = process.memory_info().rss / 1024 / 1024
            logger.debug(f"After lxml.etree cleanup - Memory usage: {current_memory:,.2f} MB")

        # Check if lxml.html is in use
        lxml_html = sys.modules.get('lxml.html')
        if lxml_html:
            # Clear HTML-specific element types
            for obj in gc.get_objects():
                if hasattr(obj, '__class__') and hasattr(obj.__class__, '__name__'):
                    class_name = obj.__class__.__name__
                    if class_name in ('HtmlElement', 'FormElement', 'InputElement',
                                    'SelectElement', 'TextareaElement', 'CheckboxGroup',
                                    'RadioGroup', 'MultipleSelectOptions', 'FieldsDict') and hasattr(obj, 'clear'):
                        try:
                            obj.clear()
                        except (AttributeError, TypeError):
                            pass

            current_memory = process.memory_info().rss / 1024 / 1024
            logger.debug(f"After lxml.html cleanup - Memory usage: {current_memory:,.2f} MB")
    except (ImportError, AttributeError):
        logger.debug("lxml cleanup not applicable")
    
    # 8. Clear JSON parser caches if applicable
    try:
        # Check if json module is being used and try to clear its cache
        json_module = sys.modules.get('json')
        if json_module and hasattr(json_module, '_default_encoder'):
            json_module._default_encoder.markers.clear()
            current_memory = process.memory_info().rss / 1024 / 1024
            logger.debug(f"After JSON parser cleanup - Memory usage: {current_memory:,.2f} MB")
    except (AttributeError, KeyError):
        logger.debug("JSON cleanup not applicable")
    
    # 9. Force Python's memory allocator to release unused memory
    try:
        if hasattr(sys, 'pypy_version_info'):
            # PyPy has different memory management
            gc.collect()
        else:
            # CPython - try to release unused memory
            ctypes.pythonapi.PyGC_Collect()
            current_memory = process.memory_info().rss / 1024 / 1024
            logger.debug(f"After PyGC_Collect - Memory usage: {current_memory:,.2f} MB")
    except (AttributeError, TypeError):
        logger.debug("PyGC_Collect not supported")
    
    # 10. Clear Flask-specific caches if applicable
    if app:
        try:
            # Clear Flask caches if they exist
            for key in list(app.config.get('_cache', {}).keys()):
                app.config['_cache'].pop(key, None)
            
            # Clear Jinja2 template cache if available
            if hasattr(app, 'jinja_env') and hasattr(app.jinja_env, 'cache'):
                app.jinja_env.cache.clear()
            
            current_memory = process.memory_info().rss / 1024 / 1024
            logger.debug(f"After Flask cache clear - Memory usage: {current_memory:,.2f} MB")
        except (AttributeError, KeyError):
            logger.debug("No Flask cache to clear")
    
    # Final garbage collection pass
    gc.collect()
    libc.malloc_trim(0)
    
    # Log final memory usage
    final_memory = process.memory_info().rss / 1024 / 1024
    logger.info(f"Memory cleanup completed - Final memory usage: {final_memory:,.2f} MB")
    return "cleaned"