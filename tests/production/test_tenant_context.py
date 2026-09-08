"""Runtime invariants on disposable PostgreSQL and Redis (opt-in)."""


async def test_tenant_context_is_transaction_local(world):
    from sqlalchemy import text

    from backend.core.dependencies import get_tenant_db

    async with world.sessions() as db:
        await get_tenant_db(db=db, current_user=world.users["viewer"])
        assert await db.scalar(text("select current_setting('app.current_org_id', true)")) == str(
            world.org_a.id
        )
        await db.commit()
        # The same Session retains its tenant binding; a fresh Session must not.
        assert await db.scalar(text("select current_setting('app.current_org_id', true)")) == str(
            world.org_a.id
        )
    async with world.sessions() as db:
        assert await db.scalar(text("select current_setting('app.current_org_id', true)")) in (
            None,
            "",
        )
