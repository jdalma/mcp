"""v2 server stub — Phase 0. Real implementation lands in Phase 1."""

import logging
import sys

from mcp.server.fastmcp import FastMCP

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("vault-decision")


@mcp.tool()
def ping() -> str:
    """Health check. Returns 'pong-phase-0'."""
    return "pong-phase-0"


def main() -> None:
    logger.info("vault-decision-mcp v2 (Phase 0 stub) starting on stdio...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
