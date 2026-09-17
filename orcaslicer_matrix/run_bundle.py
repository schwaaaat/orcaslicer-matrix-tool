"""Portable Matrix Studio v2 run bundles and the local run-library index."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 2
DEFAULT_SOFT_LIMIT = 8
HARD_VARIANT_LIMIT = 32
VIEWER_PAGE_SIZE = 8
RUN_FILENAME = "run.json"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class AxisDefinition:
    key: str
    label: str
    values: List[str]


@dataclass
class VariantRecord:
    id: str
    ordinal: int
    name: str
    changes: Dict[str, str]
    state: str = "pending"
    gcode_path: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    slice_wall_seconds: Optional[float] = None


@dataclass
class RunBundle:
    run_id: str
    name: str
    created_utc: str
    updated_utc: str
    state: str
    source: Dict[str, Any]
    axes: List[AxisDefinition]
    variants: List[VariantRecord]
    baseline_snapshot: Dict[str, str] = field(default_factory=dict)
    restoration: Dict[str, Any] = field(
        default_factory=lambda: {"required": False, "completed": False, "error": None}
    )
    settings: Dict[str, Any] = field(
        default_factory=lambda: {
            "soft_variant_limit": DEFAULT_SOFT_LIMIT,
            "hard_variant_limit": HARD_VARIANT_LIMIT,
            "viewer_page_size": VIEWER_PAGE_SIZE,
            "require_eta_approval": True,
            "auto_confirm_under_seconds": 30,
        }
    )
    comparison: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        name: str,
        axes: Iterable[AxisDefinition],
        variants: Iterable[VariantRecord],
        source: Optional[Dict[str, Any]] = None,
    ) -> "RunBundle":
        now = utc_now()
        return cls(
            run_id=str(uuid.uuid4()),
            name=name,
            created_utc=now,
            updated_utc=now,
            state="draft",
            source=source or {},
            axes=list(axes),
            variants=list(variants),
        )

    def touch(self, state: Optional[str] = None) -> None:
        self.updated_utc = utc_now()
        if state is not None:
            self.state = state

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunBundle":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported run bundle schema: {data.get('schema_version')!r}")
        axes = [AxisDefinition(**item) for item in data.get("axes", [])]
        variants = [VariantRecord(**item) for item in data.get("variants", [])]
        return cls(
            run_id=data["run_id"],
            name=data["name"],
            created_utc=data["created_utc"],
            updated_utc=data["updated_utc"],
            state=data["state"],
            source=dict(data.get("source", {})),
            axes=axes,
            variants=variants,
            baseline_snapshot=dict(data.get("baseline_snapshot", {})),
            restoration=dict(data.get("restoration", {})),
            settings=dict(data.get("settings", {})),
            comparison=dict(data.get("comparison", {})),
            schema_version=SCHEMA_VERSION,
        )


class RunBundleStore:
    """Writes bundles atomically so a crash cannot leave a half-written run file."""

    def __init__(self, runs_root: Path):
        self.runs_root = Path(runs_root)

    def create_directory(self, bundle: RunBundle) -> Path:
        day = bundle.created_utc[:10]
        safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in bundle.name).strip("-")
        safe = "-".join(part for part in safe.split("-") if part)[:48] or "matrix-run"
        run_dir = self.runs_root / f"{day}-{safe}-{bundle.run_id[:8]}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def save(self, run_dir: Path, bundle: RunBundle) -> Path:
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        bundle.touch()
        target = run_dir / RUN_FILENAME
        payload = json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=".run-", suffix=".tmp", dir=run_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target

    def load(self, run_path: Path) -> RunBundle:
        path = Path(run_path)
        if path.is_dir():
            path = path / RUN_FILENAME
        return RunBundle.from_dict(json.loads(path.read_text(encoding="utf-8")))


class RunLibrary:
    """Small SQLite index; portable run folders remain the authoritative data."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL,
                    variant_count INTEGER NOT NULL,
                    path TEXT NOT NULL UNIQUE
                )
                """
            )
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def upsert(self, bundle: RunBundle, run_dir: Path) -> None:
        with closing(self._connect()) as db:
            db.execute(
                """
                INSERT INTO runs(run_id, name, state, created_utc, updated_utc, variant_count, path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    name=excluded.name,
                    state=excluded.state,
                    updated_utc=excluded.updated_utc,
                    variant_count=excluded.variant_count,
                    path=excluded.path
                """,
                (
                    bundle.run_id,
                    bundle.name,
                    bundle.state,
                    bundle.created_utc,
                    bundle.updated_utc,
                    len(bundle.variants),
                    str(Path(run_dir).resolve()),
                ),
            )
            db.commit()

    def list_runs(self, search: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        query = (
            "SELECT run_id, name, state, created_utc, updated_utc, variant_count, path "
            "FROM runs"
        )
        params: List[Any] = []
        if search.strip():
            query += " WHERE name LIKE ?"
            params.append(f"%{search.strip()}%")
        query += " ORDER BY updated_utc DESC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, params)]

    def delete_run(self, run_id: Optional[str] = None, path: Optional[str] = None) -> None:
        """Remove a run entry from the library database by its run_id or path."""
        with closing(self._connect()) as db:
            if run_id:
                db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            elif path:
                db.execute("DELETE FROM runs WHERE path = ?", (str(Path(path).resolve()),))
            db.commit()
