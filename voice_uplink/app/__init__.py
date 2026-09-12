"""Minimal shim package for the Linux voice uplink.

Only voice_relay.py is reused. The launcher's real app/ package pulls in
detect.py, which imports winreg and cannot load on Linux — so config.py and
paths.py are replaced here with the two lookups voice_relay imports for its
DEFAULT sources. The uplink always passes explicit sources, so these defaults
are never called; they exist to satisfy the import.
"""
