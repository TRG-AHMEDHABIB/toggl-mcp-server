"""
Toggl Track MCP Server
Exposes Toggl time-tracking as MCP tools for Claude (Claude.ai, Obot, Claude Code).

Transport: stdio — works with Obot (UVX runtime), Claude Desktop, Claude Code.

Required env var:
    TOGGL_API_TOKEN      — your Toggl API token (Profile Settings → API Token)

Optional env vars:
    TOGGL_WORKSPACE_ID   — workspace ID override (skips /me lookup entirely).
    TOGGL_TZ             — IANA timezone override. If unset, auto-detected from
                           the Toggl profile.
"""

import json
import time
from . import client as toggl
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Toggl Track")


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_projects() -> str:
    """
    Fetch all active Toggl projects and their tasks for the default workspace.
    Returns JSON with workspace info, projects, and tasks (active + inactive).
    Always call this first before logging time to resolve project/task IDs.
    """
    try:
        info = toggl.get_workspace_info()
        return json.dumps(info, indent=2)
    except Exception as e:
        return f"Error fetching projects: {e}"


@mcp.tool()
def log_time_entry(
    workspace_id: int,
    project_id: int,
    task_id: int,
    description: str,
    local_date: str,
    duration_hours: float,
    local_start_time: str = "09:00",
    timezone: str | None = None,
    billable: bool | None = None,
    tags: list[str] | None = None,
) -> str:
    """
    Log a single time entry to Toggl Track.

    Args:
        workspace_id: Toggl workspace ID (from get_projects)
        project_id: Toggl project ID (from get_projects)
        task_id: Toggl task ID (from get_projects); required by most projects
        description: What was worked on (the "What I did" line)
        local_date: Date in YYYY-MM-DD format (local time)
        duration_hours: Hours worked (e.g. 2.5 for 2h 30m)
        local_start_time: Start time HH:MM, defaults to 09:00
        timezone: IANA timezone string. If omitted, auto-detected from the
                  user's Toggl profile (or TOGGL_TZ env if set).
        billable: Mark the entry as billable. Required by some projects.
        tags: Optional list of tag names to attach to the entry.
    """
    try:
        duration_seconds = int(duration_hours * 3600)
        result = toggl.create_time_entry(
            workspace_id=workspace_id,
            project_id=project_id,
            task_id=task_id,
            description=description,
            local_date=local_date,
            duration_seconds=duration_seconds,
            tz=timezone or toggl.get_user_timezone(),
            local_start_time=local_start_time,
            billable=billable,
            tags=tags,
        )
        return json.dumps({
            "ok": True,
            "entry_id": result.get("id"),
            "message": f"Logged {duration_hours}h on {local_date}: {description}"
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def log_bulk_time_entries(entries_json: str) -> str:
    """
    Log multiple time entries at once. Respects Toggl's 1 req/sec rate limit.

    Args:
        entries_json: JSON array of entry objects, each with fields:
            workspace_id, project_id, task_id, description,
            local_date (YYYY-MM-DD), duration_hours, local_start_time (optional),
            timezone (optional), billable (optional bool), tags (optional list)

    Example:
        [
          {"workspace_id": 123, "project_id": 456, "task_id": 789,
           "description": "PMO duties", "local_date": "2026-04-28",
           "duration_hours": 3, "billable": true, "tags": ["client-work"]},
          ...
        ]
    """
    try:
        entries = json.loads(entries_json)
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})

    # Resolve once per batch — every entry without an explicit tz uses this.
    default_tz = toggl.get_user_timezone()

    results = []
    for i, entry in enumerate(entries):
        try:
            duration_seconds = int(entry["duration_hours"] * 3600)
            result = toggl.create_time_entry(
                workspace_id=entry["workspace_id"],
                project_id=entry.get("project_id"),
                task_id=entry.get("task_id"),
                description=entry.get("description", ""),
                local_date=entry["local_date"],
                duration_seconds=duration_seconds,
                tz=entry.get("timezone", default_tz),
                local_start_time=entry.get("local_start_time", "09:00"),
                billable=entry.get("billable"),
                tags=entry.get("tags"),
            )
            results.append({
                "ok": True,
                "index": i,
                "entry_id": result.get("id"),
                "label": f"{entry['local_date']} {entry.get('description', '')[:40]}"
            })
        except Exception as e:
            results.append({
                "ok": False,
                "index": i,
                "error": str(e),
                "label": f"{entry.get('local_date', '?')} {entry.get('description', '')[:40]}"
            })

        if i < len(entries) - 1:
            time.sleep(1.05)  # Toggl rate limit: 1 req/sec

    succeeded = sum(1 for r in results if r["ok"])
    return json.dumps({
        "total": len(entries),
        "succeeded": succeeded,
        "failed": len(entries) - succeeded,
        "results": results,
    }, indent=2)


@mcp.tool()
def list_recent_entries(since: str, until: str | None = None) -> str:
    """
    List time entries in a date range to check for duplicates before logging.

    Args:
        since: Start date YYYY-MM-DD (inclusive)
        until: End date YYYY-MM-DD (inclusive), defaults to today
    """
    try:
        entries = toggl.list_time_entries(since=since, until=until)
        simplified = [
            {
                "id": e.get("id"),
                "date": (e.get("start") or "")[:10],
                "description": e.get("description"),
                "duration_hours": round(e.get("duration", 0) / 3600, 2),
                "project_id": e.get("project_id"),
                "task_id": e.get("task_id"),
                "billable": e.get("billable"),
                "tags": e.get("tags"),
            }
            for e in (entries or [])
        ]
        return json.dumps(simplified, indent=2)
    except Exception as e:
        return f"Error fetching entries: {e}"


@mcp.tool()
def update_time_entry(
    workspace_id: int,
    time_entry_id: int,
    duration_hours: float | None = None,
    description: str | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
    local_date: str | None = None,
    local_start_time: str | None = None,
    timezone: str | None = None,
    billable: bool | None = None,
    tags: list[str] | None = None,
) -> str:
    """
    Update an existing Toggl time entry. Only fields you pass are changed.

    Args:
        workspace_id: Toggl workspace ID
        time_entry_id: ID of the entry to update (from list_recent_entries)
        duration_hours: New duration in hours (e.g. 1.5)
        description: New description
        project_id: Move to a different project
        task_id: Move to a different task
        local_date: Change the date (YYYY-MM-DD)
        local_start_time: Change start time (HH:MM); pairs with local_date
        timezone: IANA timezone. If omitted when changing date, auto-detected
                  from the user's Toggl profile.
        billable: Set/unset billable flag.
        tags: Replace the entry's tag list.
    """
    try:
        duration_seconds = int(duration_hours * 3600) if duration_hours is not None else None
        result = toggl.update_time_entry(
            workspace_id=workspace_id,
            time_entry_id=time_entry_id,
            duration_seconds=duration_seconds,
            description=description,
            project_id=project_id,
            task_id=task_id,
            local_date=local_date,
            local_start_time=local_start_time,
            tz=timezone,
            billable=billable,
            tags=tags,
        )
        return json.dumps({
            "ok": True,
            "entry_id": result.get("id"),
            "message": f"Updated entry {time_entry_id}",
        })
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
def delete_time_entry(workspace_id: int, time_entry_id: int) -> str:
    """
    Delete a Toggl time entry permanently. This cannot be undone.

    Args:
        workspace_id: Toggl workspace ID
        time_entry_id: ID of the entry to delete (from list_recent_entries)
    """
    try:
        toggl.delete_time_entry(workspace_id, time_entry_id)
        return json.dumps({"ok": True, "message": f"Deleted entry {time_entry_id}"})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


# Entry point lives in __main__.py — `python -m toggl_mcp` or the
# `toggl-mcp` console script defined in pyproject.toml.
