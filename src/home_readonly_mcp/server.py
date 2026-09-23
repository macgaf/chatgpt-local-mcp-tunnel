from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .policy import Policy
from .service import ReadOnlyHomeService


policy = Policy.from_file()
service = ReadOnlyHomeService(policy)

mcp = MCPServer(
    "home-readonly-mcp",
    version="0.2.0",
    instructions=(
        "Read-only access to the user's HOME directory. Sensitive paths are filtered by policy. "
        "No write, delete, rename, shell, or command-execution tools exist."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


@mcp.tool(annotations=READ_ONLY)
def policy_info() -> dict[str, Any]:
    """Show the effective HOME root and read-only allow/deny policy. Does not expose file contents."""
    return service.policy_info()


@mcp.tool(annotations=READ_ONLY)
def list_directory(path: str = ".", limit: int | None = None) -> dict[str, Any]:
    """List an allowed directory under HOME. Denied entries are hidden from the result."""
    return service.list_directory(path, limit)


@mcp.tool(annotations=READ_ONLY)
def file_info(path: str) -> dict[str, Any]:
    """Return metadata and SHA-256 (for allowed small files) without modifying the file."""
    return service.file_info(path)


@mcp.tool(annotations=READ_ONLY)
def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
    """Read UTF-8/text content from an allowed file under HOME. Binary and oversized files are blocked."""
    return service.read_file(path, start_line, end_line)


@mcp.tool(annotations=READ_ONLY)
def find_files(pattern: str, path: str = ".", max_results: int = 100) -> dict[str, Any]:
    """Find filenames under an allowed HOME directory using a glob pattern, without reading file contents."""
    return service.find_files(pattern, path, max_results)


@mcp.tool(annotations=READ_ONLY)
def search_text(
    query: str,
    path: str = ".",
    glob: str = "*",
    max_results: int = 100,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """Search text within allowed HOME files. Sensitive, binary, oversized and denied files are skipped."""
    return service.search_text(query, path, glob, max_results, case_sensitive)


def main() -> None:
    # stdio is the default and is the intended target for OpenAI tunnel-client.
    mcp.run()


if __name__ == "__main__":
    main()
