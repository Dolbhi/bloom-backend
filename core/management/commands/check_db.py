"""
python manage.py check_db

Read-only health check of whatever database Django is pointed at. Use it to confirm a new
Supabase project is set up right before the first deploy:

    docker compose run --rm -e DATABASE_TARGET=supabase api python manage.py check_db

Prints each check as OK / WARN / FAIL and exits with an error if anything FAILs.
Never prints the password.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from core.db import unlocked_tables


class Command(BaseCommand):
    help = "Check the database connection, extensions, migrations and Row Level Security."

    def handle(self, *args, **opts):
        self.failed = False
        db = settings.DATABASES["default"]
        host, port = db.get("HOST") or "?", str(db.get("PORT") or "5432")
        self.stdout.write(f"Target: {settings.DATABASE_TARGET}  ->  {db.get('USER')}@{host}:{port}/{db.get('NAME')}\n")

        self._check_supabase_address(host, port)

        try:
            connection.ensure_connection()
        except Exception as exc:   # noqa: BLE001 - show any connection error plainly
            self.fail("Connect", f"{type(exc).__name__}: {str(exc).strip().splitlines()[0]}")
            raise CommandError("Could not connect. See 07-deploy-supabase-render.md, 'Troubleshooting'.")
        self.ok("Connect", "connected")

        with connection.cursor() as cur:
            cur.execute("SHOW server_version")
            version = cur.fetchone()[0]
            (self.ok if int(version.split(".")[0]) >= 15 else self.warn)("Postgres", version)

            # Our side of the link (app -> server/pooler), which is the hop that crosses the internet
            if connection.connection.pgconn.ssl_in_use:
                self.ok("SSL", "encrypted")
            elif host in ("db", "localhost", "127.0.0.1"):
                self.ok("SSL", "off (fine for the local Docker database)")
            else:
                self.fail("SSL", "connection is NOT encrypted; set DATABASE_SSL=True")

            cur.execute("SELECT e.extversion, n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = %s", ["postgis"])
            row = cur.fetchone()
            if row:
                self.ok("PostGIS", f"{row[0]} (schema {row[1]})")
            else:
                self.warn("PostGIS", "not enabled yet. Supabase: Database > Extensions > postgis (migrate also tries)")

            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'")
            row = cur.fetchone()
            if row:
                self.ok("pg_trgm", row[0])
            else:
                self.warn("pg_trgm", "not enabled yet (the plants migration enables it)")

        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if not executor.loader.applied_migrations:
            self.warn("Migrations", f"empty database: {len(pending)} migrations will run on first deploy")
        elif pending:
            self.warn("Migrations", f"{len(pending)} not applied yet (the next deploy applies them)")
        else:
            self.ok("Migrations", "all applied")

        if executor.loader.applied_migrations:
            open_tables = unlocked_tables()
            if open_tables:
                self.warn("RLS", f"off for {len(open_tables)} table(s): {', '.join(open_tables[:5])}{' ...' if len(open_tables) > 5 else ''}. Run migrate to fix")
            else:
                self.ok("RLS", "on for every Bloom table")

        if self.failed:
            raise CommandError("Some checks failed.")
        self.stdout.write(self.style.SUCCESS("\nDatabase looks good."))

    def _check_supabase_address(self, host, port):
        if "supabase" not in host:
            return
        if host.startswith("db.") and host.endswith(".supabase.co"):
            self.warn("Address", "direct connection: IPv6 only on the free plan, Render can't reach it. Use the Session pooler string")
        elif "pooler.supabase.com" in host and port == "6543":
            self.fail("Address", "transaction pooler (port 6543). Use the Session pooler string (port 5432)")
        elif "pooler.supabase.com" in host:
            self.ok("Address", "Supabase Session pooler")

    def ok(self, name, msg):
        self.stdout.write(f"  {self.style.SUCCESS('OK  ')}  {name:<11} {msg}")

    def warn(self, name, msg):
        self.stdout.write(f"  {self.style.WARNING('WARN')}  {name:<11} {msg}")

    def fail(self, name, msg):
        self.failed = True
        self.stdout.write(f"  {self.style.ERROR('FAIL')}  {name:<11} {msg}")
