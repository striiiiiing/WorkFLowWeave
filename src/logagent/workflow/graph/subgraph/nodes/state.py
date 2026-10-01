"""阶段结果的共享状态更新。"""


def phase(state, stage, **changes):
    return {
        "phase": {
            "stage": stage,
            "status": changes.get("status", state.get("status", "running")),
            "stopped": changes.get("stopped", False),
            "error": changes.get("error"),
        },
        **changes,
    }
