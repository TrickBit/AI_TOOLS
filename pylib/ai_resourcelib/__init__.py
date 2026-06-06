# ai_resourcelib/__init__.py
"""
   __init__.py
   Library init file located in <script dir>/ai_resourcelib/

   used by:
   ai_collect_metadata.py
   ai_model_manager.py
   (possibley others later)

"""
import importlib
import os
import pkgutil
import inspect
import re

EXPORT_RULES = {
    'function': True,
    'class': True,
    'variable': r'^PUBLIC_.*',
    'pattern': r'^[a-zA-Z]\w*$',
}
# Examples that MATCH pattern:        foo bar1 A_long_var2 Z
# Examples that DO NOT MATCH pattern: 1var (starts with a digit)
#                                     _private (starts with underscore)
#                                     foo-bar (contains a hyphen)
#                                     has space (contains space)

def should_export(name, obj):
    if name.startswith('_'):
        return False

    # Global pattern filter
    pattern = EXPORT_RULES.get('pattern')
    if pattern and not re.match(pattern, name):
        return False

    if inspect.isfunction(obj):
        rule = EXPORT_RULES.get('function', True)
    elif inspect.isclass(obj):
        rule = EXPORT_RULES.get('class', True)
    else:
        rule = EXPORT_RULES.get('variable', True)

    if rule is True:
        return True
    elif rule is False:
        return False
    elif isinstance(rule, str):
        return re.match(rule, name) is not None
    else:
        return False

__all__ = []
package_dir = os.path.dirname(__file__)

for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
    if is_pkg:
        continue

    module = importlib.import_module(f".{module_name}", package=__name__)

    for name in dir(module):
        obj = getattr(module, name)
        if should_export(name, obj):
            globals()[name] = obj
            __all__.append(name)
