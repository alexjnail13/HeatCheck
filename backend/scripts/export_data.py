"""
Export every table to CSV, and restore from those CSVs.

Render's free Postgres expires 30 days after creation and supports NO backups,
so the only copy of anything is whatever you export before the 14-day grace
period ends. This uses SQLAlchemy rather than pg_dump so it needs nothing
installed beyond the project's own requirements.

    python -m scripts.export_data --out ../data_export      # save everything
    python -m scripts.export_data --restore ../data_export  # load into a new DB

Restore is ordered to respect foreign keys (teams before games, games before
stats) and preserves primary keys, so relationships survive the move.

Worth knowing: most of this data is REPRODUCIBLE from the pipelines
(fetch_teams -> fetch_games -> seed_pbp -> seed_boxscores). Exporting is just
much faster than re-fetching ~220,000 rows from a rate-limited API.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import inspect, text

from app.database.session import SessionLocal, describe_database, engine

# Dependency order: a table may only be written after everything it references.
TABLE_ORDER = [
    "teams",
    "games",
    "users",
    "players",
    "team_external_ids",
    "game_external_ids",
    "player_external_ids",
    "play_by_play",
    "team_game_stats",
    "player_game_stats",
    "game_state_snapshots",
]


def ordered_tables(existing: set[str]) -> list[str]:
    """Known tables in dependency order, plus any others we didn't anticipate."""
    ordered = [t for t in TABLE_ORDER if t in existing]
    ordered += sorted(existing - set(ordered) - {"alembic_version"})
    return ordered


def export(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    insp = inspect(engine)
    tables = ordered_tables(set(insp.get_table_names()))

    total = 0
    with engine.connect() as conn:
        for table in tables:
            columns = [c["name"] for c in insp.get_columns(table)]
            rows = conn.execute(text(f'SELECT * FROM "{table}"')).fetchall()

            path = out_dir / f"{table}.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(columns)
                writer.writerows(rows)

            total += len(rows)
            print(f"  {table:<24} {len(rows):>8,} rows -> {path.name}")

    print(f"\nExported {total:,} rows across {len(tables)} tables to {out_dir}")
    return 0


def restore(in_dir: Path) -> int:
    if not in_dir.exists():
        print(f"No such directory: {in_dir}")
        return 1

    # Schema is owned by Alembic. Creating tables here would leave the database
    # untracked (no alembic_version row), which is the drift we keep paying for.
    insp = inspect(engine)
    if not insp.get_table_names():
        print("Target database has no tables. Run `alembic upgrade head` first.")
        return 1
    existing = set(insp.get_table_names())
    tables = [t for t in ordered_tables(existing) if (in_dir / f"{t}.csv").exists()]

    db = SessionLocal()
    total = 0
    try:
        for table in tables:
            path = in_dir / f"{table}.csv"
            with path.open(newline="", encoding="utf-8") as fh:
                reader = csv.reader(fh)
                columns = next(reader)
                rows = list(reader)

            if not rows:
                print(f"  {table:<24} empty, skipped")
                continue

            col_list = ", ".join(f'"{c}"' for c in columns)
            placeholders = ", ".join(f":{c}" for c in columns)
            stmt = text(f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})')

            payload = []
            for row in rows:
                # Empty CSV cells are NULLs, not empty strings — otherwise a
                # nullable integer column would reject "".
                payload.append(
                    {c: (v if v != "" else None) for c, v in zip(columns, row)}
                )

            db.execute(stmt, payload)
            db.commit()
            total += len(payload)
            print(f"  {table:<24} {len(payload):>8,} rows restored")

        # Rows were inserted with explicit ids, which leaves Postgres sequences
        # pointing at 1 — the next natural insert would collide. Fast-forward
        # each sequence past the highest id we just wrote.
        if engine.dialect.name == "postgresql":
            for table in tables:
                cols = {c["name"] for c in inspect(engine).get_columns(table)}
                if "id" not in cols:
                    continue
                db.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM \"{table}\"), 1))"
                    )
                )
            db.commit()
            print("\n  id sequences fast-forwarded past the restored rows")

        print(f"\nRestored {total:,} rows across {len(tables)} tables")
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="directory to write CSVs into")
    parser.add_argument("--restore", type=Path, help="directory to restore CSVs from")
    args = parser.parse_args()

    print(f"Target database: {describe_database()}\n")

    if args.out:
        return export(args.out)
    if args.restore:
        return restore(args.restore)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
