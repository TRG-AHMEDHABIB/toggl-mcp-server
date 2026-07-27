"""Entry point: `python -m toggl_mcp` or via the `toggl-mcp-trg` console script."""
from .server import mcp


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
