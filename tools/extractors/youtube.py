from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from urllib.parse import parse_qs, quote, urlparse
from typing import Any

from tools.collector_core.schema import make_graph, make_node


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")

    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0]

    qs = parse_qs(parsed.query)
    if qs.get("v"):
        return qs["v"][0]

    match = re.search(r"/(shorts|embed|live)/([A-Za-z0-9_-]{6,})", parsed.path)
    if match:
        return match.group(2)

    raise ValueError(f"Could not extract YouTube video id from {url}")


def fetch_oembed_title(url: str) -> str:
    api = "https://www.youtube.com/oembed?format=json&url=" + quote(url, safe="")

    try:
        import certifi
        import requests

        resp = requests.get(api, timeout=10, verify=certifi.where())
        resp.raise_for_status()
        data = resp.json()
        return data.get("title") or ""
    except Exception:
        try:
            with urllib.request.urlopen(api, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return data.get("title") or ""
        except Exception:
            return ""




def _segments_from_json3(path: str) -> list[dict[str, Any]]:
    data = json.loads(open(path, "r", encoding="utf-8", errors="replace").read())
    out: list[dict[str, Any]] = []
    for event in data.get("events", []) if isinstance(data, dict) else []:
        parts: list[str] = []
        for seg in event.get("segs", []) or []:
            text = str(seg.get("utf8") or "")
            if text:
                parts.append(text)
        text = "".join(parts).replace("\n", " ").strip()
        if not text:
            continue
        start = float(event.get("tStartMs") or 0) / 1000.0
        duration = float(event.get("dDurationMs") or 0) / 1000.0
        out.append({"text": text, "start": start, "duration": duration})
    return out


def _segments_from_vtt(path: str) -> list[dict[str, Any]]:
    timestamp_re = re.compile(r"(\d\d:)?\d\d:\d\d\.\d{3}\s+-->\s+(\d\d:)?\d\d:\d\d\.\d{3}")
    out: list[dict[str, Any]] = []
    current: list[str] = []
    for raw in open(path, "r", encoding="utf-8", errors="replace"):
        line = raw.strip()
        if not line or line.upper().startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            if current:
                text = " ".join(current).strip()
                if text:
                    out.append({"text": text, "start": 0.0, "duration": 0.0})
                current = []
            continue
        if timestamp_re.search(line) or re.fullmatch(r"\d+", line):
            if current:
                text = " ".join(current).strip()
                if text:
                    out.append({"text": text, "start": 0.0, "duration": 0.0})
                current = []
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"&[a-zA-Z#0-9]+;", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            current.append(line)
    if current:
        text = " ".join(current).strip()
        if text:
            out.append({"text": text, "start": 0.0, "duration": 0.0})
    return out


def fetch_transcript_with_ytdlp(video_id: str, languages: list[str] | None = None) -> list[dict[str, Any]]:
    """Fallback for recorded livestreams where youtube-transcript-api cannot read captions.

    Some YouTube Live recordings expose auto captions to yt-dlp even when
    youtube-transcript-api reports transcript unavailable.  We only return real
    subtitle/caption text; if yt-dlp cannot download subtitles, the caller should
    keep blocking Medium generation rather than hallucinating from the title.
    """
    languages = languages or ["ko", "en.*", "en", "ja"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory(prefix="study_capture_ytdlp_") as tmp:
        out_tpl = os.path.join(tmp, "%(id)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            ",".join(languages),
            "--sub-format",
            "json3/vtt/srv3/best",
            "-o",
            out_tpl,
            url,
        ]
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "yt-dlp subtitle download failed").strip()[:800])

        subtitle_files: list[str] = []
        for root, _dirs, files in os.walk(tmp):
            for name in files:
                lower = name.lower()
                if lower.endswith((".json3", ".vtt", ".srv3")):
                    subtitle_files.append(os.path.join(root, name))
        if not subtitle_files:
            raise RuntimeError("yt-dlp did not download subtitle files")

        # Prefer Korean, then English, then any available caption file.
        def score(path: str) -> tuple[int, int]:
            name = os.path.basename(path).lower()
            lang_score = 0
            if ".ko" in name or "-ko" in name:
                lang_score = 0
            elif ".en" in name or "-en" in name:
                lang_score = 1
            else:
                lang_score = 2
            fmt_score = 0 if name.endswith(".json3") else 1 if name.endswith(".vtt") else 2
            return (lang_score, fmt_score)

        for path in sorted(subtitle_files, key=score):
            try:
                if path.lower().endswith(".json3"):
                    segments = _segments_from_json3(path)
                else:
                    segments = _segments_from_vtt(path)
                segments = [seg for seg in segments if not is_noise_segment(str(seg.get("text") or ""))]
                if len(" ".join(str(seg.get("text") or "") for seg in segments)) >= 500:
                    return segments
            except Exception:
                continue
        raise RuntimeError("yt-dlp subtitles were downloaded but no usable transcript text was parsed")


def fetch_transcript(video_id: str, languages: list[str] | None = None) -> list[dict[str, Any]]:
    languages = languages or ["ko", "en", "en-US", "ja"]

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except Exception as exc:
        raise RuntimeError(f"youtube-transcript-api import failed: {exc}") from exc

    def normalize_fetched(fetched) -> list[dict[str, Any]]:
        if hasattr(fetched, "to_raw_data"):
            return list(fetched.to_raw_data())

        out: list[dict[str, Any]] = []
        for item in fetched:
            if isinstance(item, dict):
                out.append(item)
            else:
                out.append(
                    {
                        "text": getattr(item, "text", ""),
                        "start": getattr(item, "start", 0.0),
                        "duration": getattr(item, "duration", 0.0),
                    }
                )
        return out

    errors: list[str] = []
    api = YouTubeTranscriptApi()

    try:
        fetched = api.fetch(video_id, languages=languages)
        return normalize_fetched(fetched)
    except Exception as exc:
        errors.append(f"api.fetch={type(exc).__name__}: {exc}")

    try:
        transcript_list = api.list(video_id)

        for lang in languages:
            try:
                transcript = transcript_list.find_transcript([lang])
                return normalize_fetched(transcript.fetch())
            except Exception as exc:
                errors.append(f"find_transcript[{lang}]={type(exc).__name__}: {exc}")

        try:
            transcript = transcript_list.find_generated_transcript(languages)
            return normalize_fetched(transcript.fetch())
        except Exception as exc:
            errors.append(f"find_generated_transcript={type(exc).__name__}: {exc}")

    except Exception as exc:
        errors.append(f"api.list={type(exc).__name__}: {exc}")

    try:
        return fetch_transcript_with_ytdlp(video_id, languages=languages)
    except Exception as exc:
        errors.append(f"yt-dlp={type(exc).__name__}: {exc}")

    raise RuntimeError("transcript not available: " + " | ".join(errors))


def is_noise_segment(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    return bool(
        re.fullmatch(
            r"\[(음악|박수|웃음|Music|Applause|Laughter|music|applause|laughter)\]",
            value,
        )
    )


def group_segments(segments: list[dict[str, Any]], max_chars: int = 1600) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: list[str] = []
    start = 0.0
    end = 0.0

    for seg in segments:
        text = (seg.get("text") or "").replace("\n", " ").strip()
        if is_noise_segment(text):
            continue

        if not current:
            start = float(seg.get("start") or 0.0)

        end = float(seg.get("start") or 0.0) + float(seg.get("duration") or 0.0)
        current.append(text)

        if len(" ".join(current)) >= max_chars:
            groups.append({"start": start, "end": end, "text": " ".join(current)})
            current = []

    if current:
        groups.append({"start": start, "end": end, "text": " ".join(current)})

    return groups


def collect(
    url: str,
    *,
    run_dir,
    trace,
    plan,
    max_pages: int = 20,
    visible: bool = False,
    max_depth: int = 1,
    timeout: int = 30,
    **kwargs,
) -> dict[str, Any]:
    video_id = extract_video_id(url)
    trace.event("youtube_video_id_extracted", video_id=video_id)

    title = fetch_oembed_title(url) or f"YouTube video {video_id}"

    graph = make_graph(
        input_url=url,
        url_type="youtube",
        site_hint="youtube",
        content_shape=plan.content_shape,
        navigation_shape=plan.navigation_shape,
        access_level=plan.access_level,
        evidence_targets=plan.evidence_targets,
        title=title,
    )

    video_node = make_node(
        node_type="video",
        title=title,
        url=url,
        order=1,
        text="",
        meta={"video_id": video_id},
    )

    try:
        raw_segments = fetch_transcript(video_id)
        trace.event("youtube_transcript_collected", raw_segments=len(raw_segments))

        grouped = group_segments(raw_segments)
        trace.event("youtube_transcript_grouped", grouped_segments=len(grouped))

        children = []
        for idx, item in enumerate(grouped, start=1):
            children.append(
                make_node(
                    node_type="transcript_segment",
                    title=f"Transcript segment {idx:03d}",
                    url=url,
                    order=idx,
                    text=item["text"],
                    meta={"start": item["start"], "end": item["end"]},
                )
            )

        video_node["children"] = children
        video_node["text"] = f"Transcript collected for YouTube video {video_id}."
        graph["quality"]["transcript_segments"] = len(raw_segments)

    except Exception as exc:
        trace.warning("youtube_transcript_missing", error=str(exc))
        graph["quality"]["missing"].append("video transcript not accessible")
        video_node["text"] = "Transcript was not accessible for this video."

    graph["nodes"].append(video_node)
    graph["quality"]["pages_collected"] = 1
    graph["quality"]["text_chars"] = len(video_node.get("text", "")) + sum(
        len(c.get("text", "")) for c in video_node.get("children", [])
    )

    return graph
