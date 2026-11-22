"""Reserve global VPN addresses before provider effects; reject legacy conflicts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260906_vpn_intents"
down_revision = "20260906_task_accounting"
branch_labels = None
depends_on = None


def upgrade():
    # The cast and unique index deliberately fail atomically for malformed or
    # duplicate legacy addresses. Never choose a winning tenant or delete peers.
    op.alter_column("vpn_peers", "tunnel_ip", type_=postgresql.INET(),
                    existing_type=sa.String(45), postgresql_using="tunnel_ip::inet")
    op.alter_column("vpn_peers", "status", type_=sa.String(32), existing_type=sa.String(8))
    op.add_column("vpn_peers", sa.Column("operation_id", sa.Uuid(), nullable=True))
    op.add_column("vpn_peers", sa.Column("split_tunnel", sa.Boolean(), nullable=True))
    op.create_check_constraint("ck_vpn_ip_is_host", "vpn_peers",
        "tunnel_ip IS NULL OR masklen(tunnel_ip) = CASE WHEN family(tunnel_ip) = 4 THEN 32 ELSE 128 END")
    op.create_index("uq_vpn_held_ip", "vpn_peers", ["tunnel_ip"], unique=True,
                    postgresql_where=sa.text("status <> 'FREE'"))


def downgrade():
    # Older code cannot safely interpret pending intents. Do not discard them.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM vpn_peers WHERE status IN ('PROVISIONING', 'REVOKING')) THEN
            RAISE EXCEPTION 'Reconcile VPN intents before downgrade';
        END IF;
    END $$""")
    op.drop_index("uq_vpn_held_ip", table_name="vpn_peers")
    op.drop_constraint("ck_vpn_ip_is_host", "vpn_peers", type_="check")
    op.drop_column("vpn_peers", "split_tunnel")
    op.drop_column("vpn_peers", "operation_id")
    op.alter_column("vpn_peers", "status", type_=sa.String(8), existing_type=sa.String(32))
    op.alter_column("vpn_peers", "tunnel_ip", type_=sa.String(45),
                    existing_type=postgresql.INET(), postgresql_using="host(tunnel_ip)")
