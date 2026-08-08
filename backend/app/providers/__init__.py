"""
Data providers.

Each module here talks to exactly one third-party source and returns plain
dataclasses — never ORM objects, never raw provider JSON. Ingestion jobs consume
those dataclasses and own all database writes.

That boundary is what makes the provider swappable: when MySportsFeeds or
BALLDONTLIE replaces (or joins) cdn.nba.com, only a module in this package
changes. The ingestion jobs, the models, and the API never learn a provider's
field names.
"""
