from __future__ import annotations

import base64
import cgi
import json
import mimetypes
import os
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CAPTURE_DIR = DATA_DIR / "captures"
NOTES_PATH = DATA_DIR / "notes.jsonl"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
NOTES_PATH.touch(exist_ok=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


@dataclass
class StudyNote:
    id: str
    created_at: str
    title: str
    source_type: str
    tags: list[str]
    raw_text: str
    user_memo: str
    summary: str
    action_items: list[str]
    blog_draft: str
    image_path: str | None = None


class LLM:
    def __init__(self) -> None:
        self.client = None

    def get_client(self) -> Any:
        if self.client:
            return self.client
        if not GROQ_API_KEY:
            return None
        try:
            from groq import Groq
        except ModuleNotFoundError:
            return None
        self.client = Groq(api_key=GROQ_API_KEY, timeout=20.0)
        return self.client

    def generate_note(self, raw_text: str, memo: str) -> dict[str, Any]:
        if not raw_text.strip() and not memo.strip():
            return fallback_note(raw_text, memo)

        client = self.get_client()
        if not client:
            return fallback_note(raw_text, memo)

        prompt = f"""
아래 학습 화면/실습 기록을 기술 노트로 정리해 주세요.

규칙:
- 한국어로 작성합니다.
- 과장하지 말고 입력에 있는 내용만 사용합니다.
- JSON만 반환합니다.
- keys: title, source_type, tags, summary, action_items, blog_draft
- summary는 문제 인식, 핵심 개념, 실습 흐름, 막힌 지점, 해결 방향을 포함합니다.
- blog_draft는 기술블로그 초안처럼 제목/배경/실습/배운점 구조로 작성합니다.

[화면 텍스트]
{raw_text}

[사용자 메모]
{memo}
""".strip()
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=0.2,
                max_tokens=1200,
                messages=[
                    {
                        "role": "system",
                        "content": "You convert study captures into structured developer learning notes. Return strict JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            content = completion.choices[0].message.content or ""
            return parse_json_or_fallback(content, raw_text, memo)
        except Exception:
            return fallback_note(raw_text, memo)

    def generate_note_from_image(self, image_file: Path, memo: str) -> dict[str, Any]:
        client = self.get_client()
        if not client:
            return image_only_note(f"/captures/{image_file.name}")

        mime_type = mimetypes.guess_type(image_file.name)[0] or "image/png"
        image_data = base64.b64encode(image_file.read_bytes()).decode("ascii")
        prompt = f"""
아래 이미지는 사용자가 학습 중 캡처한 화면입니다. 화면을 읽고 포트폴리오용 학습 노트로 정리해 주세요.

규칙:
- 한국어로 작성합니다.
- 화면에 보이는 내용과 사용자 메모만 근거로 사용합니다.
- JSON만 반환합니다.
- keys: title, source_type, tags, summary, action_items, blog_draft
- summary에는 무엇을 학습/실습 중인지, 발견한 문제나 확인 포인트, 다음에 정리할 내용을 포함합니다.
- blog_draft는 문제 해결형 기술블로그 초안처럼 제목/배경/문제 인식/해결 흐름/배운 점 구조로 작성합니다.

[사용자 메모]
{memo}
""".strip()
        try:
            completion = client.chat.completions.create(
                model=GROQ_VISION_MODEL,
                temperature=0.2,
                max_tokens=1300,
                messages=[
                    {
                        "role": "system",
                        "content": "You read study screenshots and turn them into structured developer learning notes. Return strict JSON.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                            },
                        ],
                    },
                ],
            )
            content = completion.choices[0].message.content or ""
            return parse_json_or_fallback(content, "", memo)
        except Exception:
            return image_only_note(f"/captures/{image_file.name}")

    def synthesize_blog(self, notes: list[StudyNote], topic: str, format_type: str) -> str:
        notes = [note for note in notes if is_meaningful_note(note)][-3:]
        if not notes:
            return "블로그 초안을 만들 수 있는 학습 노트가 아직 없습니다. 스크린샷을 업로드하거나 메모를 입력한 뒤 먼저 노트를 생성해 주세요."

        if format_type == "problem-solving-portfolio":
            return local_portfolio_blog(notes, topic)
        return local_study_blog(notes, topic)

        joined = "\n\n".join(
            f"- {note.title}\n{note.summary[:900]}\nAction: {', '.join(note.action_items[:4])}"
            for note in notes
        )
        client = self.get_client()
        if not client:
            return fallback_blog(notes, topic, format_type)

        prompt = portfolio_prompt(topic, joined) if format_type == "problem-solving-portfolio" else study_blog_prompt(topic, joined)
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=0.25,
                max_tokens=1000,
                messages=[
                    {"role": "system", "content": "You write grounded technical blog drafts from study notes."},
                    {"role": "user", "content": prompt},
                ],
            )
            return completion.choices[0].message.content or fallback_blog(notes, topic, format_type)
        except Exception:
            return fallback_blog(notes, topic, format_type)


llm = LLM()


def parse_json_or_fallback(content: str, raw_text: str, memo: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return fallback_note(raw_text, memo)
    return {
        "title": str(data.get("title") or "학습 기록"),
        "source_type": str(data.get("source_type") or "study-capture"),
        "tags": [str(tag) for tag in data.get("tags", [])][:8],
        "summary": stringify_field(data.get("summary") or ""),
        "action_items": [str(item) for item in data.get("action_items", [])][:8],
        "blog_draft": stringify_field(data.get("blog_draft") or ""),
    }


def stringify_field(value: Any) -> str:
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            title = str(key).replace("_", " ").strip().title()
            lines.append(f"## {title}\n{stringify_field(item)}")
        return "\n\n".join(lines)
    if isinstance(value, list):
        return "\n".join(f"- {stringify_field(item)}" for item in value)
    return str(value)


def fallback_note(raw_text: str, memo: str) -> dict[str, Any]:
    source = "\n".join(part for part in [raw_text.strip(), memo.strip()] if part)
    preview = source[:900] if source else "입력된 텍스트가 없습니다."
    return {
        "title": "학습 캡처 기록",
        "source_type": "study-capture",
        "tags": ["study-note", "capture"],
        "summary": f"입력 내용을 기반으로 기본 노트를 생성했습니다.\n\n{preview}",
        "action_items": ["핵심 개념 다시 정리", "막힌 지점과 해결 방법 추가 기록", "문제 해결형 글로 변환"],
        "blog_draft": f"# 학습 캡처 기록\n\n## 기록 내용\n{preview}\n\n## 다음 정리\n- 핵심 개념\n- 실습 흐름\n- 문제 해결 과정\n",
    }


def local_study_blog(notes: list[StudyNote], topic: str) -> str:
    note = notes[-1]
    actions = "\n".join(f"- {item}" for item in note.action_items[:5]) or "- 추가 정리 필요"
    return f"""# {topic}

## 학습 배경
이번 기록은 `{note.title}` 학습 화면을 바탕으로 정리한 기술 노트입니다. 화면에서 확인한 내용과 생성된 노트를 기준으로, 실습의 흐름과 다음 점검 항목을 정리했습니다.

## 핵심 내용
{note.summary}

## 다음 작업
{actions}

## 정리
이 기록은 단순 캡처가 아니라, 학습 중 발견한 화면과 판단 지점을 다시 검토하기 위한 자료입니다. 이후 관련 수식, 쿼리, 설정값을 추가하면 문제 해결형 포트폴리오 글로 확장할 수 있습니다.
"""


def local_portfolio_blog(notes: list[StudyNote], topic: str) -> str:
    note = notes[-1]
    actions = "\n".join(f"- {item}" for item in note.action_items[:5]) or "- 추가 정리 필요"
    return f"""# {note.title}: 문제 해결형 학습 기록

_A problem-solving portfolio note from a study capture_

## 도입부
이번 기록은 `{topic}` 과정에서 생성한 학습 캡처를 바탕으로 작성했습니다. 화면에서 확인한 실습 내용은 단순 기능 사용이 아니라, 데이터 모델과 계산 결과가 왜 예상과 다르게 보이는지 확인하는 과정에 가깝습니다.

핵심 작업은 다음과 같습니다.

```text
- 화면 캡처를 학습 근거로 저장
- 실습 화면에서 주요 테이블, 지표, 관계 설정 포인트 확인
- 생성된 노트를 바탕으로 문제 인식과 다음 점검 항목 정리
```

## 문제 인식
{note.summary}

## 문제 정의
현재 실습에서 확인해야 할 문제는 화면에 보이는 결과값과 데이터 모델 설정이 의도한 분석 흐름과 일치하는지 검증하는 것입니다.

## 왜 이것을 문제로 인식했는가
Power BI, SQL, DAX, 모델링 실습에서는 화면에 값이 표시되는 것만으로는 충분하지 않습니다. 관계 설정, 계산식, 필터 컨텍스트가 잘못되면 보고서에 보이는 값은 그럴듯해도 실제 해석은 틀릴 수 있습니다. 따라서 실습 화면에서 이상한 값, 반복되는 합계, 0으로 표시되는 지표, 관계 설정 단계를 발견하면 이를 문제로 정의하고 원인을 좁혀야 합니다.

## 문제 해결 경험
1. 화면에서 현재 실습 단계와 표시된 결과를 먼저 확인했습니다.
2. 지표, 테이블, 관계 설정, 계산식 중 어떤 요소가 결과에 영향을 주는지 나누어 보았습니다.
3. 다음 점검 항목을 액션으로 분리해 이후 실습에서 재현하고 검증할 수 있도록 정리했습니다.

## 복잡한 문제 해결 경험
이 유형의 문제는 단순히 버튼을 누르는 문제가 아니라, 데이터 모델의 관계와 계산 흐름을 함께 확인해야 합니다. 특히 Power BI에서는 관계 방향, many-to-many 관계, measure 계산, 필터 컨텍스트가 결과값에 직접 영향을 줍니다. 따라서 화면 캡처를 기록으로 남기고, 어떤 지점에서 값이 달라졌는지 추적하는 방식이 중요합니다.

## 성과
이번 캡처를 통해 실습 화면을 단순히 지나치지 않고, 추후 포트폴리오 글로 확장할 수 있는 문제 해결 기록으로 전환했습니다. 이후 같은 방식으로 오류 화면, DAX 수식, SQL 쿼리, 모델링 설정을 누적하면 학습 과정 자체가 기술블로그와 포트폴리오 자료가 됩니다.

## 사용한 주요 수식/코드 정리
현재 캡처에는 별도의 코드나 수식이 직접 입력되지 않았습니다. 추후 DAX, SQL, Power Query 수식을 메모에 추가하면 이 섹션에 자동으로 정리할 수 있습니다.

## 다음 작업
{actions}

## 최종 정리
이 기록의 핵심은 학습 화면을 저장하는 데서 끝내지 않고, 화면에서 확인한 문제와 다음 검증 항목을 구조화했다는 점입니다. 이는 실무에서도 오류 화면, 분석 결과, 설정 변경 내역을 근거와 함께 남기는 방식으로 확장될 수 있습니다.

## Portfolio Summary
- Captured a technical learning screen and converted it into a structured problem-solving note.
- Identified model/result validation points from the visible interface.
- Organized follow-up actions for reproducible learning and documentation.

## Key skills practiced
- Technical documentation
- Problem framing
- Data model validation
- Portfolio writing workflow
"""


def image_only_note(image_path: str) -> dict[str, Any]:
    return {
        "title": "이미지 학습 캡처",
        "source_type": "study-capture-image",
        "tags": ["study-note", "screenshot", "needs-ocr"],
        "summary": (
            "스크린샷을 학습 근거 자료로 저장했습니다.\n\n"
            "이미지와 함께 화면에서 확인한 핵심 문장, 오류 메시지, 실습 목표를 메모하면 "
            "노트와 문제 해결형 포트폴리오 초안을 더 정확하게 구성할 수 있습니다.\n\n"
            f"저장된 이미지: {image_path}"
        ),
        "action_items": [
            "화면 속 핵심 텍스트를 raw text에 붙여넣기",
            "내가 발견한 문제와 해결 과정을 memo에 추가하기",
            "추후 OCR 또는 Vision API로 이미지 텍스트 자동 추출 연결하기",
        ],
        "blog_draft": (
            "# 이미지 기반 학습 캡처\n\n"
            "## 캡처 내용\n"
            "스크린샷이 저장되었습니다. 현재 버전에서는 이미지 속 텍스트를 자동 추출하지 않으므로, "
            "실습 목표와 문제 상황을 텍스트로 함께 기록하면 문제 해결형 포트폴리오 글로 확장할 수 있습니다.\n\n"
            "## 다음 정리\n"
            "- 화면에서 확인한 실습 주제\n"
            "- 발견한 이상 현상 또는 막힌 지점\n"
            "- 해결한 방법과 사용한 수식/쿼리/설정\n"
        ),
    }


def study_blog_prompt(topic: str, joined_notes: str) -> str:
    return f"""
다음 학습 노트들을 바탕으로 기술블로그 초안을 작성해 주세요.

조건:
- 한국어
- 제목, 문제 인식, 실습 흐름, 핵심 개념, 막힌 점과 해결, 배운 점, 다음 학습 계획 포함
- 실제 입력에 없는 성과나 수치는 만들지 않음

[주제]
{topic}

[노트]
{joined_notes}
""".strip()


def portfolio_prompt(topic: str, joined_notes: str) -> str:
    return f"""
아래 실습/프로젝트 기록을 바탕으로 Medium 블로그 글을 작성해 주세요.

글의 목적은 단순 후기나 요약이 아니라, 포트폴리오용 문제 해결 경험 글입니다.
반드시 아래 구조로 작성해 주세요.

1. 제목
- 한국어 제목
- 가능하면 영어 부제 포함

2. 도입부
- 이 실습/프로젝트에서 무엇을 했는지 2~3문단으로 설명
- 핵심 작업을 bullet 또는 code block 형태로 정리

3. 본문 구조
- 문제 인식: 처음 어떤 이상 현상/불편/한계를 발견했는지
- 문제 정의: 그 문제가 정확히 무엇인지 한 문장으로 정의
- 왜 이것을 문제로 인식했는가: 결과 패턴, 비즈니스 해석, 데이터 모델 관점에서 설명
- 문제 해결 경험 1, 2, 3...: 실제 해결 과정을 단계별로 설명
- 복잡한 문제 해결 경험: 관계, 필터 컨텍스트, DAX, SQL, 쿼리, 모델링 등 어려웠던 부분을 따로 강조
- 성과: 해결 후 무엇이 가능해졌는지, 보고서/모델/분석 관점에서 정리
- 사용한 주요 수식/코드 정리
- 최종 정리
- Portfolio Summary
- Key skills practiced

4. 문체
- 너무 강의식 말투 말고, 작성자가 직접 문제를 발견하고 해결한 경험처럼 작성
- "했습니다" 반복을 줄이고, 분석/설계/해결/구성/확인 중심으로 작성
- 취업 포트폴리오에 쓸 수 있게 실무적인 표현으로 정리
- 단순 기능 설명보다 왜 이 작업이 필요했는지와 어떤 문제를 해결했는지 강조

5. 이미지
- 입력에 이미지 설명이 있으면 이미지 순서대로 번호와 캡션을 붙임
- 본문 안에는 "이미지 1 - 제목" 형식으로 캡션만 넣음
- 마지막에 이미지 번호와 캡션 목록을 따로 정리

6. 코드/수식
- DAX, SQL, Python, Power Query 등이 있으면 코드블록으로 정리
- 수식은 단순히 붙이지 말고 각 수식이 어떤 문제를 해결했는지 설명

[주제]
{topic}

[실습/프로젝트 기록]
{joined_notes}
""".strip()


def read_notes() -> list[StudyNote]:
    notes: list[StudyNote] = []
    for line in NOTES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            notes.append(StudyNote(**json.loads(line)))
        except Exception:
            continue
    return notes


def is_meaningful_note(note: StudyNote) -> bool:
    summary = note.summary or ""
    if "입력된 텍스트가 없습니다" in summary:
        return False
    if note.source_type == "study-capture-image" and (
        "스크린샷을 학습 근거 자료로 저장했습니다" in summary
        or "스크린샷을 학습 캡처로 저장했습니다" in summary
    ):
        return False
    return True


def append_note(note: StudyNote) -> None:
    with NOTES_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(note), ensure_ascii=False) + "\n")


def search_notes(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    q_terms = set(tokenize(query))
    scored = []
    for note in read_notes():
        text = " ".join([note.title, note.summary, note.raw_text, note.user_memo, " ".join(note.tags)])
        terms = set(tokenize(text))
        score = len(q_terms & terms) / max(len(q_terms | terms), 1)
        if query.lower() in text.lower():
            score += 0.5
        if score > 0:
            scored.append((score, note))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [{"score": round(score, 3), "note": asdict(note)} for score, note in scored[:top_k]]


def tokenize(text: str) -> list[str]:
    return [chunk.strip(".,:;()[]{}<>\"'").lower() for chunk in text.split() if len(chunk.strip()) >= 2]


def make_note(raw_text: str, memo: str, image_path: str | None) -> StudyNote:
    if image_path and not raw_text.strip() and not memo.strip():
        generated = llm.generate_note_from_image(CAPTURE_DIR / image_path.removeprefix("/captures/"), memo)
    elif image_path and not raw_text.strip() and memo.strip():
        generated = llm.generate_note_from_image(CAPTURE_DIR / image_path.removeprefix("/captures/"), memo)
    else:
        generated = llm.generate_note(raw_text, memo)
    created_at = datetime.now().isoformat(timespec="seconds")
    title = generated["title"]
    if title in {"학습 캡처 기록", "이미지 학습 캡처", "이미지 기반 학습 캡처"}:
        label = "이미지" if image_path else "학습"
        title = f"{label} 캡처 {datetime.now().strftime('%H:%M')}"
    return StudyNote(
        id=str(uuid.uuid4()),
        created_at=created_at,
        title=title,
        source_type=generated["source_type"],
        tags=generated["tags"],
        raw_text=raw_text,
        user_memo=memo,
        summary=generated["summary"],
        action_items=generated["action_items"],
        blog_draft=generated["blog_draft"],
        image_path=image_path,
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            return self.html(INDEX_HTML)
        if path == "/api/notes":
            return self.json([asdict(note) for note in read_notes()])
        if path.startswith("/captures/"):
            return self.file(CAPTURE_DIR / path.removeprefix("/captures/"))
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/captures":
            return self.create_capture()
        if path == "/api/search":
            data = self.read_json()
            return self.json(search_notes(str(data.get("query", "")), int(data.get("top_k", 5))))
        if path == "/api/blog":
            data = self.read_json()
            notes = read_notes()
            note_ids = data.get("note_ids")
            if note_ids:
                wanted = set(note_ids)
                notes = [note for note in notes if note.id in wanted]
            notes = notes[-8:]
            draft = llm.synthesize_blog(notes, str(data.get("topic", "오늘의 학습 기록")), str(data.get("format_type", "study-blog")))
            return self.json({"draft": draft})
        self.send_error(404)

    def create_capture(self) -> None:
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        raw_text = get_field(form, "raw_text")
        memo = get_field(form, "memo")
        image_path = None
        image = form["image"] if "image" in form else None
        if image is not None and getattr(image, "filename", ""):
            ext = Path(image.filename).suffix.lower() or ".png"
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
            target = CAPTURE_DIR / filename
            target.write_bytes(image.file.read())
            image_path = f"/captures/{filename}"
        start = time.perf_counter()
        note = make_note(raw_text, memo, image_path)
        append_note(note)
        elapsed = round(time.perf_counter() - start, 2)
        return self.json({"note": asdict(note), "elapsed_seconds": elapsed})

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def json(self, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            return self.send_error(404)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {fmt % args}")


def get_field(form: cgi.FieldStorage, key: str) -> str:
    if key not in form:
        return ""
    value = form[key]
    if isinstance(value, list):
        value = value[0]
    return str(value.value or "")


INDEX_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Study Documentation Agent</title>
  <style>
    :root { color-scheme: dark; --bg:#0b0f17; --panel:#141a24; --line:#273142; --text:#eef3f8; --muted:#9aa7b8; --brand:#53c7ad; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { max-width:1180px; margin:0 auto; padding:32px 24px 48px; }
    h1 { margin:0; font-size:32px; }
    h2 { margin:0 0 14px; font-size:18px; }
    p { margin:6px 0 0; color:var(--muted); }
    .grid { display:grid; grid-template-columns:1.2fr .8fr; gap:18px; margin-top:24px; align-items:start; }
    .panel { border:1px solid var(--line); background:var(--panel); border-radius:10px; padding:18px; }
    textarea, input { width:100%; border:1px solid var(--line); background:#0e141d; color:var(--text); border-radius:8px; padding:12px; font:inherit; }
    textarea { min-height:130px; resize:vertical; }
    button { border:1px solid #345044; background:var(--brand); color:#06110e; border-radius:8px; padding:12px 16px; font-weight:700; cursor:pointer; }
    button.secondary { background:#111926; border-color:#2b3a4f; color:var(--text); }
    button:disabled { opacity:.55; cursor:wait; }
    .row { display:flex; gap:10px; flex-wrap:wrap; }
    .stack { display:grid; gap:12px; }
    .result { white-space:pre-wrap; border:1px solid var(--line); background:#0e141d; border-radius:8px; padding:16px; min-height:180px; }
    .note { border:1px solid var(--line); border-radius:8px; padding:12px; margin-top:10px; background:#101722; }
    .note strong { display:block; margin-bottom:4px; }
    .note img { width:100%; max-height:160px; object-fit:cover; border:1px solid var(--line); border-radius:6px; margin-top:8px; }
    .meta { color:var(--muted); font-size:13px; }
    .badge { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:3px 8px; margin:3px 4px 0 0; color:#c8d3df; font-size:12px; }
    @media (max-width:900px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
<main>
  <h1>AI Study Documentation Agent</h1>
  <p>학습 화면, 실습 메모, 오류 상황을 구조화된 기술 노트와 문제 해결형 포트폴리오 글로 정리합니다.</p>

  <div class="grid">
    <section class="panel stack">
      <h2>학습 캡처 기록</h2>
      <input id="image" type="file" accept="image/*" />
      <textarea id="rawText" placeholder="화면에서 본 핵심 텍스트, 코드, 오류 메시지를 붙여넣으세요."></textarea>
      <textarea id="memo" placeholder="내가 이해한 내용, 막힌 부분, 해결한 방법을 메모하세요."></textarea>
      <div class="row">
        <button id="saveBtn">노트 생성</button>
        <button class="secondary" id="blogBtn">최근 노트로 블로그 초안</button>
        <button class="secondary" id="portfolioBtn">문제 해결형 Medium 글</button>
      </div>
      <div id="result" class="result">아직 생성된 결과가 없습니다.</div>
    </section>

    <aside class="panel">
      <h2>저장된 노트 검색</h2>
      <div class="row">
        <input id="query" placeholder="예: DAX, SQL, 오류, 모델링" />
        <button class="secondary" id="searchBtn">검색</button>
      </div>
      <div id="notes"></div>
    </aside>
  </div>
</main>

<script>
const result = document.querySelector("#result");
const notesBox = document.querySelector("#notes");

function show(text) { result.textContent = text; }

async function loadNotes() {
  try {
    const res = await fetch("/api/notes");
    const notes = await res.json();
    renderNotes(visibleNotes(notes).slice(-6).reverse());
  } catch (err) {
    notesBox.innerHTML = "<p>저장된 노트를 불러오지 못했습니다.</p>";
  }
}

function visibleNotes(notes) {
  return notes.filter(n => {
    const hasContent = Boolean((n.raw_text || "").trim() || (n.user_memo || "").trim() || n.image_path);
    const emptyFallback = String(n.summary || "").includes("입력된 텍스트가 없습니다");
    const imageOnlyPlaceholder = n.source_type === "study-capture-image" && (
      String(n.summary || "").includes("스크린샷을 학습 근거 자료로 저장했습니다")
      || String(n.summary || "").includes("스크린샷을 학습 캡처로 저장했습니다")
    );
    if (emptyFallback && n.source_type !== "study-capture-image") return false;
    if (imageOnlyPlaceholder) return false;
    return hasContent || !emptyFallback;
  });
}

function displayTitle(n) {
  const generic = ["학습 캡처 기록", "이미지 기반 학습 캡처", "이미지 학습 캡처"];
  if (!generic.includes(n.title)) return n.title;
  const time = String(n.created_at || "").split("T")[1]?.slice(0, 5) || "";
  return `${n.image_path ? "이미지" : "학습"} 캡처${time ? " " + time : ""}`;
}

function displaySummary(n) {
  return String(n.summary || "")
    .replace(
      "현재 MVP는 이미지 파일을 근거 자료로 보관하지만, 화면 속 텍스트를 자동으로 읽는 OCR/비전 기능은 아직 연결되어 있지 않습니다. 정확한 노트 생성을 위해 화면의 핵심 문장, 오류 메시지, 실습 목표를 텍스트 입력칸이나 메모에 함께 적어 주세요.",
      "이미지를 학습 근거 자료로 저장했습니다. 화면의 핵심 문장, 오류 메시지, 실습 목표를 메모하면 노트와 문제 해결형 포트폴리오 초안을 더 정확하게 구성할 수 있습니다."
    );
}

function renderNotes(notes) {
  notesBox.innerHTML = notes.map(n => `
    <div class="note">
      <strong>${escapeHtml(displayTitle(n))}</strong>
      <div class="meta">${escapeHtml(n.created_at)} · ${escapeHtml(n.source_type)}</div>
      <div>${(n.tags || []).map(t => `<span class="badge">${escapeHtml(t)}</span>`).join("")}</div>
      ${n.image_path ? `<img src="${escapeHtml(n.image_path)}" alt="captured study screenshot" />` : ""}
      <p>${escapeHtml(displaySummary(n).slice(0, 180))}</p>
    </div>`).join("");
}

document.querySelector("#saveBtn").onclick = async () => {
  const btn = document.querySelector("#saveBtn");
  btn.disabled = true;
  show("노트를 생성하는 중입니다...");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const form = new FormData();
    const file = document.querySelector("#image").files[0];
    if (file) form.append("image", file);
    form.append("raw_text", document.querySelector("#rawText").value);
    form.append("memo", document.querySelector("#memo").value);
    const res = await fetch("/api/captures", { method:"POST", body:form, signal:controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    show(`[응답 시간: ${data.elapsed_seconds}s]\\n\\n${data.note.summary}\\n\\n--- Blog Draft ---\\n${data.note.blog_draft}`);
    await loadNotes();
  } catch (err) {
    show("노트 생성 요청이 완료되지 않았습니다. LLM API 응답이 늦거나 일시적으로 실패했을 수 있어요. 입력 내용을 조금 줄이거나 잠시 뒤 다시 시도해 주세요.");
  } finally {
    clearTimeout(timeout);
    btn.disabled = false;
  }
};

document.querySelector("#searchBtn").onclick = async () => {
  const res = await fetch("/api/search", {
    method:"POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ query: document.querySelector("#query").value, top_k: 6 })
  });
  const rows = await res.json();
  renderNotes(visibleNotes(rows.map(r => r.note)));
};

async function makeBlog(formatType) {
  show("블로그 초안을 생성하는 중입니다...");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const res = await fetch("/api/blog", {
      method:"POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ topic:"학습 기록 기반 문제 해결 경험", format_type: formatType }),
      signal: controller.signal
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    show(data.draft);
  } catch (err) {
    show("블로그 초안 생성 요청이 완료되지 않았습니다. 노트가 너무 길거나 LLM API 응답이 늦을 수 있어요.");
  } finally {
    clearTimeout(timeout);
  }
}

document.querySelector("#blogBtn").onclick = () => makeBlog("study-blog");
document.querySelector("#portfolioBtn").onclick = () => makeBlog("problem-solving-portfolio");

function escapeHtml(text) {
  return String(text || "").replace(/[&<>"']/g, ch => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" }[ch]));
}

loadNotes();
</script>
</body>
</html>
"""


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "7870"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"AI Study Documentation Agent running on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
