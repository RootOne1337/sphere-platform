"""Bind a trusted tenant to one Session and reapply PostgreSQL LOCAL context."""

from uuid import UUID

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

_TENANT_KEY = "sphere.tenant_id"
_SET_CONTEXT = text("SELECT set_config('app.current_org_id', :org_id, true)")


def _apply_tenant(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    # after_begin runs for each real connection/transaction, including recovery.
    # Use the supplied Connection: Session I/O is not reentrant in this event.
    connection.execute(_SET_CONTEXT, {"org_id": session.info[_TENANT_KEY]})


async def bind_tenant_context(db: AsyncSession, org_id: str) -> None:
    """One tenant per Session; transaction-local DB state never persists in the pool.

    Call before tenant data access. Unscoped sessions are not made safe by this
    helper. First binding inside a savepoint is rejected: its rollback could
    remove the context while leaving the outer transaction alive.
    """
    tenant = str(UUID(org_id))
    session = db.sync_session
    previous = session.info.get(_TENANT_KEY)
    if previous is not None and previous != tenant:
        # expire_on_commit=False retains ORM identities across transactions.
        raise ValueError("Cannot change tenant within a Session; create a new Session")
    if previous is None:
        if db.in_nested_transaction():
            raise ValueError("Bind tenant before entering a savepoint")
        session.info[_TENANT_KEY] = tenant
        event.listen(session, "after_begin", _apply_tenant)

    if db.in_transaction():
        # An existing transaction may have begun before the binding was installed.
        await db.execute(_SET_CONTEXT, {"org_id": tenant})
    else:
        # Materializing the connection fires after_begin and installs LOCAL once.
        await db.connection()
