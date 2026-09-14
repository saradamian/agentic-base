"""Schema migrations, shipped inside the package so every deployment carries its own.

A table created from the models on first start is correct once. The first change to a model after
that does nothing to a database that already exists, and the service then fails on a missing
column in production, at the first write that needs it. So the schema is versioned with Alembic,
and the service checks the version before it serves:

* ``agentic-base-migrate`` upgrades the configured database to the newest revision. A deployment
  runs it before the new version starts; the chart does so as a hook.
* On start, a SQLite database, which only ever means local development, is migrated in place. Any
  other database must already be at the newest revision, or the service refuses to start and
  names the command, rather than serving against a schema it was not built for.

A model change without a migration fails the suite: the test that migrates an empty database and
compares it with the models finds the difference.
"""
