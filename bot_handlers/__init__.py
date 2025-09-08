"""
This file makes the bot_handlers directory a Python package.
It also serves as a central point for exporting all the handlers
so they can be easily imported in main.py.
"""

from .start import (
    start,
    show_private_main_menu,
)

from .reputation import (
    handle_query,
    evaluation_callback_handler,
)

from .admin import (
    admin_panel,
    # Add other admin functions here as they are built
)

# This makes it possible to use "from bot_handlers import *"
# although explicit imports are generally better.
__all__ = [
    'start',
    'show_private_main_menu',
    'handle_query',
    'evaluation_callback_handler',
    'admin_panel',
]
