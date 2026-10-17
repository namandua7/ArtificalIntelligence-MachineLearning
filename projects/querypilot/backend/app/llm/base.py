"""Provider-neutral LLM interface used by the agent and the Performance Doctor.

The agent keeps its conversation as a list of `AgentMessage`s; each provider translates that
into its own wire format. `LLMTurn.raw` lets a provider replay its native message verbatim
(Gemini needs this to keep "thought signatures" intact across tool-calling turns).
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (object)


@dataclass
class ToolCall:
    id: str | None
    name: str
    args: dict[str, Any]


@dataclass
class LLMTurn:
    text: str
    tool_calls: list[ToolCall]
    raw: Any = None


@dataclass
class AgentMessage:
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    turn: LLMTurn | None = None
    # role == "tool": (call, result) pairs answering the previous assistant turn
    results: list[tuple[ToolCall, dict[str, Any]]] = field(default_factory=list)


# Called with (seconds_to_wait, reason) when a provider backs off, so the UI can show it.
RetryCallback = Callable[[float, str], None]


class LLMError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str
    model: str

    # Gemini can be forced to always call a tool; Ollama models sometimes reply in plain text.
    supports_forced_tools: bool = False

    @abstractmethod
    def chat_with_tools(
        self,
        system: str,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
        on_retry: RetryCallback | None = None,
    ) -> LLMTurn: ...

    @abstractmethod
    def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        on_retry: RetryCallback | None = None,
    ) -> T: ...
