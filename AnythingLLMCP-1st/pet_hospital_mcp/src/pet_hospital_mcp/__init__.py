"""pet_hospital_mcp - stage-1 MCP service for the pet hospital management system.

Exposes a single ``list_pets`` tool (stateless Streamable HTTP, mcp==2.0.0)
that wraps the Go backend's ``GET /api/v1/pets`` endpoint.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import Settings
from .rest_client import RestClient
from .server import PetHospitalServer, build_app, create_server

__all__ = [
    "__version__",
    "Settings",
    "RestClient",
    "PetHospitalServer",
    "build_app",
    "create_server",
]