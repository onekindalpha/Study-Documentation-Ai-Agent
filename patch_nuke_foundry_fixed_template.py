from pathlib import Path

p = Path("app/main.py")
text = p.read_text(encoding="utf-8")
backup = p.with_suffix(".py.before_nuke_foundry_fixed_template")
backup.write_text(text, encoding="utf-8")

replacements = [
    ("    elif foundry_iq:\n", "    elif False and foundry_iq:\n"),
    ("    elif foundry_iq_strict:\n", "    elif False and foundry_iq_strict:\n"),
    ('    if is_foundry_iq_mcp_article:\n', '    if False and is_foundry_iq_mcp_article:\n'),
    (
        '    if "is_foundry_iq_mcp_article" in locals() and is_foundry_iq_mcp_article:\n',
        '    if False and "is_foundry_iq_mcp_article" in locals() and is_foundry_iq_mcp_article:\n',
    ),
]

changed = 0
for old, new in replacements:
    count = text.count(old)
    if count:
        text = text.replace(old, new)
        changed += count
        print(f"replaced {count}: {old.strip()}")

if changed == 0:
    print("WARN: no foundry branch replacements made")

p.write_text(text, encoding="utf-8")
print("OK patched:", p)
print("Backup:", backup)
