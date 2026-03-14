"""Tado CE zone configuration — per-zone settings managed via Options Flow.

Entity classes and async_setup_* functions removed in v3.1.0.
Per-zone configuration is now handled entirely through the Options Flow
menu (Zone Configuration), which reads/writes zone_config.json via
ZoneConfigManager. No HA entities are created for per-zone settings.

The cleanup definitions in entity_cleanup.py are preserved to remove
legacy zone config entities on upgrade.
"""

from __future__ import annotations
