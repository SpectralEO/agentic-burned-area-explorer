from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import AgentRun, FindingCard, Investigation


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS investigations (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS finding_cards (
                id TEXT PRIMARY KEY,
                investigation_id TEXT NOT NULL,
                data TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                investigation_id TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
            );
            """
        )


def save_investigation(db_path: Path, inv: Investigation) -> Investigation:
    now = datetime.now(timezone.utc)
    inv.updated_at = now
    data = inv.model_dump(mode="json")
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO investigations (id, data, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
            """,
            (inv.id, json.dumps(data), inv.created_at.isoformat(), inv.updated_at.isoformat()),
        )
    return inv


def get_investigation(db_path: Path, investigation_id: str) -> Investigation:
    with connect(db_path) as conn:
        row = conn.execute("SELECT data FROM investigations WHERE id=?", (investigation_id,)).fetchone()
    if row is None:
        raise KeyError(f"Investigation not found: {investigation_id}")
    return Investigation.model_validate_json(row["data"])


def list_investigations(db_path: Path) -> list[Investigation]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT data FROM investigations ORDER BY updated_at DESC").fetchall()
    return [Investigation.model_validate_json(row["data"]) for row in rows]


def _finding_natural_key(card: FindingCard) -> str:
    payload = card.payload or {}
    provenance = card.provenance or {}
    params = provenance.get("parameters", {}) if isinstance(provenance.get("parameters", {}), dict) else {}
    cluster_id = (
        payload.get("cluster_id")
        or (payload.get("cluster", {}).get("properties", {}).get("cluster_id") if isinstance(payload.get("cluster"), dict) else None)
        or ""
    )
    year = payload.get("year") or params.get("year") or ""
    confidence_mode = params.get("confidence_mode") or payload.get("confidence_mode") or ""
    sensor = params.get("sensor") or payload.get("sensor_request") or ""
    composite = params.get("composite") or payload.get("composite") or ""
    return "|".join(
        [
            card.investigation_id,
            card.type.value,
            card.title.strip().lower(),
            card.source_dataset.strip().lower(),
            str(cluster_id),
            str(year),
            str(confidence_mode),
            str(sensor),
            str(composite),
        ]
    )


def save_finding_cards(db_path: Path, cards: Iterable[FindingCard]) -> list[FindingCard]:
    """Save cards while avoiding duplicate finding for repeated workflow runs.

    The app is a stateful investigation workspace, so users may click the same
    suggested action multiple times. Re-running a workflow should refresh/update
    the existing finding object rather than filling the board with duplicates.
    """
    cards = list(cards)
    saved: list[FindingCard] = []
    with connect(db_path) as conn:
        existing_rows = conn.execute("SELECT id, data FROM finding_cards").fetchall()
        existing_by_key: dict[str, FindingCard] = {}
        for row in existing_rows:
            existing_card = FindingCard.model_validate_json(row["data"])
            existing_by_key[_finding_natural_key(existing_card)] = existing_card

        for card in cards:
            key = _finding_natural_key(card)
            existing = existing_by_key.get(key)
            if existing is not None:
                card.id = existing.id
                card.created_at = existing.created_at
                # Preserve explicit user report-inclusion decisions across reruns.
                card.pinned = existing.pinned or card.pinned

            conn.execute(
                """
                INSERT INTO finding_cards (id, investigation_id, data, pinned, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET data=excluded.data, pinned=excluded.pinned
                """,
                (
                    card.id,
                    card.investigation_id,
                    json.dumps(card.model_dump(mode="json")),
                    1 if card.pinned else 0,
                    card.created_at.isoformat(),
                ),
            )
            existing_by_key[key] = card
            saved.append(card)
    return saved


def list_finding_cards(db_path: Path, investigation_id: str) -> list[FindingCard]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT data FROM finding_cards WHERE investigation_id=? ORDER BY created_at ASC",
            (investigation_id,),
        ).fetchall()
    return [FindingCard.model_validate_json(row["data"]) for row in rows]


def get_finding_card(db_path: Path, finding_id: str) -> FindingCard:
    with connect(db_path) as conn:
        row = conn.execute("SELECT data FROM finding_cards WHERE id=?", (finding_id,)).fetchone()
    if row is None:
        raise KeyError(f"Finding card not found: {finding_id}")
    return FindingCard.model_validate_json(row["data"])



def save_finding_card(db_path: Path, card: FindingCard) -> FindingCard:
    """Persist a single finding card update without changing its natural key."""
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO finding_cards (id, investigation_id, data, pinned, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, pinned=excluded.pinned
            """,
            (
                card.id,
                card.investigation_id,
                json.dumps(card.model_dump(mode="json")),
                1 if card.pinned else 0,
                card.created_at.isoformat(),
            ),
        )
    return card


def set_finding_pin(db_path: Path, finding_id: str, pinned: bool) -> FindingCard:
    with connect(db_path) as conn:
        row = conn.execute("SELECT data FROM finding_cards WHERE id=?", (finding_id,)).fetchone()
        if row is None:
            raise KeyError(f"Finding card not found: {finding_id}")
        card = FindingCard.model_validate_json(row["data"])
        card.pinned = pinned
        conn.execute(
            "UPDATE finding_cards SET data=?, pinned=? WHERE id=?",
            (json.dumps(card.model_dump(mode="json")), 1 if pinned else 0, finding_id),
        )
    return card


def delete_finding_card(db_path: Path, finding_id: str) -> None:
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM finding_cards WHERE id=?", (finding_id,))
        if cur.rowcount == 0:
            raise KeyError(f"Finding card not found: {finding_id}")


def save_agent_run(db_path: Path, run: AgentRun) -> AgentRun:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO agent_runs (id, investigation_id, data, created_at) VALUES (?, ?, ?, ?)",
            (
                run.id,
                run.investigation_id,
                json.dumps(run.model_dump(mode="json")),
                run.created_at.isoformat(),
            ),
        )
    return run
