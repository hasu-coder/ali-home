from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings


@dataclass
class HomeAssistantActionResult:
    success: bool
    verified: bool = False
    state: str | None = None
    error: str | None = None
    status_code: int | None = None


class HomeAssistantClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.home_assistant_enabled and self.settings.home_assistant_url and self.settings.home_assistant_token)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.home_assistant_token}", "Content-Type": "application/json"}

    async def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "reachable": False, "reason": "disabled_or_missing_token"}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{self.settings.home_assistant_url.rstrip('/')}/api/",
                    headers=self.headers,
                )
            return {"enabled": True, "reachable": response.is_success, "status_code": response.status_code}
        except httpx.HTTPError as exc:
            return {"enabled": True, "reachable": False, "error": exc.__class__.__name__}

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        if not self.enabled:
            return {"error": "home_assistant_disabled"}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.settings.home_assistant_url.rstrip('/')}/api/states/{entity_id}",
                headers=self.headers,
            )
            response.raise_for_status()
            return response.json()

    async def call_service(self, domain: str, service: str, service_data: dict[str, Any]) -> HomeAssistantActionResult:
        if not self.enabled:
            return HomeAssistantActionResult(success=False, error="home_assistant_disabled")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.settings.home_assistant_url.rstrip('/')}/api/services/{domain}/{service}",
                    headers=self.headers,
                    json=service_data,
                )
            if not response.is_success:
                return HomeAssistantActionResult(success=False, status_code=response.status_code, error=response.text[:300])
            return HomeAssistantActionResult(success=True, status_code=response.status_code)
        except httpx.HTTPError as exc:
            return HomeAssistantActionResult(success=False, error=exc.__class__.__name__)

    async def execute_intent(self, intent: dict[str, Any]) -> HomeAssistantActionResult:
        domain = intent.get("domain")
        service = intent.get("service")
        entity_id = intent.get("entity_id")
        if not domain or not service or not entity_id:
            return HomeAssistantActionResult(success=False, error="intent_not_executable")

        result = await self.call_service(domain, service, {"entity_id": entity_id})
        if not result.success:
            return result

        expected_state = intent.get("verify_state")
        if not expected_state:
            return result

        try:
            state = await self.get_state(entity_id)
        except Exception as exc:
            return HomeAssistantActionResult(success=False, error=f"verification_failed:{exc.__class__.__name__}")

        actual_state = state.get("state")
        if actual_state == expected_state:
            return HomeAssistantActionResult(success=True, verified=True, state=actual_state, status_code=result.status_code)
        return HomeAssistantActionResult(
            success=False,
            verified=True,
            state=actual_state,
            status_code=result.status_code,
            error=f"expected_{expected_state}_got_{actual_state}",
        )
