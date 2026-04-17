#!/usr/bin/env python3
"""restore_memory_backup.py — Disaster-recovery restore for data/memory/memory.db.

Usage
-----
  # List available backups (newest first, with size + sha256):
  python scripts/restore_memory_backup.py --list

  # Dry-run: what would be restored?
  python scripts/restore_memory_backup.py --from memory-20260417-1144.db --dry-run

  # Restore to the default target (backs up current DB first):
  python scripts/restore_memory_backup.py --from memory-20260417-1144.db

  # Restore to a custom path:
  python scripts/restore_memory_backup.py --from memory-20260417-1144.db --to /tmp/test.db

  # Overwrite a non-empty target without prompting:
  python scripts/restore_memory_backup.py --from memory-20260417-1144.db --force

  # Take a fresh backup snapshot right now (same as the daemon does):
  python scripts/restore_memory_backup.py --snapshot

Safety contract
---------------
* Refuses to overwrite a non-empty target unless ``--force`` is given.
* Before overwriting, backs up the existing target to
  ``<target>.pre-restore-<timestamp>.db``.
* Verifies the restored DB with PRAGMA integrity_check.
* Prints row counts for the main tables so you can sanity-check data integrity.
* No writes to the live source DB. Always read-only on the backup files.
* Exit codes: 0=success, 1=error, 2=user aborted.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


# ── Project root resolution ──────────────────────────────────────────────────

def _project_root() -> Path:
    """Walk up from this script to find the agent-cli root (contains .venv)."""
    here = Path(__file__).resolve().parent
    # scripts/ lives directly under agent-cli/
    root = here.parent
    if (root / ".venv").exists() or (root / "daemon").exists():
        return root
    # Fallback: cwd
    return Path.cwd()


PROJECT_ROOT = _project_root()
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "memory" / "backups"
DEFAULT_TARGET = PROJECT_ROOT / "data" / "memory" / "memory.db"

# Tables shown in the post-restore row-count report (existence checked at runtime)
MAIN_TABLES = [
    "lessons",
    "events",
    "learnings",
    "action_log",
    "account_snapshots",
    "observations",
    "summaries",
    "execution_traces",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _backup_files(backup_dir: Path) -> list[Path]:
    """Return .db files in backup_dir, excluding .tmp/.shm/.wal, newest first."""
    if not backup_dir.is_dir():
        return []
    files = [
        p for p in backup_dir.iterdir()
        if p.suffix == ".db"
        and not p.name.endswith(".tmp")
        and p.is_file()
    ]
    # Sort by mtime descending (newest first)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _is_empty_db(path: Path) -> bool:
    """Return True if path does not exist or is an empty/zero-byte file."""
    if not path.exists():
        return True
    if path.stat().st_size == 0:
        return True
    # Also consider it "empty" if SQLite has no user tables
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        finally:
            conn.close()
        return count == 0
    except sqlite3.DatabaseError:
        # Can't open → not a valid SQLite DB, treat as non-empty for safety
        return False


def _integrity_check(path: Path) -> tuple[bool, str]:
    """Run PRAGMA integrity_check. Returns (ok, message)."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return False, f"DatabaseError: {exc}"
    messages = [r[0] for r in rows]
    if messages == ["ok"]:
        return True, "ok"
    return False, "; ".join(messages[:5])


def _row_counts(path: Path) -> dict[str, int | str]:
    """Return row counts for MAIN_TABLES that exist in the DB."""
    counts: dict[str, int | str] = {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            existing = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in MAIN_TABLES:
                if table in existing:
                    counts[table] = conn.execute(
                        f"SELECT COUNT(*) FROM \"{table}\""
                    ).fetchone()[0]
                else:
                    counts[table] = "—"
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        counts["_error"] = str(exc)
    return counts


def _pre_restore_backup_path(target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Use target.name (e.g. "existing.db") as the stem so the backup lands at
    # "existing.db.pre-restore-<ts>.db" — not "existing.pre-restore-<ts>.db"
    # which `with_suffix` produces by replacing the final .db extension.
    return target.parent / f"{target.name}.pre-restore-{ts}.db"


# ── Sub-commands ─────────────────────────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> int:
    backup_dir = Path(args.backup_dir)
    files = _backup_files(backup_dir)
    if not files:
        print(f"No backups found in {backup_dir}")
        return 0

    print(f"{'FILENAME':<40}  {'SIZE':>10}  {'MODIFIED':<20}  SHA256 (first 16)")
    print("-" * 96)
    for p in files:
        stat = p.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        digest = _sha256(p)[:16]
        print(f"{p.name:<40}  {_human_size(stat.st_size):>10}  {mtime:<20}  {digest}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Take a fresh backup snapshot right now using the iterator."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from daemon.iterators.memory_backup import MemoryBackupIterator
    except ImportError as exc:
        print(f"ERROR: cannot import MemoryBackupIterator: {exc}", file=sys.stderr)
        return 1

    it = MemoryBackupIterator()
    it.on_start(ctx=None)
    result = it.run_once()
    if result.get("skipped"):
        print(f"SKIP: {result.get('reason')}")
        return 1
    ok = result.get("integrity_ok", False)
    snap = result.get("snapshot", "?")
    print(f"Snapshot: {snap}")
    print(f"Size:     {_human_size(result.get('bytes', 0))}")
    print(f"Integrity: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def cmd_restore(args: argparse.Namespace) -> int:
    backup_dir = Path(args.backup_dir)
    target = Path(args.to)

    # Resolve source backup
    source = backup_dir / args.from_backup
    if not source.exists():
        # Maybe user supplied an absolute path
        source_abs = Path(args.from_backup)
        if source_abs.exists():
            source = source_abs
        else:
            print(
                f"ERROR: backup not found.\n"
                f"  Tried: {backup_dir / args.from_backup}\n"
                f"         {Path(args.from_backup).resolve()}\n"
                f"Run --list to see available backups.",
                file=sys.stderr,
            )
            return 1

    print(f"Source backup : {source}")
    print(f"Target        : {target}")
    print(f"Force overwrite: {'yes' if args.force else 'no'}")
    print()

    # ── Dry-run ──────────────────────────────────────────────────────────────
    if args.dry_run:
        ic_ok, ic_msg = _integrity_check(source)
        counts = _row_counts(source)
        print(f"[DRY RUN] Backup integrity_check : {'PASS' if ic_ok else 'FAIL'} ({ic_msg})")
        print(f"[DRY RUN] Backup row counts:")
        for table, n in counts.items():
            print(f"  {table:<30} {n}")
        print()
        if _is_empty_db(target):
            print("[DRY RUN] Target is empty — restore would proceed without --force.")
        else:
            if args.force:
                pre = _pre_restore_backup_path(target)
                print(f"[DRY RUN] Target is non-empty. Would save pre-restore backup to:")
                print(f"          {pre}")
            else:
                print(
                    "[DRY RUN] Target is non-empty. Would require --force to proceed.\n"
                    "          A pre-restore backup would be saved automatically."
                )
        return 0

    # ── Safety: refuse non-empty target without --force (before touching anything) ─
    if not _is_empty_db(target):
        if not args.force:
            sys.stdout.flush()
            print(
                f"ERROR: target {target} is non-empty.\n"
                "       Pass --force to overwrite (a pre-restore backup will be saved).",
                file=sys.stderr,
            )
            sys.stderr.flush()
            return 2

    # ── Verify source integrity before writing ────────────────────────────────
    print("Verifying source backup integrity...")
    ic_ok, ic_msg = _integrity_check(source)
    if not ic_ok:
        print(
            f"ERROR: source backup failed integrity_check: {ic_msg}\n"
            "       Choose a different backup or investigate forensically.",
            file=sys.stderr,
        )
        return 1
    print(f"  integrity_check: PASS")

    # ── Save pre-restore backup if overwriting a non-empty target ─────────────
    if not _is_empty_db(target):
        # --force was already confirmed above; save pre-restore backup
        pre = _pre_restore_backup_path(target)
        print(f"Saving pre-restore backup to: {pre}")
        shutil.copy2(str(target), str(pre))
        ic2_ok, ic2_msg = _integrity_check(pre)
        if not ic2_ok:
            print(
                f"WARNING: pre-restore backup integrity_check FAILED ({ic2_msg}).\n"
                "         The live DB may already be corrupt. Proceeding anyway.",
                file=sys.stderr,
            )
        else:
            print(f"  Pre-restore backup integrity_check: PASS ({pre.name})")

    # ── Perform restore via SQLite online-backup API ──────────────────────────
    print(f"\nRestoring {source.name} -> {target}...")
    target.parent.mkdir(parents=True, exist_ok=True)

    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(str(target))
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()

    # ── Verify restored DB ────────────────────────────────────────────────────
    print("Verifying restored database...")
    ic_ok, ic_msg = _integrity_check(target)
    print(f"  integrity_check: {'PASS' if ic_ok else 'FAIL'} ({ic_msg})")

    counts = _row_counts(target)
    print("\nRow counts in restored DB:")
    for table, n in counts.items():
        print(f"  {table:<30} {n}")

    if not ic_ok:
        print(
            f"\nFAIL: integrity_check failed after restore. "
            "Investigate before relying on this DB.",
            file=sys.stderr,
        )
        return 1

    print(f"\nPASS: {target} restored from {source.name} and verified clean.")
    return 0


# ── CLI wiring ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="restore_memory_backup.py",
        description=(
            "List, verify, and restore memory.db backups.\n"
            "Default backup dir: data/memory/backups/\n"
            "Default restore target: data/memory/memory.db\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/restore_memory_backup.py --list\n"
            "  python scripts/restore_memory_backup.py --from memory-20260417-1144.db --dry-run\n"
            "  python scripts/restore_memory_backup.py --from memory-20260417-1144.db --to /tmp/test.db\n"
            "  python scripts/restore_memory_backup.py --from memory-20260417-1144.db --force\n"
            "  python scripts/restore_memory_backup.py --snapshot\n"
        ),
    )
    p.add_argument(
        "--backup-dir",
        default=str(DEFAULT_BACKUP_DIR),
        metavar="DIR",
        help=f"Directory containing backup files (default: {DEFAULT_BACKUP_DIR})",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List available backups sorted newest first with size + sha256.",
    )
    p.add_argument(
        "--snapshot",
        action="store_true",
        help="Take a fresh backup snapshot now (calls the iterator directly).",
    )
    p.add_argument(
        "--from",
        dest="from_backup",
        metavar="FILENAME",
        help=(
            "Backup filename to restore from (e.g. memory-20260417-1144.db). "
            "Resolved relative to --backup-dir unless an absolute path."
        ),
    )
    p.add_argument(
        "--to",
        default=str(DEFAULT_TARGET),
        metavar="PATH",
        help=f"Target path to restore into (default: {DEFAULT_TARGET})",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help=(
            "Allow overwriting a non-empty target. "
            "The existing target is backed up to <target>.pre-restore-<ts>.db first."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing anything.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        return cmd_list(args)

    if args.snapshot:
        return cmd_snapshot(args)

    if not args.from_backup:
        parser.print_help()
        print(
            "\nERROR: specify --list, --snapshot, or --from <backup_filename>.",
            file=sys.stderr,
        )
        return 1

    return cmd_restore(args)


if __name__ == "__main__":
    sys.exit(main())
