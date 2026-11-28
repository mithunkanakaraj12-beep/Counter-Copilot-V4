"""Pure, deterministic reference functions for the v0.1 contract.

No network, database, filesystem or service code belongs here. The functions show
exactly what the written rules mean; they are not an application implementation.

Modules are imported individually (``from reference import grounding``) because
``models`` uses ``reference.values`` and the other modules use ``models``.
"""
