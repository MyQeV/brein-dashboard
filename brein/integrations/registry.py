"""Run a service type's test_connection by id."""

from brein.extensions import load_extensions


async def test_service(
    service_id: str, base_url: str, api_key: str
) -> tuple[bool, str]:
    service_type = load_extensions().service_types.get(service_id)
    if service_type is None:
        return False, "Unknown service"
    return await service_type.test_connection(base_url, api_key)
