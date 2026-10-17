"""Sanity-check the configured LLM: python -m app.scripts.check_llm

For Gemini it lists the models your key can use for generateContent, then makes one tiny
function-calling request with the configured GEMINI_MODEL.
"""

from app.config import settings
from app.llm import get_llm
from app.llm.base import AgentMessage, ToolSpec


def main() -> None:
    print(f"Provider: {settings.llm_provider}")
    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            raise SystemExit("GEMINI_API_KEY is empty in backend/.env")
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        names = sorted(
            m.name.removeprefix("models/")
            for m in client.models.list()
            if "generateContent" in (m.supported_actions or [])
        )
        print("Models available to your key:", ", ".join(n for n in names if "gemini" in n))

    llm = get_llm()
    tool = ToolSpec(
        name="final_answer",
        description="Give the answer.",
        parameters={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
    )
    turn = llm.chat_with_tools(
        "Answer by calling final_answer.", [AgentMessage(role="user", text="What is 2 + 2?")], [tool]
    )
    print(f"Model: {llm.model}")
    print("Tool calls:", [(c.name, c.args) for c in turn.tool_calls] or f"none (text: {turn.text!r})")
    print("OK" if turn.tool_calls else "WARNING: model did not call the tool")


if __name__ == "__main__":
    main()
