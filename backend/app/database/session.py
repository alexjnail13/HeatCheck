from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def describe_database(url: str | None = None) -> str:
    """
    Human-readable target for the current DATABASE_URL, password removed.

    Every pipeline script prints this before doing anything. DATABASE_URL is
    routinely overridden per shell session ($env:DATABASE_URL=...), and that
    override dies with the window — so "which database am I about to write to?"
    is a question worth answering out loud rather than inferring from a stack
    trace after the fact.
    """
    url = url or settings.DATABASE_URL

    if url.startswith("sqlite"):
        return f"sqlite ({url.split('///')[-1] or 'in-memory'})"

    try:
        scheme, rest = url.split("://", 1)
        creds, hostpart = rest.split("@", 1)
        user = creds.split(":", 1)[0]
        host = hostpart.split("/", 1)[0]
        dbname = hostpart.split("/", 1)[1].split("?")[0] if "/" in hostpart else "?"
    except (ValueError, IndexError):
        return "<unparseable DATABASE_URL>"

    # Render's managed Postgres hostnames are externally routable; a local one
    # is not. Worth calling out, since it's the difference between a scratch
    # database and the live one.
    if "localhost" in host or "127.0.0.1" in host:
        location = "LOCAL"
    elif "render.com" in host or "oregon-postgres" in host:
        location = "RENDER (production)"
    else:
        location = "remote"

    return f"{scheme}://{user}:***@{host}/{dbname}  [{location}]"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()