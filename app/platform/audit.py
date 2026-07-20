from typing import Any

from ..audit import audit_service
from ..runtime_context import get_context


def platform_audit(
    event_name: str,
    *,
    actor: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    workspace_id: str | None = None,
    result: str = "success",
    changed_fields: dict[str, Any] | None = None,
) -> None:
    context = get_context()
    audit_service.record(
        event_name,
        context.request_id,
        actor=actor,
        target_type=target_type,
        target_id=target_id,
        workspace_id=workspace_id,
        correlation_id=context.correlation_id,
        result=result,
        changed_fields=changed_fields or {},
    )
