"""
Toggl Track v9 API client — shared by the MCP server.
Auth: HTTP Basic with API token as username, "api_token" as password.
Token sourced from TOGGL_API_TOKEN environment variable.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

API_BASE = "https://api.track.toggl.com/api/v9"
USER_AGENT = "toggl-mcp-server/1.0"
CREATED_WITH = "toggl-mcp-server"

# Module-level caches — populated on first use and reused for the lifetime of the process.
_USER_TZ_CACHE: str | None = None
_WORKSPACE_ID_CACHE: int | None = 7876867


def get_token() -> str:
    token = os.environ.get("TOGGL_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TOGGL_API_TOKEN environment variable is not set.")
    return token


def _auth_header(token: str) -> str:
    raw = f"{token}:api_token".encode("ascii")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def request(method: str, path: str, body: dict | None = None,
            query: dict | None = None) -> Any:
    token = get_token()
    url = API_BASE + path
    if query:
        url += "?" + urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": _auth_header(token),
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            return json.loads(payload.decode("utf-8")) if payload else None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} on {method} {path}: {body_text.strip()}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}") from None


def fetch_all_tasks(workspace_id: int) -> list[dict]:
    """Paginate through all tasks in the workspace (active + inactive)."""
    all_tasks: list[dict] = []
    page, per_page = 1, 200
    while True:
        resp = request("GET", f"/workspaces/{workspace_id}/tasks",
                       query={"page": page, "per_page": per_page}) or {}
        raw = resp.get("data") if isinstance(resp, dict) else resp
        page_tasks = raw or []
        all_tasks.extend(page_tasks)
        total = resp.get("total_count", 0) if isinstance(resp, dict) else 0
        if len(all_tasks) >= total or len(page_tasks) < per_page:
            break
        page += 1
    return all_tasks


def _get_workspace_id() -> int:
    override = os.environ.get("TOGGL_WORKSPACE_ID", "").strip()
    return int(override) if override else _WORKSPACE_ID_CACHE


def get_workspace_info() -> dict:
    """Return user, default workspace, projects and all their tasks."""
    workspace_id = _get_workspace_id()
    me = request("GET", "/me")
    workspaces = request("GET", "/workspaces") or []
    projects = request("GET", f"/workspaces/{workspace_id}/projects",
                       query={"active": "true"}) or []

    tasks_by_project: dict[int, list[dict]] = {}
    try:
        for t in fetch_all_tasks(workspace_id):
            pid = t.get("project_id")
            if pid:
                tasks_by_project.setdefault(pid, []).append(t)
    except RuntimeError:
        pass  # tasks are a paid feature; continue without them

    return {
        "user": {
            "id": me.get("id"),
            "fullname": me.get("fullname"),
            "email": me.get("email"),
            "timezone": me.get("timezone"),
        },
        "default_workspace_id": workspace_id,
        "workspaces": [{"id": w["id"], "name": w["name"]} for w in workspaces],
        "projects": [
            {
                "id": p["id"],
                "name": p["name"],
                "active": p.get("active", True),
                "tasks": [
                    {"id": t["id"], "name": t["name"], "active": t.get("active", True)}
                    for t in tasks_by_project.get(p["id"], [])
                ],
            }
            for p in projects
        ],
    }


def get_user_timezone() -> str:
    """
    Resolve the user's IANA timezone, in priority order:
      1. TOGGL_TZ env var (admin override)
      2. Cached value from a prior /me call
      3. Toggl profile timezone via GET /me
      4. UTC as a safe last resort
    """
    global _USER_TZ_CACHE
    override = os.environ.get("TOGGL_TZ", "").strip()
    if override:
        return override
    if _USER_TZ_CACHE:
        return _USER_TZ_CACHE
    try:
        me = request("GET", "/me")
        tz = (me or {}).get("timezone") or "UTC"
        _USER_TZ_CACHE = tz
        return tz
    except Exception:
        return "UTC"


def to_utc_rfc3339(local_date: str, local_time: str, tz: str) -> str:
    naive = datetime.strptime(f"{local_date} {local_time}", "%Y-%m-%d %H:%M")
    local = naive.replace(tzinfo=ZoneInfo(tz))
    utc = local.astimezone(ZoneInfo("UTC"))
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_time_entry(workspace_id: int, project_id: int | None,
                      task_id: int | None, description: str,
                      local_date: str, duration_seconds: int,
                      tz: str, local_start_time: str = "09:00",
                      billable: bool | None = None,
                      tags: list[str] | None = None) -> dict:
    start_utc = to_utc_rfc3339(local_date, local_start_time, tz)
    payload: dict = {
        "created_with": CREATED_WITH,
        "workspace_id": workspace_id,
        "duration": duration_seconds,
        "start": start_utc,
        "description": description,
    }
    if project_id:
        payload["project_id"] = project_id
    if task_id:
        payload["task_id"] = task_id
    if billable is not None:
        payload["billable"] = bool(billable)
    if tags:
        payload["tags"] = tags
    return request("POST", f"/workspaces/{workspace_id}/time_entries", body=payload)


def list_time_entries(since: str | None = None, until: str | None = None) -> list[dict]:
    query = {}
    if since:
        query["start_date"] = since + "T00:00:00Z"
    if until:
        query["end_date"] = until + "T23:59:59Z"
    return request("GET", "/me/time_entries", query=query or None) or []


def update_time_entry(workspace_id: int, time_entry_id: int,
                      duration_seconds: int | None = None,
                      description: str | None = None,
                      project_id: int | None = None,
                      task_id: int | None = None,
                      local_date: str | None = None,
                      local_start_time: str | None = None,
                      tz: str | None = None,
                      billable: bool | None = None,
                      tags: list[str] | None = None) -> dict:
    """PUT /workspaces/{wid}/time_entries/{tid} — patch only the fields provided."""
    payload: dict = {}
    if duration_seconds is not None:
        payload["duration"] = duration_seconds
    if description is not None:
        payload["description"] = description
    if project_id is not None:
        payload["project_id"] = project_id
    if task_id is not None:
        payload["task_id"] = task_id
    if local_date is not None:
        # changing the date requires recomputing start
        time_part = local_start_time or "09:00"
        zone = tz or get_user_timezone()
        payload["start"] = to_utc_rfc3339(local_date, time_part, zone)
    if billable is not None:
        payload["billable"] = bool(billable)
    if tags is not None:
        payload["tags"] = tags
    return request("PUT", f"/workspaces/{workspace_id}/time_entries/{time_entry_id}",
                   body=payload)


def delete_time_entry(workspace_id: int, time_entry_id: int) -> None:
    """DELETE /workspaces/{wid}/time_entries/{tid}."""
    request("DELETE", f"/workspaces/{workspace_id}/time_entries/{time_entry_id}")
