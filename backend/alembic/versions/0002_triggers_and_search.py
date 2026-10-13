"""append-only triggers and full-text search

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION byg_forbid_mutation() RETURNS trigger AS $$
        BEGIN
            -- Cascading deletes from a parent are allowed only when the parent row itself is removed
            -- (e.g. an event is purged); direct UPDATE/DELETE on history rows is never allowed.
            IF TG_OP = 'UPDATE' THEN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END IF;
            IF TG_OP = 'DELETE' AND pg_trigger_depth() = 1 THEN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("claim_status_history", "audit_logs"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION byg_forbid_mutation();
            """
        )
    op.execute(
        """
        ALTER TABLE events ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(tags_text, '') || ' ' || coalesce(organizer_name, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(description, '') || ' ' || coalesce(city, '') || ' ' ||
                                              coalesce(country, '') || ' ' || coalesce(prize_details, '')), 'C')
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_events_search_vector ON events USING GIN (search_vector)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_events_search_vector")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS search_vector")
    for table in ("claim_status_history", "audit_logs"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS byg_forbid_mutation()")
