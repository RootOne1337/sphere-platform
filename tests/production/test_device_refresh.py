"""Runtime invariants on disposable PostgreSQL and Redis (opt-in)."""


async def test_device_refresh_rotates_and_cannot_be_reused(world):
    from backend.schemas.device_register import DeviceRegisterRequest
    from backend.services.device_registration_service import DeviceRegistrationService

    w = world
    async with w.sessions() as db:
        enrollment = await DeviceRegistrationService(db).register_device(
            w.org_a.id, DeviceRegisterRequest(fingerprint=w.suffix)
        )
        await db.commit()
    response = await w.client.post(
        "/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrollment.refresh_token}
    )
    assert response.status_code == 200, response.text
    assert response.json()["device_id"] == str(enrollment.device_id)
    assert response.json()["refresh_token"] != enrollment.refresh_token
    response = await w.client.post(
        "/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrollment.refresh_token}
    )
    assert response.status_code == 401
