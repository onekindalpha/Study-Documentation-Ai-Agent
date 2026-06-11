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
    image_paths: list[str] | None = None


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
        self.client = Groq(api_key=GROQ_API_KEY, timeout=90.0)
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
        except Exception as exc:
            print(f"[LLM text error] {exc}")
            return fallback_note(raw_text, memo)

    def generate_note_from_image(self, image_file: Path, memo: str) -> dict[str, Any]:
        return self.generate_note_from_images([image_file], memo)

    def generate_note_from_images(self, image_files: list[Path], memo: str) -> dict[str, Any]:
        client = self.get_client()
        if not client:
            return image_only_note(f"/captures/{image_files[0].name}" if image_files else "")

        if len(image_files) > 6:
            partial_notes: list[dict[str, Any]] = []
            for chunk_index, start in enumerate(range(0, len(image_files), 6), start=1):
                chunk = image_files[start : start + 6]
                chunk_memo = f"{memo}\n\n이 묶음은 전체 캡처 중 {chunk_index}번째 묶음입니다."
                partial_note = self.generate_note_from_images(chunk, chunk_memo)
                partial_notes.append(partial_note)
            return self.combine_image_notes(partial_notes, memo, len(image_files))

        for candidate_files in (image_files, image_files[:3], image_files[:1]):
            if not candidate_files:
                continue
            note = self.try_generate_note_from_images(client, candidate_files, memo)
            if note:
                return note
        return image_only_note(f"/captures/{image_files[0].name}" if image_files else "")

    def combine_image_notes(self, partial_notes: list[dict[str, Any]], memo: str, image_count: int) -> dict[str, Any]:
        joined = "\n\n".join(
            f"[묶음 {index}]\n제목: {note.get('title', '')}\n요약:\n{note.get('summary', '')}\n액션:\n{', '.join(note.get('action_items', []))}"
            for index, note in enumerate(partial_notes, start=1)
        )
        client = self.get_client()
        if client:
            prompt = f"""
아래는 사용자가 학습/Lab 실습 중 순서대로 캡처한 {image_count}장 이미지를 6장 이하 묶음으로 나누어 판독한 결과입니다.
묶음별 내용을 하나의 흐름으로 통합해 학습 노트 JSON을 작성해 주세요.

규칙:
- 한국어로 작성합니다.
- 입력된 묶음 요약과 사용자 메모만 근거로 사용합니다.
- JSON만 반환합니다.
- keys: title, source_type, tags, summary, action_items, blog_draft
- summary는 전체 실습 흐름을 압축하지 말고, 이미지 묶음별로 문제/원인/조치/검증 흐름을 길게 정리합니다.
- blog_draft는 Medium 포트폴리오 초안처럼 배경/문제 인식/문제 정의/해결 흐름/성과/배운 점 구조로 충분히 길게 작성합니다.

[사용자 메모]
{memo}

[묶음별 판독 결과]
{joined}
""".strip()
            try:
                completion = client.chat.completions.create(
                    model=GROQ_MODEL,
                    temperature=0.2,
                    max_tokens=3200,
                    messages=[
                        {"role": "system", "content": "You merge sequential study-capture notes into one grounded structured JSON note."},
                        {"role": "user", "content": prompt},
                    ],
                )
                return parse_json_or_fallback(completion.choices[0].message.content or "", joined, memo)
            except Exception as exc:
                print(f"[LLM merge error] {exc}")
        return {
            "title": f"{image_count}장 캡처 기반 학습 기록",
            "source_type": "study-capture",
            "tags": ["study-note", "multi-image", "vision"],
            "summary": joined,
            "action_items": ["묶음별 핵심 흐름 연결", "문제 인식과 해결 과정 보강", "문제 해결형 Medium 글로 확장"],
            "blog_draft": f"# {image_count}장 캡처 기반 학습 기록\n\n{joined}",
        }

    def try_generate_note_from_images(self, client: Any, image_files: list[Path], memo: str) -> dict[str, Any] | None:
        prompt = f"""
아래 이미지는 사용자가 학습/Lab 실습 중 순서대로 캡처한 화면입니다. 이미지 순서를 실습 흐름으로 보고 포트폴리오용 학습 노트로 정리해 주세요.

규칙:
- 한국어로 작성합니다.
- 화면에 보이는 내용과 사용자 메모만 근거로 사용합니다.
- JSON만 반환합니다.
- keys: title, source_type, tags, summary, action_items, blog_draft
- 여러 이미지가 있으면 이미지 1, 이미지 2... 순서대로 실습 흐름을 연결합니다.
- summary에는 각 이미지에서 확인한 화면 변화, 발견한 문제, 의심 원인, 조치, 검증 포인트를 생략하지 말고 정리합니다.
- blog_draft는 문제 해결형 기술블로그 초안처럼 제목/배경/문제 인식/문제 정의/해결 흐름/성과/배운 점 구조로 충분히 길게 작성합니다.
- 이미지가 여러 장이면 이미지별 캡션 후보를 함께 정리합니다.

[사용자 메모]
{memo}
""".strip()
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for index, image_file in enumerate(image_files, start=1):
            mime_type = mimetypes.guess_type(image_file.name)[0] or "image/png"
            image_data = base64.b64encode(image_file.read_bytes()).decode("ascii")
            content_parts.append({"type": "text", "text": f"이미지 {index}"})
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                }
            )
        try:
            completion = client.chat.completions.create(
                model=GROQ_VISION_MODEL,
                temperature=0.2,
                max_tokens=2400,
                messages=[
                    {
                        "role": "system",
                        "content": "You read study screenshots and turn them into structured developer learning notes. Return strict JSON.",
                    },
                    {
                        "role": "user",
                        "content": content_parts,
                    },
                ],
            )
            content = completion.choices[0].message.content or ""
            return parse_json_or_fallback(content, "", memo)
        except Exception as exc:
            print(f"[LLM vision error] {exc}")
            return None

    def synthesize_blog(self, notes: list[StudyNote], topic: str, format_type: str, extra_info: str = "") -> str:
        notes = [note for note in notes if is_meaningful_note(note)][-8:]
        if not notes:
            return "문제해결형 Medium 글을 만들 수 있는 학습 노트가 아직 없습니다. 스크린샷을 업로드하거나 메모를 입력한 뒤 먼저 캡처 노트를 생성해 주세요."

        joined = "\n\n".join(
            f"[노트 {index}]\n제목: {note.title}\n요약:\n{note.summary[:5200]}\n액션: {', '.join(note.action_items[:8])}\n초안:\n{note.blog_draft[:3600]}"
            for index, note in enumerate(notes, start=1)
        )
        client = self.get_client()
        if not client:
            return local_portfolio_blog(notes, topic)

        prompt = portfolio_prompt(topic, joined, extra_info)
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=0.25,
                max_tokens=7800,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a Korean technical portfolio writer. "
                            "Write long, concrete, grounded Medium-ready problem-solving articles from study notes."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            return completion.choices[0].message.content or local_portfolio_blog(notes, topic)
        except Exception:
            return local_portfolio_blog(notes, topic)

    def synthesize_blog_from_capture(
        self,
        raw_text: str,
        memo: str,
        image_files: list[Path],
        topic: str,
        extra_info: str = "",
    ) -> str:
        client = self.get_client()
        if not client:
            pseudo_note = StudyNote(
                id=str(uuid.uuid4()),
                created_at=datetime.now().isoformat(timespec="seconds"),
                title=topic or "학습 기록 기반 문제 해결 경험",
                source_type="direct-capture",
                tags=["medium", "portfolio"],
                raw_text=raw_text,
                user_memo=memo,
                summary="\n\n".join(part for part in [raw_text, memo, extra_info] if part.strip()),
                action_items=[],
                blog_draft="",
            )
            return local_portfolio_blog([pseudo_note], topic or pseudo_note.title)

        source_text = direct_source_text(raw_text, memo, len(image_files))

        if image_files and len(image_files) <= 6:
            prompt = portfolio_prompt(topic, source_text, extra_info)
            content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for index, image_file in enumerate(image_files, start=1):
                mime_type = mimetypes.guess_type(image_file.name)[0] or "image/png"
                image_data = base64.b64encode(image_file.read_bytes()).decode("ascii")
                content_parts.append({"type": "text", "text": f"이미지 {index}"})
                content_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}})
            try:
                completion = client.chat.completions.create(
                    model=GROQ_VISION_MODEL,
                    temperature=0.25,
                    max_tokens=7800,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a Korean technical portfolio writer. "
                                "Write long, concrete, Medium-ready problem-solving articles from screenshots and notes."
                            ),
                        },
                        {"role": "user", "content": content_parts},
                    ],
                )
                return completion.choices[0].message.content or ""
            except Exception as exc:
                print(f"[LLM direct vision blog error] {exc}")

        visual_notes = ""
        if image_files:
            visual_notes = self.describe_image_sequence(image_files, memo, extra_info)
        joined = "\n\n".join(part for part in [source_text, visual_notes] if part.strip())
        prompt = portfolio_prompt(topic, joined, extra_info)
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                temperature=0.25,
                max_tokens=7800,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a Korean technical portfolio writer. "
                            "Write long, concrete, grounded Medium-ready problem-solving articles."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            print(f"[LLM direct text blog error] {exc}")
            pseudo_note = StudyNote(
                id=str(uuid.uuid4()),
                created_at=datetime.now().isoformat(timespec="seconds"),
                title=topic or "학습 기록 기반 문제 해결 경험",
                source_type="direct-capture",
                tags=["medium", "portfolio"],
                raw_text=raw_text,
                user_memo=memo,
                summary=joined,
                action_items=[],
                blog_draft="",
            )
            return local_portfolio_blog([pseudo_note], topic or pseudo_note.title)

    def describe_image_sequence(self, image_files: list[Path], memo: str, extra_info: str) -> str:
        client = self.get_client()
        if not client:
            return ""
        chunks: list[str] = []
        for chunk_index, start in enumerate(range(0, len(image_files), 6), start=1):
            chunk = image_files[start : start + 6]
            prompt = f"""
아래 이미지는 사용자가 실습/프로젝트를 진행한 순서대로 캡처한 화면 중 {chunk_index}번째 묶음입니다.
최종 Medium 글을 쓰기 위한 근거 메모를 작성해 주세요.

규칙:
- 최종 글을 쓰지 말고, 이미지별 관찰 내용과 문제 해결 흐름만 자세히 정리합니다.
- 버튼 클릭 설명이 아니라 문제/원인/조치/검증 관점으로 해석합니다.
- 화면에서 확인되는 기술명, 테이블명, 수식명, 오류, 결과값을 가능한 한 보존합니다.
- 사용자가 제공한 추가 정보와 모순되지 않게 작성합니다.
- 이미지 번호는 전체 순서를 기준으로 {start + 1}번부터 시작합니다.

[사용자 메모]
{memo}

[추가 정보]
{extra_info}
""".strip()
            content_parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for offset, image_file in enumerate(chunk, start=start + 1):
                mime_type = mimetypes.guess_type(image_file.name)[0] or "image/png"
                image_data = base64.b64encode(image_file.read_bytes()).decode("ascii")
                content_parts.append({"type": "text", "text": f"이미지 {offset}"})
                content_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}})
            try:
                completion = client.chat.completions.create(
                    model=GROQ_VISION_MODEL,
                    temperature=0.2,
                    max_tokens=3200,
                    messages=[
                        {"role": "system", "content": "You read technical screenshots and create detailed grounded writing notes."},
                        {"role": "user", "content": content_parts},
                    ],
                )
                chunks.append(completion.choices[0].message.content or "")
            except Exception as exc:
                print(f"[LLM direct image sequence error] {exc}")
        return "\n\n".join(f"[이미지 판독 묶음 {index}]\n{chunk}" for index, chunk in enumerate(chunks, start=1))


llm = LLM()


def direct_source_text(raw_text: str, memo: str, image_count: int) -> str:
    sections = []
    if raw_text.strip():
        sections.append(f"[화면 텍스트/코드/오류]\n{raw_text.strip()}")
    if memo.strip():
        sections.append(f"[사용자 메모/질문/해결 과정]\n{memo.strip()}")
    if image_count:
        sections.append(
            "[이미지 정보]\n"
            f"사용자가 실습 진행 순서대로 업로드한 이미지 수: {image_count}장\n"
            "이미지 자체는 최종 글에서 단순 캡션이 아니라 문제 발견, 원인 분석, 해결 과정, 검증 결과의 근거로 사용해야 합니다."
        )
    sections.append(
        "[작성 주의]\n"
        "비어 있는 입력칸, 내부 라벨, '직접 입력된 화면 텍스트 없음', '직접 입력된 사용자 메모 없음' 같은 시스템 상태 문구는 최종 글에 절대 쓰지 않습니다."
    )
    return "\n\n".join(sections)


def parse_json_or_fallback(content: str, raw_text: str, memo: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return fallback_note(raw_text, memo)
    if isinstance(data, list):
        summary = stringify_field(data)
        return {
            "title": "이미지 기반 학습 기록",
            "source_type": "study-capture",
            "tags": ["study-note", "vision"],
            "summary": summary,
            "action_items": ["핵심 개념 정리", "막힌 지점과 해결 방법 추가 기록", "문제 해결형 글로 변환"],
            "blog_draft": f"# 이미지 기반 학습 기록\n\n## 캡처 내용\n{summary}\n\n## 다음 정리\n- 문제 인식\n- 해결 과정\n- 배운 점\n",
        }
    if not isinstance(data, dict):
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
        "tags": ["study-note", "screenshot", "vision-fallback"],
        "summary": (
            "스크린샷을 학습 근거 자료로 저장했지만, Vision LLM 응답을 받아오지 못해 기본 노트로 기록했습니다.\n\n"
            "화면에서 확인한 핵심 문장, 오류 메시지, 실습 목표를 메모에 함께 적으면 "
            "이미지 판독이 실패해도 노트와 문제 해결형 포트폴리오 초안을 구성할 수 있습니다.\n\n"
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
            "스크린샷이 저장되었습니다. Vision LLM 응답을 받아오지 못한 경우에는 "
            "실습 목표와 문제 상황을 메모로 함께 기록하면 문제 해결형 포트폴리오 글로 확장할 수 있습니다.\n\n"
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


def portfolio_prompt(topic: str, joined_notes: str, extra_info: str = "") -> str:
    return f"""
당신은 사용자의 실습/프로젝트 기록을 Medium 포트폴리오 글로 변환하는 전용 작성자입니다.
아래 실습/프로젝트 기록을 바탕으로 Medium에 그대로 붙여넣을 수 있는 완성본을 작성해 주세요.

글의 목적은 단순 후기나 요약이 아니라, 사용자가 이미 Medium에 작성해 온 것과 같은 **문제해결형 포트폴리오 글**입니다.
반드시 아래 작성 방식을 그대로 따르세요.

가장 중요한 원칙:
- 이미지를 1장씩 따로 해설하지 않습니다.
- 이미지별로 각각 문제/원인을 만들지 않습니다.
- 전체 이미지 묶음을 하나의 실습 흐름으로 보고, 하나의 핵심 문제를 중심으로 글을 씁니다.
- 초반 이미지는 문제 인식, 중간 이미지는 원인 분석과 해결 과정, 마지막 이미지는 검증 결과로 사용합니다.
- "무엇을 클릭했다"보다 "어떤 문제가 있었고, 왜 문제가 되었고, 어떤 원인을 발견했고, 어떻게 해결했고, 결과가 어떻게 바뀌었는지"를 중심으로 씁니다.
- 사용자가 직접 문제를 발견하고 해결한 경험처럼 작성합니다.
- 취업 포트폴리오에 사용할 수 있도록 실무적인 분석 문체로 씁니다.
- 짧은 요약문이 아니라 Medium에 그대로 게시 가능한 완성형 글로 작성합니다.
- 사용자가 직접 입력한 추가 정보는 최상위 작성 브리프입니다. 이미지 판독 결과보다 우선합니다.
- 추가 정보에 "이미지 흐름 요약", "이 글에서 강조할 문제 해결 관점", "강조하고 싶은 기술"이 있으면 그 내용을 글의 뼈대로 사용합니다.
- 추가 정보가 비어 있으면 이미지/메모/노트만으로 작성하되, 없는 내용을 지어내지 않습니다.
- 내부 라벨인 [화면 텍스트/코드/오류], [사용자 메모/질문/해결 과정], [이미지 정보], [작성 주의]는 최종 글에 절대 출력하지 않습니다.

분량 규칙:
- 전체 글은 최소 4,500자 이상으로 작성합니다. 가능하면 6,000~8,000자 수준의 Medium 완성본으로 작성합니다.
- "문제 인식", "문제 정의", "왜 문제로 인식했는가"는 각각 충분히 길게 작성합니다.
- "문제 해결 경험"이 가장 중요합니다. 최소 4개 이상의 단계로 나누고, 각 단계는 `문제/제약 → 원인 판단 → 조치 → 확인 결과` 흐름으로 작성합니다.
- 문제 해결 경험 섹션은 글 전체에서 가장 긴 섹션이어야 합니다.
- 수식, 코드, 관계 설정, 오류 해결, 배포, 새로고침, 모델링, 데이터 검증처럼 복잡한 내용이 있으면 별도 섹션으로 충분히 설명합니다.
- 마지막 Portfolio Summary는 영어로 2문단 이상 작성합니다.
- Key skills practiced는 최소 8개 이상 작성합니다.

1. 한국어 제목
2. 영어 부제
3. 짧은 도입부
4. 핵심 작업 요약
5. 문제 인식
6. 문제 정의
7. 왜 이것을 문제로 인식했는가
8. 문제 해결 경험 1, 2, 3...
9. 복잡한 수식 작성 및 해결 경험
10. 성과
11. 사용한 주요 수식/코드 정리
12. 최종 정리
13. Portfolio Summary
14. Key skills practiced
15. 이미지 번호와 캡션 목록

문체 규칙:
- 다음처럼 쓰지 않습니다: "버튼을 눌렀습니다", "차트를 만들었습니다", "관계를 설정했습니다", "실습을 완료했습니다".
- 대신 다음처럼 씁니다: "처음에는 값이 정상적으로 보이는 것처럼 보였지만...", "문제의 원인은 시각화가 아니라 필터 컨텍스트가 팩트 테이블까지 전달되지 않는 semantic model 구조에 있었다", "이를 해결하기 위해 차원 테이블과 팩트 테이블 사이의 관계를 재정의했다".
- "했습니다" 반복을 줄이고 분석/정의/구성/해결/검증 중심으로 작성합니다.

이미지 규칙:
- 사용자가 제공한 이미지는 단순 캡처가 아니라 문제 해결 과정의 증거로 사용합니다.
- 입력에 이미지 설명이 있으면 사용자가 제공한 이미지 순서대로 번호를 붙입니다.
- 본문에는 "이미지 1 - 제목" 형식의 캡션만 넣습니다.
- "첨부 삽입", "여기에 이미지 넣기" 같은 placeholder 문구는 절대 넣지 않습니다.
- 마지막에 이미지 번호와 캡션 목록을 따로 정리합니다.
- 초반 이미지는 문제 발견, 이상 현상, 초기 상태, 실습 시작점으로 묶어 해석합니다.
- 중간 이미지는 원인 분석, 관계 설정, 수식 작성, 데이터 변환, 모델 수정, UI 구성, 오류 해결, 검증 과정으로 묶어 해석합니다.
- 마지막 이미지는 최종 결과, 개선된 화면, 검증 결과, 성과 화면으로 묶어 해석합니다.
- 이미지 하나하나마다 문제 정의를 반복하지 않습니다.
- 이미지 캡션은 글의 흐름을 보조하는 장치일 뿐이며, 글의 중심은 사용자가 해결한 핵심 문제와 해결 과정입니다.
- 이미지 자체에 명확한 문제가 없으면 억지로 문제를 만들지 말고, "실습에서 해결해야 할 과제"를 문제로 정의합니다.

코드/수식 규칙:
- DAX, SQL, Python, Power Query, API 코드가 있으면 코드블록으로 정리합니다.
- 수식은 단순히 나열하지 말고, 각 수식이 어떤 문제를 해결했는지 설명합니다.
- 복잡한 수식은 원인 → 중간 검증 → 최종 수식 흐름으로 설명합니다.
- 수식은 반드시 다음 흐름으로 설명합니다: 어떤 문제가 있었는가 → 왜 이 수식이 필요했는가 → 수식이 어떤 계산을 수행하는가 → 결과를 어떻게 검증했는가.
- 수식이나 코드가 이미지에 보이지 않거나 사용자가 제공하지 않았다면 임의로 만들지 않습니다.

오류/막힌 부분 처리 규칙:
- 사용자가 오류, 막힌 부분, 헷갈린 부분을 제공하면 반드시 글에 반영합니다.
- 오류는 실패가 아니라 문제 해결 경험으로 재구성합니다.
- 각 오류는 `증상 → 처음 의심한 원인 → 실제 원인 → 해결 방법 → 확인 결과` 흐름으로 작성합니다.

Power BI semantic model 실습일 때의 작성 방식:
- 현재 입력이 Power BI, Sales, Product, Category, DAX, relationship, semantic model, filter context를 다루는 경우에만 아래 패턴을 적용합니다.
- 다른 이미지 세트가 들어오면 이 Power BI 예시 내용을 재사용하지 말고, 해당 이미지의 실제 기술 주제에 맞춰 같은 문제 해결형 구조만 유지합니다.
- 첫 이미지는 기능 설명이 아니라 문제 인식 장면으로 해석합니다. 화면에 숫자가 나오는 것이 아니라, 왜 숫자가 이상한지 먼저 씁니다.
- 예를 들어 Category별 Sales가 모두 같은 값으로 반복된다면, "Power BI에서 숫자는 보이지만 의미가 틀릴 수 있다"는 문제로 시작합니다.
- 원인은 시각화 문제가 아니라 semantic model 문제로 정의합니다. Product[Category] 필터가 Sales로 전달되지 않아 ProductKey 관계가 필요하다는 식으로 원인 중심으로 씁니다.
- 이미지는 작업 순서가 아니라 아래 해결 단계로 묶습니다.
  - 이미지 1: 문제 발견, Category별 Sales 반복
  - 이미지 2~4: Product-Sales 관계 생성과 star schema 구조 정리
  - 이미지 5~6: Product hierarchy 구성
  - 이미지 7~10: Profit, Profit Margin measure 생성과 검증
  - 이미지 11~14: SalespersonRegion bridge table, many-to-many, filter direction, inactive relationship 문제 해결
  - 이미지 15: Salesperson별 Sales와 Target 비교 최종 결과
- 관계 설정은 "무엇을 선택했는가"만 쓰지 말고 왜 맞는지 설명합니다. Product는 차원 테이블, Sales는 팩트 테이블이므로 Product[ProductKey] → Sales[ProductKey], Cardinality One-to-many, Cross-filter direction Single, Active relationship이 왜 필요한지 씁니다.
- DAX는 "왜 필요한가 → 어떤 수식인가 → 어떤 결과를 검증했는가" 순서로 설명합니다. Sales만으로는 수익성을 볼 수 없어서 Profit이 필요하고, 규모가 다른 카테고리를 비교하려면 Profit Margin이 필요하다는 식으로 씁니다.
- many-to-many 관계는 복잡한 문제 해결 경험으로 따로 뽑습니다. Salesperson별 Sales를 담당 Region 기준으로 보려면 Salesperson → SalespersonRegion → Region → Sales 흐름이 필요하고, 모호한 필터 경로가 생기면 직접 관계를 비활성화해야 한다는 식으로 씁니다.
- 마지막은 "실습 완료"가 아니라 분석 가능성의 변화로 정리합니다. Category별 Sales 반복 문제 해결, Product-Sales 관계 생성, 계층 구조 구성, Measure 생성, bridge table 기반 many-to-many 해결, Salesperson별 Sales와 Target 비교 가능성을 성과로 씁니다.
- 결론은 "숫자가 화면에 보인다고 항상 맞는 것은 아니며, relationship, cardinality, filter direction, active relationship이 잘못되면 visual은 정상처럼 보여도 의미는 틀릴 수 있다"는 식으로 마무리합니다.

Medium 작성 방식 예시:
- 첫 문단은 "이번 실습에서 무엇을 했는가"보다 "처음 무엇이 이상했는가"로 시작합니다.
- 그 다음 문제를 한 문장으로 정의합니다.
- 이후 왜 그 문제가 중요한지 데이터 모델, 비즈니스 해석, 검증 관점에서 설명합니다.
- 문제 해결 경험은 다음 순서로 이어갑니다.
  1. 문제 화면에서 이상 징후를 발견한 과정
  2. 원인을 시각화가 아니라 데이터 모델/관계/수식/쿼리 구조에서 찾은 과정
  3. 관계, 수식, 쿼리, 설정, 데이터 구조를 수정한 과정
  4. 수정 후 결과가 어떻게 달라졌는지 검증한 과정
  5. 추가로 복잡했던 관계, 수식, 필터 컨텍스트, 오류 해결 과정을 별도 섹션으로 정리
- 이미지 캡션은 각 섹션 사이에 짧게 넣되, 본문은 캡션 설명이 아니라 문제해결 서사로 작성합니다.

[주제]
{topic}

[사용자가 직접 입력한 추가 정보]
{extra_info if extra_info.strip() else "추가 정보 없음. 이미지/메모/노트만 근거로 작성하세요."}

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


def make_note(raw_text: str, memo: str, image_path: str | None, image_paths: list[str] | None = None) -> StudyNote:
    image_paths = image_paths or ([image_path] if image_path else [])
    image_files = [CAPTURE_DIR / path.removeprefix("/captures/") for path in image_paths]
    if image_files and not raw_text.strip():
        generated = llm.generate_note_from_images(image_files, memo)
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
        image_paths=image_paths or None,
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
            draft = llm.synthesize_blog(
                notes,
                str(data.get("topic", "오늘의 학습 기록")),
                str(data.get("format_type", "study-blog")),
                str(data.get("extra_info", "")),
            )
            return self.json({"draft": draft})
        if path == "/api/direct-blog":
            return self.create_direct_blog()
        self.send_error(404)

    def create_capture(self) -> None:
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        raw_text = get_field(form, "raw_text")
        memo = get_field(form, "memo")
        image_paths: list[str] = []
        image = form["image"] if "image" in form else None
        images = image if isinstance(image, list) else ([image] if image is not None else [])
        for index, item in enumerate(images, start=1):
            if item is not None and getattr(item, "filename", ""):
                ext = Path(item.filename).suffix.lower() or ".png"
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{index:02d}_{uuid.uuid4().hex[:8]}{ext}"
                target = CAPTURE_DIR / filename
                target.write_bytes(item.file.read())
                image_paths.append(f"/captures/{filename}")
        image_path = image_paths[0] if image_paths else None
        start = time.perf_counter()
        note = make_note(raw_text, memo, image_path, image_paths)
        append_note(note)
        elapsed = round(time.perf_counter() - start, 2)
        return self.json({"note": asdict(note), "elapsed_seconds": elapsed})

    def create_direct_blog(self) -> None:
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        raw_text = get_field(form, "raw_text")
        memo = get_field(form, "memo")
        topic = get_field(form, "topic") or "학습 기록 기반 문제 해결 경험"
        extra_info = get_field(form, "extra_info")
        image_files: list[Path] = []
        image = form["image"] if "image" in form else None
        images = image if isinstance(image, list) else ([image] if image is not None else [])
        for index, item in enumerate(images, start=1):
            if item is not None and getattr(item, "filename", ""):
                ext = Path(item.filename).suffix.lower() or ".png"
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{index:02d}_{uuid.uuid4().hex[:8]}{ext}"
                target = CAPTURE_DIR / filename
                target.write_bytes(item.file.read())
                image_files.append(target)
        start = time.perf_counter()
        draft = llm.synthesize_blog_from_capture(raw_text, memo, image_files, topic, extra_info)
        elapsed = round(time.perf_counter() - start, 2)
        return self.json({"draft": draft, "elapsed_seconds": elapsed, "image_count": len(image_files)})

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
    .compact textarea { min-height:68px; }
    .optional-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .optional-grid .wide { grid-column:1 / -1; }
    .section-label { font-weight:700; color:#c8d3df; margin-top:4px; }
    button { border:1px solid #345044; background:var(--brand); color:#06110e; border-radius:8px; padding:12px 16px; font-weight:700; cursor:pointer; }
    button.secondary { background:#111926; border-color:#2b3a4f; color:var(--text); }
    button:disabled { opacity:.55; cursor:wait; }
    .dropzone { border:1px dashed #3a4a61; background:#0e141d; border-radius:10px; padding:16px; cursor:pointer; transition:border-color .15s, background .15s; }
    .dropzone:hover, .dropzone.dragover { border-color:var(--brand); background:#101b24; }
    .dropzone strong { display:block; margin-bottom:4px; }
    .dropzone span { color:var(--muted); font-size:13px; }
    .dropzone input { display:none; }
    .file-list { color:#c8d3df; font-size:13px; margin-top:8px; }
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
  <p>학습 화면, 실습 메모, 오류 상황을 문제 해결형 Medium 포트폴리오 글로 바로 변환합니다.</p>

  <div class="grid">
    <section class="panel stack">
      <h2>문제 해결형 Medium 글 생성</h2>
      <label id="dropzone" class="dropzone" for="image">
        <strong>이미지 끌어놓기 또는 파일 선택</strong>
        <span>실습 순서대로 여러 장을 한 번에 넣거나, 나중에 이미지를 추가할 수 있습니다.</span>
        <input id="image" type="file" accept="image/*" multiple />
        <div id="fileList" class="file-list">선택된 이미지 없음</div>
      </label>
      <textarea id="rawText" placeholder="화면에서 본 핵심 텍스트, 코드, 오류 메시지를 붙여넣으세요."></textarea>
      <textarea id="memo" placeholder="내가 이해한 내용, 막힌 부분, 해결한 방법을 메모하세요."></textarea>
      <div class="section-label">Medium 글 추가 정보 <span class="meta">(선택 입력)</span></div>
      <div class="optional-grid compact">
        <textarea id="projectName" placeholder="실습/프로젝트 이름"></textarea>
        <textarea id="coreProblem" placeholder="내가 해결한 핵심 문제"></textarea>
        <textarea id="blockedPart" placeholder="중간에 막힌 부분"></textarea>
        <textarea id="finalResult" placeholder="최종 결과"></textarea>
        <textarea class="wide" id="focusTech" placeholder="강조하고 싶은 기술, 수식, 코드, 설정"></textarea>
      </div>
      <div class="row">
        <button class="secondary" id="clearFilesBtn">이미지 선택 초기화</button>
        <button id="portfolioBtn">문제 해결형 Medium 완성본 생성</button>
      </div>
      <div id="result" class="result">아직 생성된 결과가 없습니다.</div>
    </section>

    <aside class="panel">
      <h2>이전 기록 검색</h2>
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
const fileInput = document.querySelector("#image");
const dropzone = document.querySelector("#dropzone");
const fileList = document.querySelector("#fileList");
let selectedFiles = [];
let currentNoteIds = [];

function show(text) { result.textContent = text; }

function fileKey(file) {
  return `${file.name}-${file.size}-${file.lastModified}`;
}

function addSelectedFiles(files) {
  const current = new Map(selectedFiles.map(file => [fileKey(file), file]));
  Array.from(files || [])
    .filter(file => file.type.startsWith("image/"))
    .forEach(file => current.set(fileKey(file), file));
  selectedFiles = Array.from(current.values());
  fileList.textContent = selectedFiles.length
    ? selectedFiles.map((file, index) => `${index + 1}. ${file.name}`).join(" · ")
    : "선택된 이미지 없음";
}

function clearSelectedFiles() {
  selectedFiles = [];
  fileInput.value = "";
  fileList.textContent = "선택된 이미지 없음";
}

fileInput.onchange = () => {
  addSelectedFiles(fileInput.files);
  fileInput.value = "";
};
document.querySelector("#clearFilesBtn").onclick = clearSelectedFiles;

function handleDragOver(event) {
  event.preventDefault();
  dropzone.classList.add("dragover");
}

function handleDragLeave() {
  dropzone.classList.remove("dragover");
}

function handleDrop(event) {
  event.preventDefault();
  dropzone.classList.remove("dragover");
  addSelectedFiles(event.dataTransfer.files);
}

dropzone.ondragover = handleDragOver;
dropzone.ondragleave = handleDragLeave;
dropzone.ondrop = handleDrop;
document.ondragover = handleDragOver;
document.ondrop = handleDrop;

async function loadNotes() {
  try {
    const res = await fetch("/api/notes");
    const notes = await res.json();
    if (!currentNoteIds.length) {
      notesBox.innerHTML = "<p>이번 세션에서 생성한 노트가 아직 없습니다. 검색창을 사용하면 이전 저장 기록을 찾아볼 수 있습니다.</p>";
      return;
    }
    const currentNotes = notes.filter(note => currentNoteIds.includes(note.id));
    renderNotes(currentNotes.reverse());
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
      ${(n.image_paths || []).length > 1 ? `<div class="meta">캡처 ${(n.image_paths || []).length}장 연결</div>` : ""}
      <p>${escapeHtml(displaySummary(n).slice(0, 180))}</p>
    </div>`).join("");
}

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
  if (!selectedFiles.length && !document.querySelector("#rawText").value.trim() && !document.querySelector("#memo").value.trim()) {
    show("이미지, 화면 텍스트, 메모 중 하나는 입력해 주세요.");
    return;
  }
  const btn = document.querySelector("#portfolioBtn");
  const extraInfo = [
    ["실습/프로젝트 이름", document.querySelector("#projectName").value],
    ["내가 해결한 핵심 문제", document.querySelector("#coreProblem").value],
    ["중간에 막힌 부분", document.querySelector("#blockedPart").value],
    ["최종 결과", document.querySelector("#finalResult").value],
    ["강조하고 싶은 기술", document.querySelector("#focusTech").value]
  ]
    .filter(([, value]) => String(value || "").trim())
    .map(([label, value]) => `- ${label}: ${String(value).trim()}`)
    .join("\\n");
  const topic = document.querySelector("#projectName").value.trim() || "학습 기록 기반 문제 해결 경험";
  btn.disabled = true;
  show("문제 해결형 Medium 완성본을 생성하는 중입니다. 이미지 판독과 긴 글 생성이 함께 진행되어 시간이 걸릴 수 있습니다...");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 300000);
  try {
    const form = new FormData();
    selectedFiles.forEach(file => form.append("image", file));
    form.append("raw_text", document.querySelector("#rawText").value);
    form.append("memo", document.querySelector("#memo").value);
    form.append("topic", topic);
    form.append("format_type", formatType);
    form.append("extra_info", extraInfo);
    const res = await fetch("/api/direct-blog", {
      method:"POST",
      body: form,
      signal: controller.signal
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    show(`[응답 시간: ${data.elapsed_seconds}s · 이미지 ${data.image_count}장]\\n\\n${data.draft}`);
  } catch (err) {
    show("문제 해결형 Medium 글 생성 요청이 완료되지 않았습니다. 이미지가 많거나 LLM API 응답이 늦을 수 있어요. 추가 정보 칸에 이미지 흐름 요약을 넣고 다시 시도해 주세요.");
  } finally {
    clearTimeout(timeout);
    btn.disabled = false;
  }
}

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
