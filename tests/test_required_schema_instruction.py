from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel


def test_required_schema_appends_explicit_format_instruction(monkeypatch):
    from tradingagents.llm_clients.openai_client import (
        LocalCompatibleChatOpenAI,
        NormalizedChatOpenAI,
    )
    class Decision(BaseModel):
        action: str
    monkeypatch.setattr(NormalizedChatOpenAI, 'with_structured_output', lambda *a, **kw: RunnableLambda(lambda value: value))
    llm = LocalCompatibleChatOpenAI(model='test', api_key='test', structured_output_tool_choice='required')
    result = llm.with_structured_output(Decision).invoke('Write prose sections')
    assert 'MUST call the Decision function' in str(result)
    assert 'Do not produce a prose response' in str(result)
