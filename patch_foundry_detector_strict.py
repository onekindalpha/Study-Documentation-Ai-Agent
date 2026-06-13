from pathlib import Path

p = Path("app/main.py")
text = p.read_text(encoding="utf-8")
backup = p.with_suffix(".py.before_foundry_detector_strict")
backup.write_text(text, encoding="utf-8")

if "foundry_iq_strict" in text:
    print("Already patched.")
    raise SystemExit(0)

# 첫 번째 foundry_iq 분기 위치를 기준으로, 그 앞의 if azure: 시작점 찾기
marker = '\n    elif foundry_iq:\n        # Source Pack mode'
m = text.find(marker)
if m == -1:
    raise SystemExit("ERROR: Source Pack foundry_iq branch not found")

if_marker = '\n    if azure:\n'
insert_at = text.rfind(if_marker, 0, m)
if insert_at == -1:
    raise SystemExit("ERROR: preceding if azure branch not found")

strict_code = '''
    foundry_iq_source_check = f"{article_type} {raw_text} {memo} {qa_logs}".lower()
    foundry_iq_strict = bool(
        foundry_iq and (
            "foundry iq" in foundry_iq_source_check
            or "microsoft iq overview" in foundry_iq_source_check
            or ("work iq" in foundry_iq_source_check and "fabric iq" in foundry_iq_source_check)
            or "build knowledge-enhanced ai agents with foundry iq" in foundry_iq_source_check
            or "integrate mcp tools with azure ai agents" in foundry_iq_source_check
            or "model context protocol" in foundry_iq_source_check and "dynamic tool discovery" in foundry_iq_source_check
        )
    )

'''

text = text[:insert_at + 1] + strict_code + text[insert_at + 1:]

text = text.replace(
    '    elif foundry_iq:\n        # Source Pack mode',
    '    elif foundry_iq_strict:\n        # Source Pack mode',
    1,
)

text = text.replace(
    '    elif foundry_iq:\n        title = "Foundry IQ와 MCP 학습: 지식 기반 AI Agent Workflow 이해하기"',
    '    elif foundry_iq_strict:\n        title = "Foundry IQ와 MCP 학습: 지식 기반 AI Agent Workflow 이해하기"',
    1,
)

p.write_text(text, encoding="utf-8")
print("OK patched:", p)
print("Backup:", backup)
