from pathlib import Path

p = Path("app/main.py")
text = p.read_text(encoding="utf-8")
backup = p.with_suffix(".py.before_foundry_safe_v3_patch")
backup.write_text(text, encoding="utf-8")

marker = "\n    foundry_iq_descriptions = {\n"
idx = text.find(marker)
if idx == -1:
    raise SystemExit("ERROR: foundry_iq_descriptions marker not found")

insert = '''
    foundry_source_check = f"{article_type} {raw_text} {memo} {qa_logs}".lower()
    is_foundry_iq_mcp_article = (
        article_type == "foundry_iq_mcp_learning"
        or ("foundry iq" in foundry_source_check and "mcp" in foundry_source_check)
        or ("knowledge base" in foundry_source_check and "dynamic tool discovery" in foundry_source_check)
        or ("azure ai agents" in foundry_source_check and "model context protocol" in foundry_source_check)
    )

'''

if "is_foundry_iq_mcp_article" not in text[idx-500:idx+500]:
    text = text[:idx] + insert + text[idx:]

# marker 위치 다시 계산
idx = text.find(marker)
head = text[:idx]
tail = text[idx:]

tail = tail.replace('article_type == "foundry_iq_mcp_learning"', 'is_foundry_iq_mcp_article')

text = head + tail

p.write_text(text, encoding="utf-8")
print("OK patched:", p)
print("Backup:", backup)
