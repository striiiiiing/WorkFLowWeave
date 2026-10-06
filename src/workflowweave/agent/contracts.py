"""Agent value objects; task and storage handles live with their owners."""

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from workflowweave.models import AIConfig


def _immutable(*args, **kwargs):
    raise TypeError("turn snapshot is immutable")


class FrozenDict(dict):
    """JSON-compatible mapping that cannot be changed through nested references."""

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self


class FrozenList(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = _immutable
    reverse = sort = __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo):
        return self


@lru_cache
def _frozen_model(model_type):
    return type(f"Frozen{model_type.__name__}", (model_type,), {
        "__module__": __name__, "model_config": {**model_type.model_config, "frozen": True},
    })


def freeze(value):
    """Capture nested configuration without creating a second defaults definition."""
    if isinstance(value, BaseModel):
        return _frozen_model(type(value)).model_construct(**{
            name: freeze(getattr(value, name)) for name in type(value).model_fields
        })
    if isinstance(value, dict):
        return FrozenDict((key, freeze(item)) for key, item in value.items())
    if isinstance(value, list):
        return FrozenList(freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class TurnSnapshot:
    config: Any
    ai_config: Any | None
    model: str | None
    summary_ai_config: Any | None
    summary_model: str | None
    tools_generation: int | None
    declarations: tuple
    gateway: Any | None


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    session_id: str
    turn_id: str
    branch_id: str
    workflow_session_id: str | None = None
    model: str | None = None
    tools_generation: int | None = None
    workspace: str | None = None

    def document(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(slots=True)
class SessionView:
    """Rebuildable session metadata, with no locks, tasks or event log."""

    session_id: str
    branch_id: str
    model: str | None
    workflow_session_id: str | None
    workflow_input: Any
    created_at: str
    updated_at: str
    title: str = ""
    status: str = "created"
    turn_id: str | None = None
    parent_session_id: str | None = None
    parent_turn_id: str | None = None
    parent_branch_id: str | None = None
    parent_event_id: int | None = None
    workflow_task_id: str | None = None
    ai_config: AIConfig | None = None
    system_prompt: str = ""
    input_prompt: str = "{input}"
    user_prompt: str = ""
    tool_names: list[str] | None = None

    @property
    def session_kind(self) -> str:
        if self.workflow_session_id is None:
            return "standalone"
        return "workflow_subtask" if self.workflow_task_id is not None else "workflow_continue"
