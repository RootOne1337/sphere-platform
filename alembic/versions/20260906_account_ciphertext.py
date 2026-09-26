"""Add unambiguous encrypted credential storage; backfill uses a separate key-aware tool."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_account_ciphertext"
down_revision = "20260906_vpn_intents"
branch_labels = None
depends_on = None


def upgrade():
    # No keys in migration history. NULL distinguishes every legacy password,
    # including values that happen to resemble a valid ciphertext prefix.
    op.add_column("game_accounts", sa.Column("password_ciphertext", sa.Text(), nullable=True))
    op.create_check_constraint("ck_account_no_plaintext_with_ciphertext", "game_accounts",
                               "password_ciphertext IS NULL OR password_encrypted = ''")


def downgrade():
    # Older writers/readers cannot interpret encrypted rows. Never erase tokens
    # or silently restore plaintext merely to make a schema downgrade succeed.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM game_accounts WHERE password_ciphertext IS NOT NULL) THEN
            RAISE EXCEPTION 'Encrypted account credentials prevent downgrade';
        END IF;
    END $$""")
    op.drop_constraint("ck_account_no_plaintext_with_ciphertext", "game_accounts", type_="check")
    op.drop_column("game_accounts", "password_ciphertext")
