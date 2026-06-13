from __future__ import annotations

from pathlib import Path
from typing import Optional
import argparse
import json

from .extractor_models import make_run_id, write_json
from .video_ingest import ingest_video_url
from .transcript_extractor import extract_transcript
from .frame_extractor import extract_scene_frames
from .ocr_extractor import extract_ocr
from .concept_extractor import extract_concepts
from .timeline_builder import build_timeline
from .extraction_report import build_extraction_report, report_to_markdown


def run_extraction(
    input_url: str,
    runs_root: str | Path = "runs",
    run_id: Optional[str] = None,
    whisper_model: str = "base",
    skip_ocr: bool = False,
):
    """
    Main integration point for app/main.py.

    Important:
    - This function never reuses a previous source_pack.
    - Every input_url creates a new run directory unless run_id is explicitly supplied.
    - Draft generation should read extraction_report.can_generate_draft before proceeding.
    """
    runs_root = Path(runs_root)
    run_id = run_id or make_run_id(input_url)
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    record = ingest_video_url(input_url=input_url, run_dir=run_dir, run_id=run_id)
    transcript = extract_transcript(run_dir, whisper_model=whisper_model)
    import os
    fast_text_only = os.environ.get("SCC_FAST_TEXT_ONLY", "0") in {"1", "true", "TRUE", "yes", "YES"}

    if fast_text_only:
        write_json(run_dir / "frames.json", [])
        write_json(run_dir / "ocr.json", [])
    else:
        frames = extract_scene_frames(run_dir)

        if skip_ocr:
            write_json(run_dir / "ocr.json", [])
        else:
            extract_ocr(run_dir)

    extract_concepts(run_dir)
    build_timeline(run_dir)
    report = build_extraction_report(run_dir)
    (run_dir / "extraction_report.md").write_text(report_to_markdown(report), encoding="utf-8")

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "report": report,
        "report_json_path": str(run_dir / "extraction_report.json"),
        "report_md_path": str(run_dir / "extraction_report.md"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--runs-root", default="runs")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--whisper-model", default="base")
    parser.add_argument("--skip-ocr", action="store_true")
    args = parser.parse_args()

    result = run_extraction(
        input_url=args.url,
        runs_root=args.runs_root,
        run_id=args.run_id,
        whisper_model=args.whisper_model,
        skip_ocr=args.skip_ocr,
    )
    print(json.dumps({
        "run_id": result["run_id"],
        "run_dir": result["run_dir"],
        "report_json_path": result["report_json_path"],
        "report_md_path": result["report_md_path"],
        "can_generate_draft": result["report"].can_generate_draft,
        "scores": result["report"].scores,
        "warnings": result["report"].warnings,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

# SCC_AUTO_CLEANUP_WRAPPER_START
def _scc_cleanup_heavy_run_files_after_extraction(run_dir):
    """
    Keep JSON analysis artifacts, delete heavy media files after each extraction.
    This prevents disk-full errors while collecting many URL cases.
    """
    import os
    import json
    from pathlib import Path

    keep_media = str(os.environ.get("SCC_KEEP_MEDIA", "0")).lower() in {"1", "true", "yes", "on"}
    clean_enabled = str(os.environ.get("SCC_CLEAN_MEDIA_AFTER_RUN", "1")).lower() not in {"0", "false", "no", "off"}

    info = {
        "enabled": bool(clean_enabled and not keep_media),
        "deleted_files": 0,
        "freed_bytes": 0,
        "freed_mb": 0.0,
    }

    if keep_media or not clean_enabled:
        return info

    root = Path(str(run_dir))
    if not root.exists():
        return info

    heavy_exts = {
        ".mp4", ".webm", ".mkv", ".mov",
        ".wav", ".m4a", ".mp3", ".opus",
        ".jpg", ".jpeg", ".png", ".webp",
    }

    for f in list(root.rglob("*")):
        try:
            if not f.is_file():
                continue
            if f.suffix.lower() not in heavy_exts:
                continue
            size = f.stat().st_size
            f.unlink()
            info["deleted_files"] += 1
            info["freed_bytes"] += size
        except Exception:
            pass

    info["freed_mb"] = round(info["freed_bytes"] / 1024 / 1024, 2)

    # extraction_report.json에도 cleanup 결과를 기록
    report_path = root / "extraction_report.json"
    try:
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
            report["cleanup"] = info
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return info


_scc_original_run_extraction = run_extraction

def run_extraction(*args, **kwargs):
    result = _scc_original_run_extraction(*args, **kwargs)

    try:
        run_dir = None
        if isinstance(result, dict):
            run_dir = result.get("run_dir")
        if run_dir:
            cleanup = _scc_cleanup_heavy_run_files_after_extraction(run_dir)
            if isinstance(result, dict):
                result["cleanup"] = cleanup
    except Exception as e:
        if isinstance(result, dict):
            result["cleanup_error"] = repr(e)

    return result
# SCC_AUTO_CLEANUP_WRAPPER_END

# SCC_CONCEPT_GUARD_WRAPPER_START
_scc_concept_guard_original_run_extraction = run_extraction

def run_extraction(*args, **kwargs):
    result = _scc_concept_guard_original_run_extraction(*args, **kwargs)

    try:
        run_dir = None
        if isinstance(result, dict):
            run_dir = result.get("run_dir")
        if run_dir:
            from tools.concept_guard import apply_concept_guard
            guard = apply_concept_guard(run_dir)
            if isinstance(result, dict):
                result["concept_guard"] = guard
    except Exception as e:
        if isinstance(result, dict):
            result["concept_guard_error"] = repr(e)

    return result
# SCC_CONCEPT_GUARD_WRAPPER_END


# SCC_FORCE_CONCEPT_EXTRACTOR_V3_START
# Post-extraction current-run concept rewrite.
# Uses only the current run_dir artifacts and current result title.
try:
    from tools.concept_extractor_v3_runtime import apply_to_run as _scc_apply_concept_extractor_v3
except Exception as _scc_v3_import_error:
    _scc_apply_concept_extractor_v3 = None

_scc_prev_run_extraction_for_v3 = run_extraction

def run_extraction(*args, **kwargs):
    result = _scc_prev_run_extraction_for_v3(*args, **kwargs)

    try:
        run_dir = None
        title = None

        if isinstance(result, dict):
            run_dir = result.get("run_dir")
            title = (
                result.get("title")
                or result.get("video_title")
                or result.get("source_title")
            )
            meta = result.get("metadata")
            if not title and isinstance(meta, dict):
                title = meta.get("title") or meta.get("video_title")

        if run_dir and _scc_apply_concept_extractor_v3:
            v3 = _scc_apply_concept_extractor_v3(run_dir, title=title)
            if isinstance(result, dict):
                result["concept_extractor"] = "concept_extractor_v3_runtime"
                result["concepts_v3"] = {
                    "core_count": len(v3.get("core_concepts", [])),
                    "supporting_count": len(v3.get("supporting_terms", [])),
                    "concept_score": v3.get("quality", {}).get("concept_score"),
                }
    except Exception as e:
        if isinstance(result, dict):
            result["concept_extractor_v3_error"] = str(e)

    return result
# SCC_FORCE_CONCEPT_EXTRACTOR_V3_END

