from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "main.py"

spec = importlib.util.spec_from_file_location("study_capture_main", MAIN)
main = importlib.util.module_from_spec(spec)
sys.modules["study_capture_main"] = main
assert spec.loader is not None
spec.loader.exec_module(main)


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed" + (f": {detail}" if detail else ""))


def terms(title: str, body: str) -> list[str]:
    return main.youtube_learning_terms(title, body, limit=10)


def run() -> None:
    vector_terms = terms(
        "Vector Databases: Embeddings, Semantic Search, and Hybrid Retrieval - Alexey Grigorev",
        "we cover embeddings vector database semantic search hybrid retrieval git github repository rest agent",
    )
    check("vector terms include embeddings", "임베딩" in vector_terms, str(vector_terms))
    check("vector terms avoid stale git", "Git" not in vector_terms and "GitHub" not in vector_terms, str(vector_terms))
    check("vector terms avoid stale REST", "REST" not in vector_terms, str(vector_terms))

    llm_terms = terms(
        "LLM Zoomcamp 2026 Course Launch - Alexey Grigorev",
        "free 10 week course about AI engineering RAG agents evaluation monitoring GitHub repo",
    )
    check("llm terms focus ai engineering", "AI Engineering" in llm_terms or "RAG" in llm_terms, str(llm_terms))
    check("llm terms avoid git overpromotion", "Git" not in llm_terms and "GitHub" not in llm_terms, str(llm_terms))

    cleaned = main.clean_prompt_memo("[생성 직전 사용자가 정의한 어려운 문제]")
    check("placeholder removed", cleaned == "", cleaned)
    cleaned_dot = main.clean_prompt_memo("[생성 직전 사용자가 정의한 어려운 문제]\n.")
    check("placeholder dot residue removed", cleaned_dot == "", cleaned_dot)
    dsa_problem = main.youtube_core_problem_from_profile(
        "얄코의 자료구조 & 알고리즘 무료공개 파트",
        ["시간 복잡도", "공간 복잡도"],
        ".",
        "시간 복잡도 공간 복잡도 빅오 배열 인덱스 탐색",
    )
    check("dot user problem falls back to topic problem", dsa_problem != "." and "자료구조" in dsa_problem, dsa_problem)

    bad_sections = main.youtube_chapter_sections(
        "Um so right now I'm just recording the content for the course. But the first thing I want to do is prepare the environment. We will use embeddings and vector databases for semantic search and hybrid retrieval.",
        title="Vector Databases: Embeddings, Semantic Search, and Hybrid Retrieval",
    )
    titles = [s.get("title", "") for s in bad_sections]
    check("no transcript fragment section title", not any("But the first thing" in t or "Um so" in t for t in titles), str(titles))

    report = main.collection_failure_report(
        "https://youtube.com/playlist?list=PL_TEST",
        "run_test",
        {},
        ["Could not extract YouTube video id"],
    )
    check("failure report hides run_id", "run_test" not in report and "SOURCE_GRAPH" not in report, report)
    check("playlist guidance", "플레이리스트" in report and "개별 영상 URL" in report, report)

    print("OK: source generation regression smoke checks passed")


if __name__ == "__main__":
    run()
