"""Console entry point: runs the pet hospital MCP server.

Usage:
    python -m pet_hospital_mcp            # from the project root
    pet-hospital-mcp                      # installed console script
"""

from __future__ import annotations

import asyncio

from .config import Settings
from .logging_config import configure_logging
from .server import create_server


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    server = create_server(settings)
    asyncio.run(
        server.run_streamable_http_async(
            host=settings.mcp_host,
            port=settings.mcp_port,
            streamable_http_path="/mcp",
            stateless_http=True,
        )
    )


if __name__ == "__main__":
    main()