from pathlib import Path

p = Path("app/main.py")
text = p.read_text(encoding="utf-8")
backup = p.with_suffix(".py.before_disable_foundry_hardcoded_branch")
backup.write_text(text, encoding="utf-8")

# Foundry라는 단어만 보고 Foundry IQ/MCP 전용 템플릿으로 빠지는 분기를 끈다.
text = text.replace(
    'elif foundry_iq:\n        # Source Pack mode',
    'elif False and foundry_iq:\n        # Source Pack mode',
)

text = text.replace(
    'elif foundry_iq:\n        title = "Foundry IQ와 MCP 학습: 지식 기반 AI Agent Workflow 이해하기"',
    'elif False and foundry_iq:\n        title = "Foundry IQ와 MCP 학습: 지식 기반 AI Agent Workflow 이해하기"',
)

# strict 패치가 남아 있어도 강제 Foundry 전용 후처리를 못 타게 막는다.
text = text.replace(
    'if "is_foundry_iq_mcp_article" in locals() and is_foundry_iq_mcp_article:',
    'if False and "is_foundry_iq_mcp_article" in locals() and is_foundry_iq_mcp_article:',
)

text = text.replace(
    'if is_foundry_iq_mcp_article:',
    'if False and is_foundry_iq_mcp_article:',
)

p.write_text(text, encoding="utf-8")
print("OK patched:", p)
print("Backup:", backup)
