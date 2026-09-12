"""MorrowFriends — one-click TES3MP host/join launcher."""

# Single source of truth is paths.APP_VERSION. This used to carry its own
# hardcoded copy, which silently drifted: the 0.5.1 build shipped with the
# window still titled v0.5.0, making it impossible to tell which build was
# running while testing fixes (2026-08-18).
from .paths import APP_VERSION as __version__

__all__ = ["__version__"]
