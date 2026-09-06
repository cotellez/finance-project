"""Cross-cutting safe JSON persistence helpers.

Provides:
- project_root(): a stable anchor for runtime data files so file locations do
  not depend on the process working directory (CWD-independent).
- resolve_path(): resolves a caller ``db_path`` at CALL TIME, so monkeypatching
  or parameter injection takes effect (defaults are NOT bound at import time).
- atomic_write_json(): temp-file + fsync + os.replace writes (no partial files).
- append_audit(): append-only audit trail of data mutations.
- FileLock: advisory, cross-platform lock for read-modify-write sections.
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Anchored to the repository root, NOT the process CWD.
# src/finance/jsonstore.py -> parents[2] == project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_LOG = PROJECT_ROOT / "data_audit.jsonl"


def resolve_path(db_path: Path | str | None, default: Path) -> Path:
    """Resolve a caller-supplied path (or None) to the fallback default at call time."""
    if db_path is None:
        return default
    return Path(db_path)


def _under_project_root(target: Path) -> bool:
    try:
        return target.resolve().is_relative_to(PROJECT_ROOT.resolve())
    except (OSError, ValueError):
        return False


def append_audit(target: Path, action: str, detail: str = "") -> None:
    """Append one audit record to the project audit log (best-effort, never raises).

    Only targets inside the project root are audited so external/temp paths used
    by tests and tooling do not pollute the ledger.
    """
    target = Path(target)
    if not _under_project_root(target):
        return
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": str(target.resolve()),
        "detail": detail,
    }
    try:
        log = DEFAULT_AUDIT_LOG
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        # Auditing must never block the primary operation.
        pass


def atomic_write_json(
    db_path: Path | str,
    data: Any,
    *,
    audit: bool = False,
    audit_action: str = "write",
    audit_detail: str = "",
) -> None:
    """Write ``data`` to ``db_path`` atomically, optionally appending an audit record."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(db_path.parent), prefix=db_path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, db_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if audit:
        append_audit(db_path, audit_action, audit_detail)


class FileLock:
    """Advisory cross-platform lock via ``<target>.lock``.

    Uses ``msvcrt`` on Windows and ``fcntl`` on POSIX. Single-writer protection
    for read-modify-write sections; the lock file is intentionally left behind
    (harmless) so a second process can acquire it immediately.
    """

    def __init__(self, target: Path | str, timeout: float = 10.0, retry: float = 0.05):
        self.lock_path = Path(str(target) + ".lock")
        self.timeout = timeout
        self.retry = retry
        self._fh = None

    def __enter__(self) -> "FileLock":
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.lock_path.open("a+", encoding="utf-8")
        try:
            # msvcrt.locking requires at least one byte to exist in the file.
            self._fh.seek(0, os.SEEK_END)
            if self._fh.tell() == 0:
                self._fh.write("\0")
            self._fh.flush()
        except (OSError, ValueError):
            pass
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self._fh.close()
                    raise IOError(
                        f"Could not acquire lock on {self.lock_path} within {self.timeout}s "
                        "(another process may be writing the same data file)."
                    ) from None
                time.sleep(self.retry)

    def __exit__(self, *exc) -> None:
        try:
            if self._fh is None:
                return
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            if self._fh is not None:
                self._fh.close()
                self._fh = None