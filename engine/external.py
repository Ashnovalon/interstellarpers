"""Optional official external observations.  Network failures never imply zero risk."""
from __future__ import annotations

import json
import os
from datetime import date
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _get_json(url: str, timeout=8) -> dict:
    request = Request(url, headers={"User-Agent": "PulpRiotControlTower/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return json.load(response)


def poll_tomtom(as_of: date, get_json=_get_json) -> dict:
    """A bounding-box incident is a watch; it is not proof it blocks our route."""
    key = os.getenv("TOMTOM_API_KEY")
    bbox = os.getenv("PULP_ROUTE_BBOX")
    if not key or not bbox:
        return {"state": "UNCONFIGURED", "reason": "TOMTOM_API_KEY and verified PULP_ROUTE_BBOX required"}
    try:
        coords = [float(x.strip()) for x in bbox.split(",")]
        if len(coords) != 4 or not (-180 <= coords[0] < coords[2] <= 180 and -90 <= coords[1] < coords[3] <= 90):
            raise ValueError("invalid verified route bounding box")
        query = urlencode({"key": key, "bbox": bbox,
            "fields": "{incidents{geometry{type,coordinates},properties{id,iconCategory,startTime,endTime,from,to,lastReportTime}}}",
            "language": "en-GB", "timeValidityFilter": "present"})
        payload = get_json("https://api.tomtom.com/traffic/services/5/incidentDetails?" + query)
        closed = [x for x in payload.get("incidents", []) if x.get("properties", {}).get("iconCategory") == 8]
        return {"state": "WATCH" if closed else "NO_REPORTED_CLOSURE", "date": as_of.isoformat(),
                "source": "TomTom incident details", "closure_incidents_in_bbox": len(closed),
                "incidents": [{"id": x.get("properties", {}).get("id"),
                               "from": x.get("properties", {}).get("from"),
                               "to": x.get("properties", {}).get("to"),
                               "last_report": x.get("properties", {}).get("lastReportTime")}
                              for x in closed[:20]],
                "reason": "Bounding-box incidents need corridor and transporter confirmation"}
    except Exception as exc:
        return {"state": "UNKNOWN", "reason": f"TomTom request unavailable: {type(exc).__name__}"}


def poll_youtube(as_of: date, get_json=_get_json) -> dict:
    """Poll only marketing-verified video IDs; view counts are attention, not orders."""
    key = os.getenv("YOUTUBE_API_KEY")
    ids = [x.strip() for x in os.getenv("PULP_YOUTUBE_VIDEO_IDS", "").split(",") if x.strip()]
    if not key or not ids:
        return {"state": "UNCONFIGURED", "reason": "YOUTUBE_API_KEY and campaign video IDs required"}
    if len(ids) > 50:
        return {"state": "INVALID_CONFIG", "reason": "at most 50 video IDs per request"}
    try:
        query = urlencode({"key": key, "id": ",".join(ids), "part": "snippet,statistics"})
        payload = get_json("https://www.googleapis.com/youtube/v3/videos?" + query)
        videos = [{"id": x["id"], "title": x.get("snippet", {}).get("title", ""),
                   "views": int(x.get("statistics", {}).get("viewCount", 0))}
                  for x in payload.get("items", [])]
        return {"state": "OBSERVED", "date": as_of.isoformat(), "source": "YouTube Data API",
                "videos": videos, "reason": "Compare repeated observations; do not convert views directly into bottles"}
    except Exception as exc:
        return {"state": "UNKNOWN", "reason": f"YouTube request unavailable: {type(exc).__name__}"}


def poll_all(as_of: date, get_json=_get_json) -> dict:
    return {"road": poll_tomtom(as_of, get_json), "attention": poll_youtube(as_of, get_json)}
