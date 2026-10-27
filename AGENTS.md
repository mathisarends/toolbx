# Repository conventions

- The project supports Python 3.13-3.14. Always add
  `from __future__ import annotations` to modules that use forward
  references (e.g. a class referencing its own name, or names defined later
  in the file), since lazy annotation evaluation (PEP 649) is only native to
  3.14+ and 3.13 will raise `NameError` at import time otherwise.
- Use absolute imports (`from toolbx.tools.models import Tool`),
  not relative imports (`from .models import Tool`). The one
  exception is `__init__.py` files, which use relative imports to re-export
  their package's public API.
- No comments or docstrings that just restate what the code does. Only write
  one when it explains something non-obvious: why it exists, a hidden
  constraint, or a behavior that would otherwise surprise a reader.
