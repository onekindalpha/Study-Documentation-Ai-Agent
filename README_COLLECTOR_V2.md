# Study Capture Copilot Collector v2 Patch

Adds a source-graph v2 collector for:
- Oopy/Notion-like pages
- WikiDocs and static docs
- general web pages
- YouTube transcript/description extraction

AI Skills Navigator remains on the existing specialized Playwright/API collector first, because it already understands the player/lab tree. The v2 hook falls back to the legacy collector automatically.

Run:

```bash
python tools/apply_collector_v2_hook.py
pip install -r requirements.txt
python -m playwright install chromium
```
