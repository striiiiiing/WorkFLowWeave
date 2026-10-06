from workflowweave.models import ErrorInfo, RecoveryAvailability
from tests.interaction.test_interaction import Lifecycle, _client


def test_recovery_query_is_read_only_and_returns_material_reason():
    lifecycle = Lifecycle()
    calls = []

    async def eligibility(session_id):
        calls.append(session_id)
        return RecoveryAvailability(
            available=False,
            reason=ErrorInfo(code="recovery_unavailable", message="原配置快照不可用"),
        )

    lifecycle.workflow.recovery_availability = eligibility
    with _client(lifecycle) as client:
        response = client.get("/api/sessions/session-1/recovery")
    assert response.status_code == 200
    assert response.json() == {
        "checkpoint_expires_at": None,
        "available": False,
        "reason": {"code": "recovery_unavailable", "message": "原配置快照不可用", "details": {}},
    }
    assert calls == ["session-1"] and lifecycle.workflow.recovered == []
