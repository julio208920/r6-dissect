"""Local REST API shared by the React web client and Unity desktop client."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from necc_data import MAX_CATALOG_BYTES, fetch_school_catalog, normalize_school_catalog
from file_guard import ReplayScanner
from parser import ReplayParseError, collect_rec_files, group_by_match, parse_match, r6_dissect_available, save_uploads
from season_stats import DEFAULT_DB_PATH, StatsError, StatsManager


app = FastAPI(title="R6 Match Intelligence API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class MatchLogRequest(BaseModel):
    match: dict[str, Any]
    rosters: dict[str, list[str]] = Field(default_factory=dict)


class RosterRequest(BaseModel):
    team: str
    players: list[str]


class ReplayPathRequest(BaseModel):
    path: str


class _MemoryUpload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self) -> memoryview:
        return memoryview(self._data)


def _season_or_400(season: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9 _.-]{1,40}", season):
        raise HTTPException(status_code=400, detail="Invalid season name.")
    return season.strip()


def _catalog_path() -> Path:
    return Path(DEFAULT_DB_PATH).parent / "necc_r6_catalog.json"


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "r6-match-intelligence"}


@app.get("/api/v1/seasons")
def seasons() -> dict[str, list[str]]:
    with StatsManager() as manager:
        return {"seasons": manager.seasons()}


@app.get("/api/v1/seasons/{season}/summary")
def season_summary(season: str) -> dict[str, Any]:
    with StatsManager(season=_season_or_400(season)) as manager:
        return manager.export_json()


@app.get("/api/v1/seasons/{season}/matches")
def season_matches(season: str) -> dict[str, Any]:
    with StatsManager(season=_season_or_400(season)) as manager:
        return {"season": season, "matches": manager.match_history()}


@app.post("/api/v1/seasons/{season}/rosters")
def track_roster(season: str, payload: RosterRequest) -> dict[str, Any]:
    team = payload.team.strip()
    players = list(dict.fromkeys(player.strip() for player in payload.players if player.strip()))
    if not team or not players or len(players) > 100:
        raise HTTPException(status_code=400, detail="Provide a team name and between 1 and 100 player names.")
    with StatsManager(season=_season_or_400(season)) as manager:
        manager.add_players(players, team=team)
        return {"team": team, "tracked_players": manager.tracked_players()}


@app.post("/api/v1/replays/parse")
async def parse_replays(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    if not r6_dissect_available():
        raise HTTPException(status_code=503, detail="The r6-dissect replay parser is not available.")
    uploads = []
    total_bytes = 0
    max_bytes = 512 * 1024 * 1024
    for upload in files:
        data = await upload.read(max_bytes - total_bytes + 1)
        total_bytes += len(data)
        if total_bytes > max_bytes:
            raise HTTPException(status_code=413, detail="Replay uploads are limited to 512 MB per request.")
        uploads.append(_MemoryUpload(upload.filename or "replay.rec", data))

    scanner = ReplayScanner()
    try:
        with tempfile.TemporaryDirectory(prefix="r6-api-") as workdir:
            paths = save_uploads(uploads, Path(workdir), scanner)
            groups = group_by_match(paths)
            if not groups:
                raise HTTPException(status_code=400, detail=scanner.summary() or "No Siege replay files found.")
            matches = []
            for name, rec_paths in groups.items():
                match, _raw, warnings = parse_match(rec_paths)
                matches.append({"name": name, "match": match, "match_json": json.dumps(match, ensure_ascii=False), "warnings": warnings})
    except ReplayParseError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"matches": matches, "skipped": scanner.summary()}


@app.post("/api/v1/replays/parse-path")
def parse_replay_path(payload: ReplayPathRequest) -> dict[str, Any]:
    if not r6_dissect_available():
        raise HTTPException(status_code=503, detail="The r6-dissect replay parser is not available.")
    source = Path(payload.path).expanduser()
    scanner = ReplayScanner()
    try:
        with tempfile.TemporaryDirectory(prefix="r6-api-path-") as workdir:
            paths = collect_rec_files(source, Path(workdir), scanner)
            groups = group_by_match(paths)
            if not groups:
                raise HTTPException(status_code=400, detail=scanner.summary() or "No Siege replay files found.")
            matches = []
            for name, rec_paths in groups.items():
                match, _raw, warnings = parse_match(rec_paths)
                matches.append({"name": name, "match": match, "match_json": json.dumps(match, ensure_ascii=False), "warnings": warnings})
    except ReplayParseError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=f"Cannot read the requested replay path: {error}") from error
    return {"matches": matches, "skipped": scanner.summary()}


@app.post("/api/v1/seasons/{season}/matches/log")
def log_match(season: str, payload: MatchLogRequest) -> dict[str, Any]:
    with StatsManager(season=_season_or_400(season)) as manager:
        for team, players in payload.rosters.items():
            manager.add_players(players, team=team)
        try:
            result = manager.log_match(payload.match)
        except StatsError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "match_id": result.match_id,
            "rounds_logged": result.rounds_logged,
            "rounds_skipped_duplicate": result.rounds_skipped_duplicate,
            "players_logged": sorted(result.players_logged),
            "untracked_players": sorted(result.untracked_players),
            "warnings": result.warnings,
        }


@app.get("/api/v1/schools")
def schools() -> dict[str, Any]:
    if os.environ.get("NECC_R6_DATA_URL"):
        try:
            return {"schools": fetch_school_catalog(), "source": "configured-feed"}
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=503, detail=f"NECC feed unavailable: {error}") from error
    catalog = _catalog_path()
    if catalog.is_file():
        try:
            return {"schools": normalize_school_catalog(json.loads(catalog.read_text())), "source": "imported"}
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise HTTPException(status_code=500, detail=f"Saved school catalog is invalid: {error}") from error
    raise HTTPException(status_code=503, detail="No NECC feed configured and no school catalog imported.")


@app.post("/api/v1/schools/catalog")
async def import_school_catalog(request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > MAX_CATALOG_BYTES:
        raise HTTPException(status_code=413, detail="The catalog exceeds the 2 MB limit.")
    try:
        payload = json.loads(body)
        normalized = normalize_school_catalog(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"Invalid school catalog: {error}") from error
    path = _catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schools": normalized}, indent=2), encoding="utf-8")
    return {"schools": normalized, "source": "imported"}