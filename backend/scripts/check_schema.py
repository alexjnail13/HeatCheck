"""
Compare the models against the database DATABASE_URL points at.

Schema drift is silent until something queries the missing piece — a model
column that was never created, a table left behind by an old create_all, or
simply being connected to a different database than you think. This prints the
difference in both directions.

    python -m scripts.check_schema

Exit 0 = models and database agree on every table and column.
Exit 1 = drift found; the output says exactly what and where.
"""

import sys

from sqlalchemy import create_engine, inspect

from app.config import settings
from app.database.session import Base
from app.database import models  # noqa: F401  (registers tables on Base.metadata)


def redact(url: str) -> str:
    """Show which host/database we hit without printing the password."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.split("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def main() -> int:
    url = settings.DATABASE_URL
    print(f"Connected to: {redact(url)}\n")

    engine = create_engine(url)
    insp = inspect(engine)
    db_tables = set(insp.get_table_names())
    model_tables = set(Base.metadata.tables)

    problems = 0

    missing_tables = sorted(model_tables - db_tables)
    if missing_tables:
        problems += len(missing_tables)
        print("TABLES IN MODELS BUT NOT IN DATABASE:")
        for t in missing_tables:
            print(f"  - {t}")
        print("  -> run: alembic upgrade head\n")

    extra_tables = sorted(db_tables - model_tables - {"alembic_version"})
    if extra_tables:
        print("TABLES IN DATABASE BUT NOT IN MODELS (informational):")
        for t in extra_tables:
            print(f"  - {t}")
        print()

    print("COLUMN CHECK")
    for table_name in sorted(model_tables & db_tables):
        model_cols = {c.name for c in Base.metadata.tables[table_name].columns}
        db_cols = {c["name"] for c in insp.get_columns(table_name)}

        missing = sorted(model_cols - db_cols)
        extra = sorted(db_cols - model_cols)

        if not missing and not extra:
            print(f"  OK   {table_name} ({len(model_cols)} columns)")
            continue

        print(f"  DRIFT {table_name}")
        if missing:
            problems += len(missing)
            print(f"        models have, database MISSING: {missing}")
        if extra:
            print(f"        database has, models missing:  {extra}")

    # Row counts help identify WHICH database this is.
    print("\nROW COUNTS")
    from sqlalchemy import text

    with engine.connect() as conn:
        for table_name in sorted(model_tables & db_tables):
            try:
                n = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()
                print(f"  {table_name}: {n}")
            except Exception as exc:
                print(f"  {table_name}: <error: {type(exc).__name__}>")

    # Which migration does this database think it's on?
    print("\nALEMBIC VERSION")
    with engine.connect() as conn:
        try:
            rows = conn.execute(text("SELECT version_num FROM alembic_version")).all()
            print(f"  {[r[0] for r in rows] or '<empty>'}")
        except Exception:
            print("  <no alembic_version table — this DB has never been migrated>")

    print("\n" + "=" * 60)
    if problems:
        print(f"RESULT: {problems} drift issue(s) found.")
        return 1
    print("RESULT: OK — models and database agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
