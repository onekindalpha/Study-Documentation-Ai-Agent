from __future__ import annotations

from pathlib import Path
import json
import re
import html
from collections import Counter

STOP_START = {
    "i","you","we","they","he","she","it","this","that","these","those",
    "there","here","now","then","so","because","when","where","what","how",
    "if","and","or","but","to","of","in","on","for","with","about","from",
    "as","at","by","into","over","under","again","also","maybe","let","lets",
    "ll","re","ve","m","d","s"
}

STOP_END = {
    "i","you","we","they","he","she","it","this","that","these","those",
    "a","an","the","to","of","in","on","for","with","about","from","as",
    "is","are","was","were","be","been","being","do","does","did","doing",
    "can","could","will","would","should","may","might","must","have","has",
    "had","ll","re","ve","m","d","s"
}

BAD_PATTERNS = [
    r"\bgoing to\b",
    r"\bbe able to\b",
    r"\bas you can see\b",
    r"\blet'?s\b",
    r"\bclick on\b",
    r"\bpress\b",
    r"\bcopy and paste\b",
    r"\bselect insert\b",
    r"\brespond faster\b",
    r"\boverview tab\b",
    r"\babsolutely correct\b",
    r"\bgame changer\b",
    r"\bpeople ask questions\b",
    r"\babout the customer id\b",
    r"\bwithin the ai visuals category\b",
    r"\bclear description\b",
    r"\bsubtle difference\b",
    r"\bsample pdf to run\b",
]

# 전역 도메인 키워드가 아니라, 명사구 구조를 판정하기 위한 일반 head noun 목록.
GENERIC_HEADS = {
    "model","models","system","systems","feature","features","variable","variables",
    "label","labels","prediction","predictions","threshold","probability",
    "training","data","dataset","datasets","table","tables","database","pipeline",
    "pipelines","workflow","workflows","task","tasks","file","files","connection",
    "protocol","protocols","address","router","layer","layers","interface","card",
    "application","network","networking","prompt","prompts","source","sources",
    "context","window","json","flow","flows","agent","agents","format","formatting",
    "instruction","instructions","control","controls","version","versions","visual",
    "visuals","query","queries","report","reports","dashboard","slicer","filter",
    "filters","line","forecast","anomaly","anomalies","narrative","quality",
    "column","columns","roles","role","grounding","knowledge","function","defaults",
    "plugin","plugins","schedule","schedules","backfill","backfills","trigger",
    "triggers","sync","deployment","production","cloud","engine","storage"
}

def _norm(x: str) -> str:
    x = html.unescape(str(x or ""))
    x = x.replace("\xa0", " ")
    x = re.sub(r"&nbsp;?", " ", x)
    x = re.sub(r"\s+", " ", x)
    return x.strip()

def _clean_phrase(x: str) -> str:
    x = _norm(x)
    x = x.strip(" \t\r\n.,;:!?()[]{}\"'`“”‘’")
    x = re.sub(r"\s+", " ", x)
    return x

def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

def _dump_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def _iter_strings(obj):
    if obj is None:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)

def _dedupe_repeated_text(text: str) -> str:
    text = _norm(text)
    # adjacent repeated phrase collapse: "x x x" -> "x"
    for _ in range(4):
        text = re.sub(r"\b((?:[A-Za-z0-9&+\-\.]+(?:\s+|$)){1,10})\1{1,}", r"\1", text)
    text = re.sub(r"\b(\w+)(?:\s+\1\b){1,}", r"\1", text, flags=re.I)
    return _norm(text)

def _tokens(phrase: str):
    return re.findall(r"[A-Za-z0-9&+\-\.#]+", phrase)

def _is_bad_phrase(phrase: str) -> bool:
    p = _clean_phrase(phrase)
    low = p.lower()
    toks = [t.lower() for t in _tokens(p)]

    if len(p) < 3 or len(p) > 72:
        return True
    if not re.search(r"[A-Za-z]", p):
        return True
    if any(re.search(bp, low) for bp in BAD_PATTERNS):
        return True
    if toks and (toks[0] in STOP_START or toks[-1] in STOP_END):
        return True
    if re.match(r"^(ll|re|ve|m|d|s)\b", low):
        return True
    if p.endswith(".") and len(toks) <= 3:
        return True

    stop_count = sum(1 for t in toks if t in STOP_START or t in STOP_END)
    if toks and stop_count / max(1, len(toks)) >= 0.55:
        return True

    # 잘린 조각 방지
    if len(toks) == 2:
        if toks[0] in {"cat","four","machines","model","data"} and toks[-1] in {"versus","inside","don","isn"}:
            return True

    return False

def _title_candidates(title: str):
    title = _norm(title)
    out = []

    for part in re.split(r"\s+\|\s+|[-–—:]", title):
        part = _clean_phrase(part)
        part = re.sub(r"\b(FREE|Tutorial|Explained|Introduction to|Part \d+|Mission \d+)\b", "", part, flags=re.I)
        part = _clean_phrase(part)
        if part and not _is_bad_phrase(part):
            out.append(part)

    for m in re.finditer(r"\b[A-Z][A-Za-z0-9&+\-\.#]*(?:\s+[A-Z][A-Za-z0-9&+\-\.#]*){0,4}\b", title):
        p = _clean_phrase(m.group(0))
        if p and not _is_bad_phrase(p):
            out.append(p)

    for m in re.finditer(r"\b[A-Z0-9]{2,}(?:[&+.-][A-Z0-9]+)*\b", title):
        p = _clean_phrase(m.group(0))
        if p and len(p) >= 2:
            out.append(p)

    return out

def _candidate_phrases(text: str):
    text = _norm(text)
    out = []

    # Acronyms: OSI, TCP, UDP, HTTP, FTP, SMTP, ETL, CSV, JSON, GPT-4.1
    for m in re.finditer(r"\b[A-Z]{2,8}(?:[-\.][A-Z0-9]+)*\b", text):
        out.append(m.group(0))

    # TitleCase phrases: Power BI, Smart Narrative, Power Query, Claude Sonnet
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9&+\-\.#]*(?:\s+[A-Z][A-Za-z0-9&+\-\.#]*){1,4}\b", text):
        out.append(m.group(0))

    # hyphenated terms: rule-based systems
    for m in re.finditer(r"\b[A-Za-z]+-[A-Za-z]+(?:\s+[A-Za-z]+){0,3}\b", text):
        out.append(m.group(0))

    words = re.findall(r"[A-Za-z][A-Za-z0-9&+\-\.#]*", text)
    lows = [w.lower() for w in words]

    for n in (2, 3, 4):
        for i in range(0, max(0, len(words) - n + 1)):
            chunk = words[i:i+n]
            low = lows[i:i+n]

            if low[0] in STOP_START or low[-1] in STOP_END:
                continue
            if not any(w in GENERIC_HEADS for w in low):
                continue
            if any(w in {"going","click","press","select","copy","paste","welcome","today"} for w in low):
                continue

            out.append(" ".join(chunk))

    cleaned = []
    for p in out:
        p = _clean_phrase(p)
        if p and not _is_bad_phrase(p):
            cleaned.append(p)
    return cleaned

def _occurrences(text_low: str, phrase: str) -> int:
    key = re.escape(phrase.lower())
    return len(re.findall(r"\b" + key + r"\b", text_low))

def _score_phrase(phrase: str, title: str, text: str, freq_hint: int) -> float:
    p = _clean_phrase(phrase)
    low = p.lower()
    title_low = title.lower()
    text_low = text.lower()
    toks = [t.lower() for t in _tokens(p)]

    score = 0.0
    if low in title_low:
        score += 5.0
    if any(t in title_low for t in toks if len(t) >= 4):
        score += 1.5

    occ = max(freq_hint, _occurrences(text_low, p))
    score += min(4.0, occ * 0.45)

    first = text_low[: min(len(text_low), 8000)]
    if low in first:
        score += 2.0

    if re.fullmatch(r"[A-Z0-9]{2,8}(?:[-\.][A-Z0-9]+)*", p):
        score += 2.5

    if any(t in GENERIC_HEADS for t in toks):
        score += 1.5

    if re.search(r"\b(is|means|refers to|used to|used for|helps|works|creates|select|choose|define|configure)\b.{0,80}" + re.escape(low), text_low):
        score += 1.2

    if _is_bad_phrase(p):
        score -= 8.0

    # 너무 일반적인 단일어는 낮춤
    if len(toks) == 1 and low not in title_low and not re.fullmatch(r"[A-Z0-9]{2,8}", p):
        score -= 1.5

    return score

def _make_items(scored, title_low: str):
    core = []
    supporting = []
    rejected = []

    seen = set()
    for phrase, score, reason in scored:
        p = _clean_phrase(phrase)
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)

        item = {
            "text": p,
            "confidence": round(max(0.35, min(0.92, score / 10)), 2),
            "evidence": ["title" if key in title_low else "transcript"],
            "score": round(score, 2),
            "reason": reason,
        }

        if score >= 5.2 and len(core) < 14:
            core.append(item)
        elif score >= 3.2 and len(supporting) < 12:
            supporting.append(item)
        elif len(rejected) < 30:
            bad = dict(item)
            bad["reason"] = "low_score_or_fragment"
            rejected.append(bad)

    return core, supporting, rejected

def apply_to_run(run_dir: str | Path, title: str | None = None):
    run_dir = Path(run_dir)
    report_path = run_dir / "extraction_report.json"
    transcript_path = run_dir / "transcript.json"
    timeline_path = run_dir / "timeline.json"
    concepts_path = run_dir / "concepts.json"
    concepts_v3_path = run_dir / "concepts_v3.json"
    cleaned_path = run_dir / "transcript_cleaned.txt"

    report = _load_json(report_path) or {}
    transcript_obj = _load_json(transcript_path)
    timeline_obj = _load_json(timeline_path)
    old_concepts = _load_json(concepts_path) or {}

    title = (
        title
        or report.get("title")
        or report.get("video_title")
        or report.get("source_title")
        or old_concepts.get("title")
        or ""
    )
    title = _norm(title)

    transcript_text = _norm(" ".join(_iter_strings(transcript_obj)))
    timeline_text = _norm(" ".join(_iter_strings(timeline_obj)))
    combined = _dedupe_repeated_text(" ".join([title, transcript_text, timeline_text]))

    try:
        cleaned_path.write_text(combined[:300000], encoding="utf-8")
    except Exception:
        pass

    candidates = []
    candidates.extend(_title_candidates(title))
    candidates.extend(_candidate_phrases(combined[:300000]))

    counts = Counter(_clean_phrase(c) for c in candidates if _clean_phrase(c))
    scored = []
    for phrase, cnt in counts.items():
        if _is_bad_phrase(phrase):
            scored.append((phrase, -5.0, "rejected_by_fragment_filter"))
            continue
        score = _score_phrase(phrase, title, combined[:300000], cnt)
        reason = "current-run title/transcript/timeline candidate"
        scored.append((phrase, score, reason))

    scored.sort(key=lambda x: x[1], reverse=True)
    core, supporting, rejected = _make_items(scored, title.lower())

    concept_score = min(10, max(1, int(round(len(core) * 0.7 + len(supporting) * 0.25))))
    if len(core) < 3:
        concept_score = min(concept_score, 4)
    if any(_is_bad_phrase(x["text"]) for x in core[:5]):
        concept_score = min(concept_score, 5)

    payload = {
        "extractor": "concept_extractor_v3_runtime",
        "title": title,
        "core_concepts": core,
        "supporting_terms": supporting,
        "rejected_false_positives": rejected,
        "quality": {
            "concept_score": concept_score,
            "core_count": len(core),
            "supporting_count": len(supporting),
            "rejected_count": len(rejected),
        },
    }

    _dump_json(concepts_v3_path, payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": title,
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in core
        ],
        "supporting_terms": supporting,
        "rejected": rejected,
        "core_concepts": core,
        "quality": payload["quality"],
    }
    _dump_json(concepts_path, legacy)

    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(core)
            report["assets"]["supporting_terms"] = len(supporting)
        _dump_json(report_path, report)

    return payload

# SCC_V3_QUALITY_PATCH_START
# Refine title/candidate ranking without global domain keyword injection.

LOW_VALUE_SINGLE_WORDS = {
    "build", "deploy", "course", "tutorial", "free", "ready",
    "production", "full", "part", "mission", "understanding",
    "enhanced", "tips", "tricks", "introduction"
}

TITLE_CONNECTOR_WORDS = {
    "and", "with", "to", "a", "an", "the", "w", "for", "of", "in", "on"
}

def _is_low_value_singleton(p: str) -> bool:
    toks = [t.lower() for t in _tokens(p)]
    return len(toks) == 1 and toks[0] in LOW_VALUE_SINGLE_WORDS

def _is_title_marketing_fragment(p: str) -> bool:
    low = _clean_phrase(p).lower()
    toks = [t.lower() for t in _tokens(p)]

    if not toks:
        return True

    if _is_low_value_singleton(p):
        return True

    # 제목 홍보문구/동작문구: Build and Deploy A Production Ready...
    if len(toks) >= 5 and toks[0] in {"build", "deploy", "understanding", "enhanced"}:
        return True

    if len(toks) <= 2 and all(t in LOW_VALUE_SINGLE_WORDS or t in TITLE_CONNECTOR_WORDS for t in toks):
        return True

    if low in {"a production", "production ready", "full course", "free tutorial"}:
        return True

    return False

def _title_candidates(title: str):
    title = _norm(title)
    out = []

    # Split title into meaningful chunks.
    for part in re.split(r"\s+\|\s+|[-–—:]", title):
        part = _clean_phrase(part)
        part = re.sub(r"\b(FREE|Tutorial|Full Course|Course|Explained|Introduction to|Part \d+|Mission \d+)\b", "", part, flags=re.I)
        part = _clean_phrase(part)

        if part and not _is_bad_phrase(part) and not _is_title_marketing_fragment(part):
            out.append(part)

    # TitleCase phrase candidates, but avoid action/marketing fragments.
    for m in re.finditer(r"\b[A-Z][A-Za-z0-9&+\-\.#]*(?:\s+[A-Z][A-Za-z0-9&+\-\.#]*){0,4}\b", title):
        p = _clean_phrase(m.group(0))
        if p and not _is_bad_phrase(p) and not _is_title_marketing_fragment(p):
            out.append(p)

    # Acronyms / framework-style terms.
    for m in re.finditer(r"\b[A-Z0-9]{2,}(?:[&+.-][A-Z0-9]+)*\b", title):
        p = _clean_phrase(m.group(0))
        if p and len(p) >= 2 and not _is_title_marketing_fragment(p):
            out.append(p)

    # Special cleanup: extract useful tail after "Build and Deploy ..."
    # This still uses only the current title text.
    m = re.search(r"(Job Application Tracker)", title, flags=re.I)
    if m:
        out.append(_clean_phrase(m.group(1)))

    return out

def _is_redundant_subphrase(candidate: str, selected: list[dict]) -> bool:
    c = _clean_phrase(candidate).lower()
    c_toks = set(t.lower() for t in _tokens(c))

    if len(c_toks) <= 1:
        return False

    for item in selected:
        s = _clean_phrase(item.get("text", "")).lower()
        s_toks = set(t.lower() for t in _tokens(s))

        # If candidate is a shorter substring of an already selected stronger phrase,
        # don't keep both as core.
        if c != s and c in s and len(s_toks) > len(c_toks):
            return True

        # High token overlap with longer phrase.
        if len(c_toks) >= 2 and len(s_toks) > len(c_toks):
            overlap = len(c_toks & s_toks) / max(1, len(c_toks))
            if overlap >= 0.95:
                return True

    return False

def _make_items(scored, title_low: str):
    core = []
    supporting = []
    rejected = []

    seen = set()

    for phrase, score, reason in scored:
        p = _clean_phrase(phrase)
        key = p.lower()

        if not p or key in seen:
            continue
        seen.add(key)

        if _is_bad_phrase(p) or _is_title_marketing_fragment(p):
            if len(rejected) < 40:
                rejected.append({
                    "text": p,
                    "confidence": 0.2,
                    "evidence": ["title" if key in title_low else "transcript"],
                    "score": round(score, 2),
                    "reason": "rejected_fragment_or_title_marketing_phrase",
                })
            continue

        item = {
            "text": p,
            "confidence": round(max(0.35, min(0.92, score / 10)), 2),
            "evidence": ["title" if key in title_low else "transcript"],
            "score": round(score, 2),
            "reason": reason,
        }

        if score >= 5.2 and len(core) < 14:
            if _is_redundant_subphrase(p, core):
                if len(supporting) < 12:
                    item["reason"] = "supporting_redundant_subphrase_of_core"
                    supporting.append(item)
            else:
                core.append(item)
        elif score >= 3.2 and len(supporting) < 12:
            supporting.append(item)
        elif len(rejected) < 40:
            bad = dict(item)
            bad["reason"] = "low_score_or_fragment"
            rejected.append(bad)

    return core, supporting, rejected
# SCC_V3_QUALITY_PATCH_END

# SCC_V3_QUALITY_PATCH_2_START

def _is_file_artifact_phrase(p: str) -> bool:
    low = _clean_phrase(p).lower()
    if re.search(r"\b[a-z0-9_-]{8,}\.(en\.)?(vtt|srt|json|txt|mp4|webm|wav|m4a)\b", low):
        return True
    if ".vtt" in low or ".srt" in low:
        return True
    return False

def _is_title_marketing_fragment(p: str) -> bool:
    p = _clean_phrase(p)
    low = p.lower()
    toks = [t.lower() for t in _tokens(p)]

    if not toks:
        return True

    if _is_file_artifact_phrase(p):
        return True

    if _is_low_value_singleton(p):
        return True

    # one-letter connector artifact: "Tracker w"
    if toks[-1] in {"w", "a", "an", "the", "to", "for", "with"}:
        return True

    # title marketing fragments around "production ready"
    if "production ready" in low:
        return True
    if low in {
        "a production", "production ready", "ready job",
        "deploy a production", "a production ready",
        "production ready job", "ready job application",
        "deploy a production ready", "a production ready job",
        "production ready job application", "ready job application tracker",
        "job application tracker w", "application tracker w",
    }:
        return True

    # long action/promo phrases from titles
    if len(toks) >= 3 and toks[0] in {"build", "deploy"}:
        return True
    if len(toks) >= 5 and toks[0] in {"understanding", "enhanced"}:
        return True

    if len(toks) <= 2 and all(t in LOW_VALUE_SINGLE_WORDS or t in TITLE_CONNECTOR_WORDS for t in toks):
        return True

    return False

def _is_redundant_subphrase(candidate: str, selected: list[dict]) -> bool:
    c = _clean_phrase(candidate).lower()
    c_toks = set(t.lower() for t in _tokens(c))

    if len(c_toks) <= 1:
        return False

    for item in selected:
        s = _clean_phrase(item.get("text", "")).lower()
        s_toks = set(t.lower() for t in _tokens(s))

        if c == s:
            return True

        # shorter phrase inside stronger longer phrase
        if c in s and len(s_toks) > len(c_toks):
            return True

        # longer phrase is mostly same but contains marketing connector/artifact
        if s in c and len(c_toks) > len(s_toks):
            noisy_extra = c_toks - s_toks
            if noisy_extra and all(t in LOW_VALUE_SINGLE_WORDS or t in TITLE_CONNECTOR_WORDS for t in noisy_extra):
                return True

        overlap = len(c_toks & s_toks) / max(1, min(len(c_toks), len(s_toks)))
        if overlap >= 0.95 and abs(len(c_toks) - len(s_toks)) <= 1:
            return True

    return False

def _make_items(scored, title_low: str):
    # Stronger sorting: score first, then longer useful concept first.
    # This lets "Job Application Tracker" beat "Application Tracker".
    scored = sorted(
        scored,
        key=lambda x: (
            x[1],
            len([t for t in _tokens(x[0]) if t.lower() not in TITLE_CONNECTOR_WORDS]),
            len(_clean_phrase(x[0]))
        ),
        reverse=True,
    )

    core = []
    supporting = []
    rejected = []
    seen = set()

    for phrase, score, reason in scored:
        p = _clean_phrase(phrase)
        key = p.lower()

        if not p or key in seen:
            continue
        seen.add(key)

        if _is_bad_phrase(p) or _is_title_marketing_fragment(p) or _is_file_artifact_phrase(p):
            if len(rejected) < 60:
                rejected.append({
                    "text": p,
                    "confidence": 0.2,
                    "evidence": ["title" if key in title_low else "transcript"],
                    "score": round(score, 2),
                    "reason": "rejected_fragment_marketing_or_file_artifact",
                })
            continue

        item = {
            "text": p,
            "confidence": round(max(0.35, min(0.92, score / 10)), 2),
            "evidence": ["title" if key in title_low else "transcript"],
            "score": round(score, 2),
            "reason": reason,
        }

        if score >= 5.2 and len(core) < 14:
            if _is_redundant_subphrase(p, core):
                if len(supporting) < 12:
                    item["reason"] = "supporting_redundant_or_less_specific"
                    supporting.append(item)
            else:
                core.append(item)
        elif score >= 3.2 and len(supporting) < 12:
            if not _is_redundant_subphrase(p, core):
                supporting.append(item)
        elif len(rejected) < 60:
            bad = dict(item)
            bad["reason"] = "low_score_or_fragment"
            rejected.append(bad)

    return core, supporting, rejected

# Patch apply_to_run scoring after original function by wrapping it.
_scc_v3_prev_apply_to_run_quality2 = apply_to_run

def apply_to_run(run_dir, title=None):
    payload = _scc_v3_prev_apply_to_run_quality2(run_dir, title=title)

    # Recompute score more strictly after cleanup.
    core = payload.get("core_concepts", [])
    supporting = payload.get("supporting_terms", [])
    rejected = payload.get("rejected_false_positives", [])

    bad_core = [x for x in core if _is_bad_phrase(x.get("text", "")) or _is_title_marketing_fragment(x.get("text", "")) or _is_file_artifact_phrase(x.get("text", ""))]
    if bad_core:
        rejected.extend(bad_core)
        core = [x for x in core if x not in bad_core]

    concept_score = min(9, max(1, int(round(len(core) * 0.55 + len(supporting) * 0.18))))
    if len(core) < 5:
        concept_score = min(concept_score, 5)
    if len(core) < 3:
        concept_score = min(concept_score, 3)

    payload["core_concepts"] = core[:14]
    payload["supporting_terms"] = supporting[:12]
    payload["rejected_false_positives"] = rejected[:80]
    payload["quality"] = {
        "concept_score": concept_score,
        "core_count": len(payload["core_concepts"]),
        "supporting_count": len(payload["supporting_terms"]),
        "rejected_count": len(payload["rejected_false_positives"]),
    }

    run_dir = Path(run_dir)
    _dump_json(run_dir / "concepts_v3.json", payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": payload.get("title", title or ""),
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in payload["core_concepts"]
        ],
        "supporting_terms": payload["supporting_terms"],
        "rejected": payload["rejected_false_positives"],
        "core_concepts": payload["core_concepts"],
        "quality": payload["quality"],
    }
    _dump_json(run_dir / "concepts.json", legacy)

    report_path = run_dir / "extraction_report.json"
    report = _load_json(report_path) or {}
    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(payload["core_concepts"])
            report["assets"]["supporting_terms"] = len(payload["supporting_terms"])
        _dump_json(report_path, report)

    return payload

# SCC_V3_QUALITY_PATCH_2_END

# SCC_V3_QUALITY_PATCH_3_START

_scc_v3_old_clean_phrase_p3 = _clean_phrase

ARTIFACT_WORDS = {
    "subtitle", "subtitles", "transcript", "caption", "captions",
    "vtt", "srt", "jsonl"
}

LOW_VALUE_ACRONYMS = {
    "DOM", "JSON", "CSS", "URI", "URL", "HTML"
}

LIKELY_ASR_FALSE_ACRONYMS = {
    "XJS", "NEX"
}

def _clean_phrase(x: str) -> str:
    p = _scc_v3_old_clean_phrase_p3(x)

    # remove leading articles from candidate phrases
    p = re.sub(r"^(a|an|the)\s+", "", p, flags=re.I)

    # remove trailing artifact markers
    p = re.sub(r"\s+(subtitle|subtitles|transcript|caption|captions)$", "", p, flags=re.I)

    # normalize spacing again
    p = re.sub(r"\s+", " ", p).strip(" \t\r\n.,;:!?()[]{}\"'`“”‘’")
    return p

def _is_file_artifact_phrase(p: str) -> bool:
    raw = str(p or "")
    low = _scc_v3_old_clean_phrase_p3(raw).lower()

    if re.search(r"\b[a-z0-9_-]{8,}\.(en\.)?(vtt|srt|json|txt|mp4|webm|wav|m4a)\b", low):
        return True
    if ".vtt" in low or ".srt" in low:
        return True
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in ARTIFACT_WORDS):
        return True
    return False

def _is_low_value_acronym_core(p: str, title_low: str) -> bool:
    pp = _clean_phrase(p)
    if pp in LIKELY_ASR_FALSE_ACRONYMS:
        return True

    # DOM/JSON/CSS/URI can be real, but usually supporting unless title-level topic.
    if pp in LOW_VALUE_ACRONYMS and pp.lower() not in title_low:
        return True

    return False

def _is_title_marketing_fragment(p: str) -> bool:
    p = _clean_phrase(p)
    low = p.lower()
    toks = [t.lower() for t in _tokens(p)]

    if not toks:
        return True

    if _is_file_artifact_phrase(p):
        return True

    if _is_low_value_singleton(p):
        return True

    if toks[-1] in {"w", "a", "an", "the", "to", "for", "with"}:
        return True

    if "production ready" in low:
        return True

    if low in {
        "production", "ready", "ready job", "a production", "production ready",
        "deploy production", "deploy production ready",
        "production ready job", "ready job application",
        "production ready job application", "ready job application tracker",
        "job application tracker w", "application tracker w",
        "real job application", "application tracker that",
    }:
        return True

    if len(toks) >= 3 and toks[0] in {"build", "deploy"}:
        return True

    if len(toks) >= 5 and toks[0] in {"understanding", "enhanced"}:
        return True

    if len(toks) <= 2 and all(t in LOW_VALUE_SINGLE_WORDS or t in TITLE_CONNECTOR_WORDS for t in toks):
        return True

    return False

def _make_items(scored, title_low: str):
    scored = sorted(
        scored,
        key=lambda x: (
            x[1],
            len([t for t in _tokens(x[0]) if t.lower() not in TITLE_CONNECTOR_WORDS]),
            len(_clean_phrase(x[0]))
        ),
        reverse=True,
    )

    core = []
    supporting = []
    rejected = []
    seen = set()

    for phrase, score, reason in scored:
        p = _clean_phrase(phrase)
        key = p.lower()

        if not p or key in seen:
            continue
        seen.add(key)

        if (
            _is_bad_phrase(p)
            or _is_title_marketing_fragment(p)
            or _is_file_artifact_phrase(p)
        ):
            if len(rejected) < 80:
                rejected.append({
                    "text": p,
                    "confidence": 0.2,
                    "evidence": ["title" if key in title_low else "transcript"],
                    "score": round(score, 2),
                    "reason": "rejected_fragment_marketing_subtitle_or_file_artifact",
                })
            continue

        item = {
            "text": p,
            "confidence": round(max(0.35, min(0.92, score / 10)), 2),
            "evidence": ["title" if key in title_low else "transcript"],
            "score": round(score, 2),
            "reason": reason,
        }

        if _is_low_value_acronym_core(p, title_low):
            if len(supporting) < 12 and p not in LIKELY_ASR_FALSE_ACRONYMS:
                item["reason"] = "supporting_low_value_acronym_not_title_topic"
                supporting.append(item)
            elif len(rejected) < 80:
                bad = dict(item)
                bad["reason"] = "rejected_likely_asr_false_acronym"
                rejected.append(bad)
            continue

        if score >= 5.2 and len(core) < 12:
            if _is_redundant_subphrase(p, core):
                if len(supporting) < 12:
                    item["reason"] = "supporting_redundant_or_less_specific"
                    supporting.append(item)
            else:
                core.append(item)
        elif score >= 3.2 and len(supporting) < 12:
            if not _is_redundant_subphrase(p, core):
                supporting.append(item)
        elif len(rejected) < 80:
            bad = dict(item)
            bad["reason"] = "low_score_or_fragment"
            rejected.append(bad)

    return core, supporting, rejected

_scc_v3_prev_apply_to_run_quality3 = apply_to_run

def apply_to_run(run_dir, title=None):
    payload = _scc_v3_prev_apply_to_run_quality3(run_dir, title=title)

    title_low = str(payload.get("title") or title or "").lower()

    core = []
    supporting = list(payload.get("supporting_terms", []))
    rejected = list(payload.get("rejected_false_positives", []))

    seen = set()

    for item in payload.get("core_concepts", []):
        text = _clean_phrase(item.get("text", ""))
        key = text.lower()

        if not text or key in seen:
            continue
        seen.add(key)

        new_item = dict(item)
        new_item["text"] = text

        if (
            _is_bad_phrase(text)
            or _is_title_marketing_fragment(text)
            or _is_file_artifact_phrase(text)
        ):
            new_item["reason"] = "rejected_after_quality_patch_3"
            rejected.append(new_item)
            continue

        if _is_low_value_acronym_core(text, title_low):
            if text not in LIKELY_ASR_FALSE_ACRONYMS:
                new_item["reason"] = "supporting_low_value_acronym_not_title_topic"
                supporting.append(new_item)
            else:
                new_item["reason"] = "rejected_likely_asr_false_acronym"
                rejected.append(new_item)
            continue

        if _is_redundant_subphrase(text, core):
            new_item["reason"] = "supporting_redundant_or_less_specific"
            supporting.append(new_item)
            continue

        core.append(new_item)

    # clean supporting too
    clean_supporting = []
    support_seen = set(x["text"].lower() for x in core if isinstance(x, dict) and x.get("text"))

    for item in supporting:
        text = _clean_phrase(item.get("text", ""))
        key = text.lower()

        if not text or key in support_seen:
            continue
        support_seen.add(key)

        if (
            _is_bad_phrase(text)
            or _is_title_marketing_fragment(text)
            or _is_file_artifact_phrase(text)
            or text in LIKELY_ASR_FALSE_ACRONYMS
        ):
            bad = dict(item)
            bad["text"] = text
            bad["reason"] = "rejected_supporting_after_quality_patch_3"
            rejected.append(bad)
            continue

        item = dict(item)
        item["text"] = text
        clean_supporting.append(item)

        if len(clean_supporting) >= 12:
            break

    core = core[:12]
    clean_supporting = clean_supporting[:12]
    rejected = rejected[:100]

    concept_score = min(9, max(1, int(round(len(core) * 0.6 + len(clean_supporting) * 0.15))))
    if len(core) < 5:
        concept_score = min(concept_score, 5)
    if len(core) < 3:
        concept_score = min(concept_score, 3)

    payload["core_concepts"] = core
    payload["supporting_terms"] = clean_supporting
    payload["rejected_false_positives"] = rejected
    payload["quality"] = {
        "concept_score": concept_score,
        "core_count": len(core),
        "supporting_count": len(clean_supporting),
        "rejected_count": len(rejected),
    }

    run_dir = Path(run_dir)
    _dump_json(run_dir / "concepts_v3.json", payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": payload.get("title", title or ""),
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in core
        ],
        "supporting_terms": clean_supporting,
        "rejected": rejected,
        "core_concepts": core,
        "quality": payload["quality"],
    }
    _dump_json(run_dir / "concepts.json", legacy)

    report_path = run_dir / "extraction_report.json"
    report = _load_json(report_path) or {}
    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(core)
            report["assets"]["supporting_terms"] = len(clean_supporting)
        _dump_json(report_path, report)

    return payload

# SCC_V3_QUALITY_PATCH_3_END

# SCC_V3_QUALITY_PATCH_4_START

GENERIC_SINGLE_CORE_BLOCK = {
    "application", "database", "data", "file", "files", "folder", "page",
    "project", "component", "components", "model", "models", "system",
    "systems", "workflow", "workflows", "table", "tables", "query",
    "queries", "field", "fields", "variable", "variables"
}

BAD_TRAILING_WORDS_PATCH4 = {
    "and", "or", "but", "with", "to", "from", "for", "like", "that",
    "this", "these", "those", "a", "an", "the"
}

BAD_GENERIC_PHRASES_PATCH4 = {
    "application from scratch",
    "real production style",
    "real job application",
    "dashboard like",
    "database and",
    "our database",
    "create a file",
    "application tracker that",
}

def _strip_bad_trailing_words_p4(p: str) -> str:
    p = _clean_phrase(p)
    toks = _tokens(p)

    while toks and toks[-1].lower() in BAD_TRAILING_WORDS_PATCH4:
        toks = toks[:-1]

    return _clean_phrase(" ".join(toks))

def _is_generic_single_core_block_p4(p: str) -> bool:
    toks = [t.lower() for t in _tokens(p)]
    return len(toks) == 1 and toks[0] in GENERIC_SINGLE_CORE_BLOCK

def _is_bad_generic_phrase_p4(p: str) -> bool:
    p2 = _strip_bad_trailing_words_p4(p)
    low = p2.lower()
    toks = [t.lower() for t in _tokens(p2)]

    if not toks:
        return True

    if _is_generic_single_core_block_p4(p2):
        return True

    if low in BAD_GENERIC_PHRASES_PATCH4:
        return True

    if "from scratch" in low:
        return True

    if len(toks) <= 2 and all(t in GENERIC_SINGLE_CORE_BLOCK or t in BAD_TRAILING_WORDS_PATCH4 for t in toks):
        return True

    # 너무 일반적인 말 + 형용사 조합
    if len(toks) == 2 and toks[-1] in GENERIC_SINGLE_CORE_BLOCK and toks[0] in {
        "real", "new", "main", "simple", "modern", "clean", "specific", "different"
    }:
        return True

    return False

_scc_v3_prev_apply_to_run_quality4 = apply_to_run

def apply_to_run(run_dir, title=None):
    payload = _scc_v3_prev_apply_to_run_quality4(run_dir, title=title)

    title_low = str(payload.get("title") or title or "").lower()

    core = []
    supporting = list(payload.get("supporting_terms", []))
    rejected = list(payload.get("rejected_false_positives", []))

    seen_core = set()

    for item in payload.get("core_concepts", []):
        text = _strip_bad_trailing_words_p4(item.get("text", ""))
        key = text.lower()

        if not text or key in seen_core:
            continue

        new_item = dict(item)
        new_item["text"] = text

        if (
            _is_bad_phrase(text)
            or _is_title_marketing_fragment(text)
            or _is_file_artifact_phrase(text)
            or _is_bad_generic_phrase_p4(text)
        ):
            new_item["reason"] = "rejected_after_quality_patch_4_generic_or_fragment"
            rejected.append(new_item)
            continue

        # single generic terms cannot be core unless title explicitly names them as product/framework.
        if _is_generic_single_core_block_p4(text) and key not in title_low:
            new_item["reason"] = "supporting_generic_single_not_core"
            supporting.append(new_item)
            continue

        # low-value acronyms stay supporting unless title-level topic.
        if _is_low_value_acronym_core(text, title_low):
            if text not in LIKELY_ASR_FALSE_ACRONYMS:
                new_item["reason"] = "supporting_low_value_acronym_not_title_topic"
                supporting.append(new_item)
            else:
                new_item["reason"] = "rejected_likely_asr_false_acronym"
                rejected.append(new_item)
            continue

        if _is_redundant_subphrase(text, core):
            new_item["reason"] = "supporting_redundant_or_less_specific"
            supporting.append(new_item)
            continue

        seen_core.add(key)
        core.append(new_item)

    # Supporting도 다시 정리
    clean_supporting = []
    seen_support = set(x["text"].lower() for x in core if isinstance(x, dict) and x.get("text"))

    for item in supporting:
        text = _strip_bad_trailing_words_p4(item.get("text", ""))
        key = text.lower()

        if not text or key in seen_support:
            continue

        if (
            _is_bad_phrase(text)
            or _is_title_marketing_fragment(text)
            or _is_file_artifact_phrase(text)
            or text in LIKELY_ASR_FALSE_ACRONYMS
            or _is_bad_generic_phrase_p4(text)
        ):
            bad = dict(item)
            bad["text"] = text
            bad["reason"] = "rejected_supporting_after_quality_patch_4"
            rejected.append(bad)
            continue

        item = dict(item)
        item["text"] = text
        clean_supporting.append(item)
        seen_support.add(key)

        if len(clean_supporting) >= 14:
            break

    core = core[:12]
    clean_supporting = clean_supporting[:14]
    rejected = rejected[:120]

    concept_score = min(9, max(1, int(round(len(core) * 0.65 + len(clean_supporting) * 0.12))))
    if len(core) < 5:
        concept_score = min(concept_score, 5)
    if len(core) < 3:
        concept_score = min(concept_score, 3)

    payload["core_concepts"] = core
    payload["supporting_terms"] = clean_supporting
    payload["rejected_false_positives"] = rejected
    payload["quality"] = {
        "concept_score": concept_score,
        "core_count": len(core),
        "supporting_count": len(clean_supporting),
        "rejected_count": len(rejected),
    }

    run_dir = Path(run_dir)
    _dump_json(run_dir / "concepts_v3.json", payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": payload.get("title", title or ""),
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in core
        ],
        "supporting_terms": clean_supporting,
        "rejected": rejected,
        "core_concepts": core,
        "quality": payload["quality"],
    }

    _dump_json(run_dir / "concepts.json", legacy)

    report_path = run_dir / "extraction_report.json"
    report = _load_json(report_path) or {}
    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(core)
            report["assets"]["supporting_terms"] = len(clean_supporting)
        _dump_json(report_path, report)

    return payload

# SCC_V3_QUALITY_PATCH_4_END

# SCC_V3_QUALITY_PATCH_5_START

BAD_VERB_START_PATCH5 = {
    "go", "watch", "learned", "learn", "participate", "participating",
    "through", "building", "build", "submit", "choose", "register",
    "made", "make", "see", "show", "use", "using"
}

BAD_MID_PATTERNS_PATCH5 = [
    r"\bgo through\b",
    r"\bwatch\b",
    r"\bparticipate in\b",
    r"\blearned on\b",
    r"\bthrough the\b",
    r"\bdoesn t\b",
    r"\bdon t\b",
    r"\bwe re\b",
    r"\byou re\b",
]

GENERIC_SINGLE_DEMOTE_PATCH5 = {
    "agent", "hackathon", "project", "challenge", "track", "tracks",
    "event", "content", "presentation", "academy"
}

def _is_action_fragment_p5(p: str) -> bool:
    p = _clean_phrase(p)
    low = p.lower()
    toks = [t.lower() for t in _tokens(p)]

    if not toks:
        return True

    if toks[0] in BAD_VERB_START_PATCH5:
        return True

    if any(re.search(pattern, low) for pattern in BAD_MID_PATTERNS_PATCH5):
        return True

    if toks[-1] in {"the", "a", "an", "to", "of", "in", "on", "through"}:
        return True

    # "agent doesn t", "model isn" 같은 잘린 부정문
    if len(toks) <= 3 and any(t in {"doesn", "isn", "don", "can"} for t in toks):
        return True

    return False

def _is_generic_single_demote_p5(p: str, title_low: str) -> bool:
    toks = [t.lower() for t in _tokens(p)]
    if len(toks) != 1:
        return False

    # 단일어가 제목에 있더라도, 복합 개념이 있으면 core보다 supporting이 낫다.
    return toks[0] in GENERIC_SINGLE_DEMOTE_PATCH5

_scc_v3_prev_apply_to_run_quality5 = apply_to_run

def apply_to_run(run_dir, title=None):
    payload = _scc_v3_prev_apply_to_run_quality5(run_dir, title=title)

    title_low = str(payload.get("title") or title or "").lower()

    core = []
    supporting = list(payload.get("supporting_terms", []))
    rejected = list(payload.get("rejected_false_positives", []))

    seen_core = set()

    for item in payload.get("core_concepts", []):
        text = _strip_bad_trailing_words_p4(item.get("text", ""))
        key = text.lower()

        if not text or key in seen_core:
            continue

        new_item = dict(item)
        new_item["text"] = text

        if (
            _is_bad_phrase(text)
            or _is_title_marketing_fragment(text)
            or _is_file_artifact_phrase(text)
            or _is_bad_generic_phrase_p4(text)
            or _is_action_fragment_p5(text)
        ):
            new_item["reason"] = "rejected_after_quality_patch_5_action_fragment"
            rejected.append(new_item)
            continue

        if _is_generic_single_demote_p5(text, title_low):
            new_item["reason"] = "supporting_generic_single_demoted_after_patch_5"
            supporting.append(new_item)
            continue

        if _is_redundant_subphrase(text, core):
            new_item["reason"] = "supporting_redundant_or_less_specific"
            supporting.append(new_item)
            continue

        seen_core.add(key)
        core.append(new_item)

    clean_supporting = []
    seen_support = set(x["text"].lower() for x in core if isinstance(x, dict) and x.get("text"))

    for item in supporting:
        text = _strip_bad_trailing_words_p4(item.get("text", ""))
        key = text.lower()

        if not text or key in seen_support:
            continue

        if (
            _is_bad_phrase(text)
            or _is_title_marketing_fragment(text)
            or _is_file_artifact_phrase(text)
            or _is_bad_generic_phrase_p4(text)
            or _is_action_fragment_p5(text)
            or text in LIKELY_ASR_FALSE_ACRONYMS
        ):
            bad = dict(item)
            bad["text"] = text
            bad["reason"] = "rejected_supporting_after_quality_patch_5"
            rejected.append(bad)
            continue

        item = dict(item)
        item["text"] = text
        clean_supporting.append(item)
        seen_support.add(key)

        if len(clean_supporting) >= 14:
            break

    core = core[:12]
    clean_supporting = clean_supporting[:14]
    rejected = rejected[:140]

    concept_score = min(9, max(1, int(round(len(core) * 0.65 + len(clean_supporting) * 0.12))))
    if len(core) < 5:
        concept_score = min(concept_score, 5)
    if len(core) < 3:
        concept_score = min(concept_score, 3)

    payload["core_concepts"] = core
    payload["supporting_terms"] = clean_supporting
    payload["rejected_false_positives"] = rejected
    payload["quality"] = {
        "concept_score": concept_score,
        "core_count": len(core),
        "supporting_count": len(clean_supporting),
        "rejected_count": len(rejected),
    }

    run_dir = Path(run_dir)
    _dump_json(run_dir / "concepts_v3.json", payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": payload.get("title", title or ""),
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in core
        ],
        "supporting_terms": clean_supporting,
        "rejected": rejected,
        "core_concepts": core,
        "quality": payload["quality"],
    }

    _dump_json(run_dir / "concepts.json", legacy)

    report_path = run_dir / "extraction_report.json"
    report = _load_json(report_path) or {}
    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(core)
            report["assets"]["supporting_terms"] = len(clean_supporting)
        _dump_json(report_path, report)

    return payload

# SCC_V3_QUALITY_PATCH_5_END

# SCC_V3_SCORE_CALIBRATION_PATCH_START

_scc_v3_prev_apply_to_run_score_calibration = apply_to_run

def apply_to_run(run_dir, title=None):
    payload = _scc_v3_prev_apply_to_run_score_calibration(run_dir, title=title)

    core = payload.get("core_concepts", [])
    supporting = payload.get("supporting_terms", [])
    rejected = list(payload.get("rejected_false_positives", []))

    # Clean remaining supporting action fragments.
    clean_supporting = []
    seen = set(x.get("text", "").lower() for x in core if isinstance(x, dict))

    for item in supporting:
        text = _strip_bad_trailing_words_p4(item.get("text", ""))
        key = text.lower()

        if not text or key in seen:
            continue

        if (
            _is_action_fragment_p5(text)
            or _is_bad_generic_phrase_p4(text)
            or _is_file_artifact_phrase(text)
            or text.lower() in {"agent academy the things", "include a working agent"}
        ):
            bad = dict(item)
            bad["text"] = text
            bad["reason"] = "rejected_supporting_after_score_calibration"
            rejected.append(bad)
            continue

        item = dict(item)
        item["text"] = text
        clean_supporting.append(item)
        seen.add(key)

        if len(clean_supporting) >= 14:
            break

    # Score calibration:
    # 3 good core concepts can be enough for short/event/overview videos.
    concept_score = min(9, max(1, int(round(len(core) * 0.75 + len(clean_supporting) * 0.15))))

    if len(core) >= 3:
        concept_score = max(concept_score, 5)
    if len(core) >= 5:
        concept_score = max(concept_score, 6)
    if len(core) >= 8:
        concept_score = max(concept_score, 7)

    payload["supporting_terms"] = clean_supporting
    payload["rejected_false_positives"] = rejected[:160]
    payload["quality"] = {
        "concept_score": concept_score,
        "core_count": len(core),
        "supporting_count": len(clean_supporting),
        "rejected_count": len(payload["rejected_false_positives"]),
    }

    run_dir = Path(run_dir)
    _dump_json(run_dir / "concepts_v3.json", payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": payload.get("title", title or ""),
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in core
        ],
        "supporting_terms": clean_supporting,
        "rejected": payload["rejected_false_positives"],
        "core_concepts": core,
        "quality": payload["quality"],
    }
    _dump_json(run_dir / "concepts.json", legacy)

    report_path = run_dir / "extraction_report.json"
    report = _load_json(report_path) or {}
    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(core)
            report["assets"]["supporting_terms"] = len(clean_supporting)
        _dump_json(report_path, report)

    return payload

# SCC_V3_SCORE_CALIBRATION_PATCH_END

# SCC_V3_ABSOLUTE_FINAL_CLEANER_START

_scc_v3_prev_apply_absolute_final = apply_to_run

_ABS_REJECT_EXACT = {
    "crash course",
    "full course",
    "complete course",
    "real time project",
    "network fundamentals part",
    "system design course",
    "complete terraform course",
    "full claude tutorial for beginners",
    "learn infrastructure",
    "code",
    "pro",
    "beginner",
    "beginners",
    "task",
    "feature",
    "prompt",
    "version",
    "cloud",
    "network",
    "url",
    "pdf",
    "gacao",
    "gcao",
    "emv",
}

_ABS_REJECT_CONTAINS = [
    " has many",
    " each router",
    "tables there",
    "on each router",
    "network so",
    "network each router",
    "task given",
    "chrome trigger right",
    "pipeline will keep",
    "two files one",
    "database in your",
    "python file so",
    "feature that claude",
    "files for me",
    "data to the client",
    "production environment. maybe",
]

_ABS_TITLE_BUNDLE_WORDS = {
    "and", "&", "using", "with"
}

_ABS_FALSE_ACRONYMS = {
    "EMV", "GCAO", "GCAO"
}

_ABS_GENERIC_SINGLE_DEMOTE = {
    "agent", "project", "course", "tutorial", "application",
    "database", "data", "file", "page", "cloud", "network",
    "task", "feature", "prompt", "version"
}

def _abs_clean_text(x):
    try:
        return _strip_bad_trailing_words_p4(str(x or ""))
    except Exception:
        return str(x or "").strip()

def _abs_tokens(x):
    try:
        return [t.lower() for t in _tokens(_abs_clean_text(x))]
    except Exception:
        return _abs_clean_text(x).lower().split()

def _abs_is_reject(text):
    p = _abs_clean_text(text)
    low = p.lower()
    toks = _abs_tokens(p)

    if not p or not toks:
        return True

    if low in _ABS_REJECT_EXACT:
        return True

    if p.upper() in _ABS_FALSE_ACRONYMS:
        return True

    if any(bad in low for bad in _ABS_REJECT_CONTAINS):
        return True

    if len(toks) == 1 and toks[0] in _ABS_REJECT_EXACT:
        return True

    # 긴 제목 묶음 제거
    if len(toks) >= 7 and any(w in low for w in [" and ", " & ", " using ", " with "]):
        return True

    # 강의 제목 장식어 제거
    if "crash course" in low:
        return True
    if "full course" in low:
        return True
    if "real time project" in low:
        return True
    if "for beginners" in low and "claude tutorial" in low:
        return True
    if re.search(r"\bpart\s+\d+\b", low):
        return True

    # 잘린 문장 조각
    if toks[-1] in {"so", "there", "your", "our", "that", "this", "maybe", "and"}:
        return True

    if len(toks) <= 4 and any(t in {"has", "many", "there", "each", "your", "our", "so", "maybe"} for t in toks):
        return True

    return False

def _abs_should_demote(text):
    toks = _abs_tokens(text)
    return len(toks) == 1 and toks[0] in _ABS_GENERIC_SINGLE_DEMOTE

def apply_to_run(run_dir, title=None):
    payload = _scc_v3_prev_apply_absolute_final(run_dir, title=title)

    rejected = list(payload.get("rejected_false_positives", []))
    supporting = list(payload.get("supporting_terms", []))

    core = []
    seen_core = set()

    for item in payload.get("core_concepts", []):
        text = _abs_clean_text(item.get("text", ""))
        key = text.lower()

        if not text or key in seen_core:
            continue

        new_item = dict(item)
        new_item["text"] = text

        if _abs_is_reject(text):
            new_item["reason"] = "rejected_by_absolute_final_cleaner"
            rejected.append(new_item)
            continue

        if _abs_should_demote(text):
            new_item["reason"] = "supporting_generic_single_by_absolute_final_cleaner"
            supporting.append(new_item)
            continue

        core.append(new_item)
        seen_core.add(key)

    clean_supporting = []
    seen = set(x.get("text", "").lower() for x in core if isinstance(x, dict))

    for item in supporting:
        text = _abs_clean_text(item.get("text", ""))
        key = text.lower()

        if not text or key in seen:
            continue

        if _abs_is_reject(text):
            bad = dict(item)
            bad["text"] = text
            bad["reason"] = "rejected_supporting_by_absolute_final_cleaner"
            rejected.append(bad)
            continue

        item = dict(item)
        item["text"] = text
        clean_supporting.append(item)
        seen.add(key)

        if len(clean_supporting) >= 14:
            break

    core = core[:12]
    clean_supporting = clean_supporting[:14]
    rejected = rejected[:220]

    concept_score = min(9, max(1, int(round(len(core) * 0.75 + len(clean_supporting) * 0.15))))
    if len(core) >= 3:
        concept_score = max(concept_score, 5)
    if len(core) >= 5:
        concept_score = max(concept_score, 6)
    if len(core) >= 8:
        concept_score = max(concept_score, 7)

    payload["core_concepts"] = core
    payload["supporting_terms"] = clean_supporting
    payload["rejected_false_positives"] = rejected
    payload["quality"] = {
        "concept_score": concept_score,
        "core_count": len(core),
        "supporting_count": len(clean_supporting),
        "rejected_count": len(rejected),
    }

    run_dir = Path(run_dir)
    _dump_json(run_dir / "concepts_v3.json", payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": payload.get("title", title or ""),
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in core
        ],
        "supporting_terms": clean_supporting,
        "rejected": rejected,
        "core_concepts": core,
        "quality": payload["quality"],
    }
    _dump_json(run_dir / "concepts.json", legacy)

    report_path = run_dir / "extraction_report.json"
    report = _load_json(report_path) or {}
    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(core)
            report["assets"]["supporting_terms"] = len(clean_supporting)
        _dump_json(report_path, report)

    return payload

# SCC_V3_ABSOLUTE_FINAL_CLEANER_END

# SCC_V3_TITLE_RESCUE_AND_DEDUPE_START

_scc_v3_prev_apply_title_rescue = apply_to_run

_TITLE_RESCUE_DECOR_WORDS = {
    "complete", "full", "course", "tutorial", "crash", "beginner",
    "beginners", "pro", "learn", "from", "to", "part", "real", "time",
    "project", "for", "in"
}

_TITLE_RESCUE_REJECT_EXACT = {
    "complete",
    "course",
    "full",
    "tutorial",
    "crash course",
    "full course",
    "complete course",
    "from beginner to pro",
    "beginner to pro",
    "real time project",
}

def _title_rescue_clean_phrase(text: str) -> str:
    p = _abs_clean_text(text)
    p = re.sub(r"\b(Complete|FULL|Full|Course|Tutorial|Crash Course)\b", "", p, flags=re.I)
    p = re.sub(r"\bFrom\s+BEGINNER\s+to\s+PRO\b", "", p, flags=re.I)
    p = re.sub(r"\bFor\s+Beginners\b", "", p, flags=re.I)
    p = re.sub(r"\bLearn\s+", "", p, flags=re.I)
    p = re.sub(r"\bPart\s+\d+\b", "", p, flags=re.I)
    p = re.sub(r"\b\d{4}\b", "", p)
    p = re.sub(r"\b\d+/\d+\b", "", p)
    p = re.sub(r"\s+", " ", p).strip(" -–—|:[]()!,")
    return _abs_clean_text(p)

def _title_rescue_candidates(title: str):
    title = str(title or "")
    out = []

    # Bracket/parenthesis 안의 개념 먼저 살림: [API, SQL Databases...] / (Infrastructure as Code)
    for inner in re.findall(r"[\[\(]([^\]\)]+)[\]\)]", title):
        for part in re.split(r",|/|&|\band\b", inner, flags=re.I):
            p = _title_rescue_clean_phrase(part)
            if p:
                out.append(p)

    # 큰 제목 조각
    for part in re.split(r"\s+\|\s+|[-–—:]", title):
        p = _title_rescue_clean_phrase(part)
        if p:
            out.append(p)

        # using 뒤의 도구명 살림: Using Terraform and GitHub Actions
        m = re.search(r"\bUsing\s+(.+)$", part, flags=re.I)
        if m:
            for sub in re.split(r",|/|&|\band\b", m.group(1), flags=re.I):
                s = _title_rescue_clean_phrase(sub)
                if s:
                    out.append(s)

    # comma separated title concepts
    for part in re.split(r",", title):
        p = _title_rescue_clean_phrase(part)
        if p:
            out.append(p)

    # 너무 긴 묶음은 버리고, 너무 짧은 장식어도 버림
    clean = []
    seen = set()
    for p in out:
        low = p.lower()
        toks = _abs_tokens(p)

        if not p or low in seen:
            continue
        seen.add(low)

        if low in _TITLE_RESCUE_REJECT_EXACT:
            continue
        if _abs_is_reject(p):
            continue
        if len(toks) >= 7:
            continue
        if len(toks) == 1 and toks[0] in _TITLE_RESCUE_DECOR_WORDS:
            continue

        clean.append(p)

    return clean

def _canon_concept_key(text: str) -> str:
    p = _abs_clean_text(text).lower()
    p = re.sub(r"[^a-z0-9+#.\s-]", " ", p)
    p = re.sub(r"\s+", " ", p).strip()

    toks = p.split()
    norm = []
    for t in toks:
        # APIs -> api, Databases -> database, Protocols -> protocol 정도의 중복 제거용
        if len(t) > 3 and t.endswith("s") and t not in {"aws", "dns", "css"}:
            t = t[:-1]
        norm.append(t)

    return " ".join(norm)

def apply_to_run(run_dir, title=None):
    payload = _scc_v3_prev_apply_title_rescue(run_dir, title=title)

    title_text = str(payload.get("title") or title or "")
    rejected = list(payload.get("rejected_false_positives", []))
    supporting = list(payload.get("supporting_terms", []))

    core = []
    seen = set()

    # 1) 기존 core 중복 제거
    for item in payload.get("core_concepts", []):
        text = _abs_clean_text(item.get("text", ""))
        key = _canon_concept_key(text)

        if not text or key in seen:
            bad = dict(item)
            bad["text"] = text
            bad["reason"] = "rejected_duplicate_by_title_rescue"
            rejected.append(bad)
            continue

        item = dict(item)
        item["text"] = text
        core.append(item)
        seen.add(key)

    # 2) 현재 title에서 빠진 핵심어만 rescue
    for p in _title_rescue_candidates(title_text):
        key = _canon_concept_key(p)

        if not p or key in seen:
            continue

        item = {
            "text": p,
            "confidence": 0.86,
            "evidence": ["title"],
            "score": 8.6,
            "reason": "rescued_from_current_run_title",
        }

        # 단일 일반어는 rescue하지 않음
        if _abs_should_demote(p):
            supporting.append(item)
            continue

        core.append(item)
        seen.add(key)

        if len(core) >= 12:
            break

    # 3) supporting도 core와 중복 제거
    clean_supporting = []
    seen_support = set(seen)

    for item in supporting:
        text = _abs_clean_text(item.get("text", ""))
        key = _canon_concept_key(text)

        if not text or key in seen_support:
            continue

        if _abs_is_reject(text):
            bad = dict(item)
            bad["text"] = text
            bad["reason"] = "rejected_supporting_by_title_rescue"
            rejected.append(bad)
            continue

        item = dict(item)
        item["text"] = text
        clean_supporting.append(item)
        seen_support.add(key)

        if len(clean_supporting) >= 14:
            break

    core = core[:12]
    clean_supporting = clean_supporting[:14]
    rejected = rejected[:260]

    concept_score = min(9, max(1, int(round(len(core) * 0.75 + len(clean_supporting) * 0.15))))
    if len(core) >= 3:
        concept_score = max(concept_score, 5)
    if len(core) >= 5:
        concept_score = max(concept_score, 6)
    if len(core) >= 8:
        concept_score = max(concept_score, 7)

    payload["core_concepts"] = core
    payload["supporting_terms"] = clean_supporting
    payload["rejected_false_positives"] = rejected
    payload["quality"] = {
        "concept_score": concept_score,
        "core_count": len(core),
        "supporting_count": len(clean_supporting),
        "rejected_count": len(rejected),
    }

    run_dir = Path(run_dir)
    _dump_json(run_dir / "concepts_v3.json", payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": payload.get("title", title or ""),
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in core
        ],
        "supporting_terms": clean_supporting,
        "rejected": rejected,
        "core_concepts": core,
        "quality": payload["quality"],
    }
    _dump_json(run_dir / "concepts.json", legacy)

    report_path = run_dir / "extraction_report.json"
    report = _load_json(report_path) or {}
    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(core)
            report["assets"]["supporting_terms"] = len(clean_supporting)
        _dump_json(report_path, report)

    return payload

# SCC_V3_TITLE_RESCUE_AND_DEDUPE_END

# SCC_V3_RESCUE_CLEANUP_PATCH_START

_scc_v3_prev_apply_rescue_cleanup = apply_to_run

_RESCUE_CLEAN_REJECT_EXACT = {
    "30 30",
    "network fundamentals",
    "network fundamentals part",
    "terraform - infrastructure as code",
    "claude in",
    "system design apis",
    "python for web development api",
    "load balancing & production infra",
    "cloud infrastructure in general",
    "protocols and traffic",
    "routing protocols and traffic",
    "protocols and traffic forwarding",
    "network imagine",
    "complete terraform",
    "database similar",
    "clawed models",
}

_RESCUE_CLEAN_DEMOTE_EXACT = {
    "google",
    "actual database",
    "create a database",
    "generic prompt",
}

def _rescue_cleanup_key(text: str) -> str:
    return _abs_clean_text(text).lower().strip()

def _rescue_cleanup_reject(text: str) -> bool:
    low = _rescue_cleanup_key(text)
    toks = _abs_tokens(text)

    if not low:
        return True

    if low in _RESCUE_CLEAN_REJECT_EXACT:
        return True

    # "Claude in", "Python ... API" 같은 구조적 찌꺼기
    if len(toks) >= 3 and low.endswith(" api") and "web development" in low:
        return True

    if len(toks) >= 3 and low.endswith("apis") and "system design" in low:
        return True

    if " in general" in low:
        return True

    if re.search(r"^\d+\s+\d+$", low):
        return True

    # 이미 더 작은 핵심어가 있으므로 복합 중복 조각 제거
    if " - infrastructure as code" in low:
        return True

    if low.endswith(" in"):
        return True

    return False

def _rescue_cleanup_demote(text: str) -> bool:
    return _rescue_cleanup_key(text) in _RESCUE_CLEAN_DEMOTE_EXACT

def apply_to_run(run_dir, title=None):
    payload = _scc_v3_prev_apply_rescue_cleanup(run_dir, title=title)

    rejected = list(payload.get("rejected_false_positives", []))
    supporting = list(payload.get("supporting_terms", []))

    core = []
    seen_core = set()

    for item in payload.get("core_concepts", []):
        text = _abs_clean_text(item.get("text", ""))
        key = _canon_concept_key(text)

        if not text or key in seen_core:
            continue

        new_item = dict(item)
        new_item["text"] = text

        if _rescue_cleanup_reject(text):
            new_item["reason"] = "rejected_by_rescue_cleanup_patch"
            rejected.append(new_item)
            continue

        if _rescue_cleanup_demote(text):
            new_item["reason"] = "supporting_by_rescue_cleanup_patch"
            supporting.append(new_item)
            continue

        core.append(new_item)
        seen_core.add(key)

    clean_supporting = []
    seen = set(_canon_concept_key(x.get("text", "")) for x in core if isinstance(x, dict))

    for item in supporting:
        text = _abs_clean_text(item.get("text", ""))
        key = _canon_concept_key(text)

        if not text or key in seen:
            continue

        if _rescue_cleanup_reject(text) or _abs_is_reject(text):
            bad = dict(item)
            bad["text"] = text
            bad["reason"] = "rejected_supporting_by_rescue_cleanup_patch"
            rejected.append(bad)
            continue

        item = dict(item)
        item["text"] = text
        clean_supporting.append(item)
        seen.add(key)

        if len(clean_supporting) >= 14:
            break

    core = core[:12]
    clean_supporting = clean_supporting[:14]
    rejected = rejected[:300]

    concept_score = min(9, max(1, int(round(len(core) * 0.75 + len(clean_supporting) * 0.15))))
    if len(core) >= 3:
        concept_score = max(concept_score, 5)
    if len(core) >= 5:
        concept_score = max(concept_score, 6)
    if len(core) >= 8:
        concept_score = max(concept_score, 7)

    payload["core_concepts"] = core
    payload["supporting_terms"] = clean_supporting
    payload["rejected_false_positives"] = rejected
    payload["quality"] = {
        "concept_score": concept_score,
        "core_count": len(core),
        "supporting_count": len(clean_supporting),
        "rejected_count": len(rejected),
    }

    run_dir = Path(run_dir)
    _dump_json(run_dir / "concepts_v3.json", payload)

    legacy = {
        "extractor": "concept_extractor_v3_runtime",
        "title": payload.get("title", title or ""),
        "accepted": [
            {
                "text": x["text"],
                "evidence": x.get("evidence", ["transcript"]),
                "confidence": x.get("confidence", 0.7),
                "status": "accepted",
                "reason": x.get("reason", ""),
            }
            for x in core
        ],
        "supporting_terms": clean_supporting,
        "rejected": rejected,
        "core_concepts": core,
        "quality": payload["quality"],
    }
    _dump_json(run_dir / "concepts.json", legacy)

    report_path = run_dir / "extraction_report.json"
    report = _load_json(report_path) or {}
    if isinstance(report, dict):
        report["concept_extractor"] = "concept_extractor_v3_runtime"
        report.setdefault("scores", {})
        if isinstance(report["scores"], dict):
            report["scores"]["concepts"] = concept_score
        report.setdefault("assets", {})
        if isinstance(report["assets"], dict):
            report["assets"]["concepts_v3"] = True
            report["assets"]["core_concepts"] = len(core)
            report["assets"]["supporting_terms"] = len(clean_supporting)
        _dump_json(report_path, report)

    return payload

# SCC_V3_RESCUE_CLEANUP_PATCH_END
