"""Local database identity: inside the DB (local_identity table) and outside it
(config/instance_identity.json). Read-only check + explicit record; no network.

The outside file is per installation directory and is NOT copied with the
database, so a copied/replaced/restored database is detectable before any
future cloud bridge is allowed to consume commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid

from app.database.connection import Database
from app.utils.paths import AppPaths

IDENTITY_FILE = "instance_identity.json"


class IdentityStatus(StrEnum):
    NEW = "new"                          # no outside record yet
    PAIRED = "paired"                    # DB and installation agree
    DATABASE_CHANGED = "database_changed"  # different db_id than recorded
    MOVED_OR_COPIED = "moved_or_copied"    # same db_id, different file location
    ROLLBACK_SUSPECTED = "rollback_suspected"  # epoch/change_seq/task id went backwards
    UNAVAILABLE = "unavailable"          # schema < 5 or unreadable


@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    db_id: str
    epoch: int
    max_change_seq: int
    max_task_id: int


@dataclass(frozen=True, slots=True)
class IdentityCheck:
    status: IdentityStatus
    database: DatabaseIdentity | None
    recorded: dict | None


def install_fingerprint(database_path: Path) -> str:
    resolved = Path(database_path).resolve()
    try:
        device = os.stat(resolved).st_dev  # volume serial on Windows
    except OSError:
        device = 0
    return hashlib.sha256(f"{os.path.normcase(str(resolved))}|{device}".encode("utf-8")).hexdigest()


class LocalIdentityService:
    def __init__(self, paths: AppPaths, database: Database) -> None:
        self.paths = paths
        self.database = database

    @property
    def identity_file(self) -> Path:
        return self.paths.config_dir / IDENTITY_FILE

    def read_database_identity(self) -> DatabaseIdentity | None:
        with self.database.transaction() as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='local_identity'").fetchone() is None:
                return None
            row = connection.execute("SELECT db_id, epoch FROM local_identity WHERE singleton = 1").fetchone()
            if row is None:
                return None
            # sqlite_sequence survives deletes, so it is the highest value ever issued:
            # pruning task_changes (or hard-deleting the newest task) can never lower it.
            change_seq = self._sequence(connection, "task_changes")
            max_task_id = self._sequence(connection, "tasks")
        return DatabaseIdentity(row["db_id"], int(row["epoch"]), change_seq, max_task_id)

    @staticmethod
    def _sequence(connection, table: str) -> int:
        row = connection.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
        return int(row[0]) if row else 0

    def _read_record(self) -> dict | None:
        try:
            value = json.loads(self.identity_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("invalid instance identity file")
        return value

    def check(self) -> IdentityCheck:
        try:
            identity = self.read_database_identity()
            recorded = self._read_record()
        except (OSError, ValueError):
            return IdentityCheck(IdentityStatus.UNAVAILABLE, None, None)
        if identity is None:
            return IdentityCheck(IdentityStatus.UNAVAILABLE, None, recorded)
        if recorded is None:
            return IdentityCheck(IdentityStatus.NEW, identity, None)
        if recorded.get("db_id") != identity.db_id:
            status = IdentityStatus.DATABASE_CHANGED
        elif recorded.get("install_fingerprint") != install_fingerprint(self.database.path):
            status = IdentityStatus.MOVED_OR_COPIED
        elif (identity.epoch < int(recorded.get("epoch", 0))
              or identity.max_change_seq < int(recorded.get("last_change_seq_seen", 0))
              or identity.max_task_id < int(recorded.get("max_task_id_seen", 0))):
            status = IdentityStatus.ROLLBACK_SUSPECTED
        else:
            status = IdentityStatus.PAIRED
        return IdentityCheck(status, identity, recorded)

    def record(self, check: IdentityCheck | None = None) -> IdentityCheck:
        """Write the outside checkpoint, but only for NEW/PAIRED (keep evidence otherwise)."""
        check = check or self.check()
        if check.status not in (IdentityStatus.NEW, IdentityStatus.PAIRED) or check.database is None:
            return check
        previous = check.recorded or {}
        value = {
            "version": 1,
            "instance_id": previous.get("instance_id") or str(uuid.uuid4()),
            "db_id": check.database.db_id,
            "epoch": check.database.epoch,
            "install_fingerprint": install_fingerprint(self.database.path),
            "last_change_seq_seen": check.database.max_change_seq,
            "max_task_id_seen": check.database.max_task_id,
            "recorded_at": datetime.now().astimezone().isoformat(),
        }
        self.identity_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".identity-", dir=self.identity_file.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.identity_file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return IdentityCheck(IdentityStatus.PAIRED, check.database, value)
