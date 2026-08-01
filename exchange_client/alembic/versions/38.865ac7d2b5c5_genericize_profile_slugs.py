"""genericize trading_profiles.name into stable id-based slugs

Renames every profile's ``name`` to a generic, id-derived slug (``profile<id>``)
so the human-meaningful label lives ONLY in ``display_name``. This removes the
confusion of two competing descriptive names (e.g. name ``4h_v19_tight_pullback``
vs display_name ``4hr_dip_v7_deep_dip_satellite``).

``name`` remains the cross-table key (there are no FKs on the ``profile_name``
string columns), so this is a pure DATA migration: the same string value is
rewritten everywhere it appears, in one transaction. The app is name-agnostic —
it uses whatever strings the DB holds — so no code change is required, but the
service MUST be restarted afterwards to rebuild the in-memory caches/Profile
manager (both keyed by name).

Reversibility: a temporary table ``_profile_slug_rename_backup`` captures the
old→new mapping during upgrade and is used by downgrade to restore the original
names, then dropped. Take a Neon branch before running regardless.

Revision ID: 865ac7d2b5c5
Revises: f4a1c8d92b6e
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '865ac7d2b5c5'
down_revision: Union[str, Sequence[str], None] = 'f4a1c8d92b6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Every table that keys rows by the profile NAME string ────────────────────
# (loose string columns — no FK, so each must be rewritten explicitly.)
# The ``extra`` clause protects sentinel values that are intentionally NOT a
# profile name — currently only settings.profile_name = '0' (means "global").
CHILD_TABLES: list[tuple[str, str]] = [
    ("positions", ""),
    ("trades", ""),
    ("orders", ""),
    ("symbol_configs", ""),
    ("circuit_breaker_config", ""),
    ("circuit_breaker_events", ""),
    ("app_user_mappings", ""),
    ("ai_signal_log", ""),
    ("ai_vs_rules_stats", ""),
    ("daily_balance_snapshots", ""),
    ("settings", "AND c.profile_name <> '0'"),
]


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # ── 1. Safety guard ──────────────────────────────────────────────────────
    # Fail loudly if any child table references a profile_name that has NO
    # matching trading_profiles.name. Those rows would be silently stranded on
    # a now-nonexistent old name after the rename. If the orphans are intended
    # historical rows (e.g. positions from a deleted profile) you can clean them
    # up first, or comment out this block to proceed knowingly.
    orphans: list[str] = []
    for table, extra in CHILD_TABLES:
        rows = conn.execute(sa.text(f"""
            SELECT c.profile_name AS pn, COUNT(*) AS n
            FROM {table} c
            WHERE c.profile_name IS NOT NULL
              {extra}
              AND NOT EXISTS (
                  SELECT 1 FROM trading_profiles tp WHERE tp.name = c.profile_name
              )
            GROUP BY c.profile_name
        """)).fetchall()
        for r in rows:
            orphans.append(f"  {table}: profile_name={r.pn!r} ({r.n} row(s))")
    if orphans:
        raise RuntimeError(
            "Aborting slug rename — found profile_name values with no matching "
            "trading_profiles.name (they would be stranded by the rename):\n"
            + "\n".join(orphans)
            + "\n\nClean up or reassign these rows first, or comment out the guard "
              "in this migration if the orphans are intentional historical records."
        )

    # ── 2. Capture the old→new mapping (makes downgrade possible) ─────────────
    op.execute("""
        CREATE TABLE _profile_slug_rename_backup AS
        SELECT id,
               name                      AS old_name,
               'profile' || id::text     AS new_name
        FROM trading_profiles
    """)

    # ── 3. Rewrite every child table: old_name → new_name ────────────────────
    # No uniqueness on these columns, so a single set-based UPDATE is safe.
    for table, extra in CHILD_TABLES:
        op.execute(f"""
            UPDATE {table} c
            SET profile_name = b.new_name
            FROM _profile_slug_rename_backup b
            WHERE c.profile_name = b.old_name
              {extra}
        """)

    # ── 4. Rename the parent, two-phase to avoid a transient UNIQUE clash ─────
    # trading_profiles.name is UNIQUE and non-deferrable, so a one-shot UPDATE
    # could momentarily duplicate a value if some old name happened to equal a
    # target slug. Bounce through a guaranteed-unique temp value first.
    op.execute("""
        UPDATE trading_profiles tp
        SET name = '__slugtmp_' || tp.id::text
    """)
    op.execute("""
        UPDATE trading_profiles tp
        SET name = b.new_name
        FROM _profile_slug_rename_backup b
        WHERE tp.id = b.id
    """)


def downgrade() -> None:
    """Restore the original profile names from the backup table."""
    # Reverse child rewrites: new_name → old_name.
    for table, extra in CHILD_TABLES:
        op.execute(f"""
            UPDATE {table} c
            SET profile_name = b.old_name
            FROM _profile_slug_rename_backup b
            WHERE c.profile_name = b.new_name
              {extra}
        """)

    # Reverse parent rename (two-phase again for the UNIQUE constraint).
    op.execute("""
        UPDATE trading_profiles tp
        SET name = '__slugtmp_' || tp.id::text
    """)
    op.execute("""
        UPDATE trading_profiles tp
        SET name = b.old_name
        FROM _profile_slug_rename_backup b
        WHERE tp.id = b.id
    """)

    op.execute("DROP TABLE IF EXISTS _profile_slug_rename_backup")
