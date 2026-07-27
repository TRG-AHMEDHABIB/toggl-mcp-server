# Toggl MCP Server

A Model Context Protocol server that logs time entries to Toggl Track from a weekly summary.

## Tools

- `get_projects` — fetch workspace, projects, and tasks
- `log_time_entry` — create a single entry
- `log_bulk_time_entries` — create many entries (handles rate limits)
- `list_recent_entries` — check what's already logged

## Configuration

Set `TOGGL_API_TOKEN` (required) and optionally `TOGGL_TZ` (default `America/Chicago`).

Get your Toggl token from Toggl Track → Profile Settings → API Token.

## Running

```bash
uvx --from git+https://github.com/<you>/toggl-mcp-server toggl-mcp
```

Or locally during development:

```bash
pip install -e .
toggl-mcp
```

## Obot setup

1. Add MCP Server → Single User Server
2. Runtime: **UVX**
3. Package: `git+https://github.com/<you>/toggl-mcp-server`
4. Command: `toggl-mcp`
5. User Configuration: `TOGGL_API_TOKEN` (required)
