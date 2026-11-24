"""
Database helpers that are about Postgres/Supabase itself, not about Bloom's data.

lock_down_tables(): Supabase publishes every table in the "public" schema through its Data API
(PostgREST, used with the project's anon key). Bloom only talks to the database through Django,
so we switch on Row Level Security for our tables. With RLS on and no policies, the Data API
can read nothing, while Django (which connects as the table owner) is unaffected.
It runs after every `migrate` (see core/apps.py), so tables added later are covered too.
Locally it's harmless and keeps the dev database behaving like Supabase.
"""
from django.db import connections

# Our tables in "public": owned by the user Django connects as, RLS still off,
# and not part of an extension (e.g. PostGIS's spatial_ref_sys, which we must not touch).
UNLOCKED_TABLES_SQL = """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
      AND pg_get_userbyid(c.relowner) = current_user
      AND NOT c.relrowsecurity
      AND NOT EXISTS (
          SELECT 1 FROM pg_depend d
          WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e'
      )
    ORDER BY c.relname
"""


def unlocked_tables(using="default"):
    with connections[using].cursor() as cur:
        cur.execute(UNLOCKED_TABLES_SQL)
        return [row[0] for row in cur.fetchall()]


def lock_down_tables(using="default"):
    """Enables RLS on our public tables that don't have it yet. Returns the table names changed."""
    connection = connections[using]
    if connection.vendor != "postgresql":
        return []
    tables = unlocked_tables(using)
    with connection.cursor() as cur:
        for name in tables:
            cur.execute(f"ALTER TABLE {connection.ops.quote_name(name)} ENABLE ROW LEVEL SECURITY")
    return tables
