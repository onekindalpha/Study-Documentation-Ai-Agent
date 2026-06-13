from pathlib import Path

p = Path("app/main.py")
text = p.read_text(encoding="utf-8")
backup = p.with_suffix(".py.before_foundry_longform_v5_newline_fix")
backup.write_text(text, encoding="utf-8")

start = text.find('    article_body = "\\n".join(lines)')
end = text.find('    return article_body', start)

if start == -1 or end == -1:
    raise SystemExit("ERROR: longform block not found")

block = text[start:end]

# v4에서 문자열 매칭용 줄바꿈이 \\n으로 들어간 경우를 실제 newline escape인 \n으로 교정
fixed = block.replace('\\\\n', '\\n')

if fixed == block:
    print("No double-escaped newline found. Nothing changed.")
else:
    text = text[:start] + fixed + text[end:]
    p.write_text(text, encoding="utf-8")
    print("OK patched newline escapes")
    print("Backup:", backup)
