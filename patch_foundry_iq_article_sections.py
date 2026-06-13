from __future__ import annotations

from pathlib import Path

TARGET = Path("app/main.py")

FOUNDRY_DESCRIPTIONS_CODE = '''
    foundry_iq_descriptions = {
        "Microsoft IQ": "Microsoft의 AI agent 학습 흐름 안에서 Work IQ, Foundry IQ, Fabric IQ처럼 업무 지식·데이터·AI agent 활용을 연결해 이해하는 상위 개념이다.",
        "Foundry IQ": "여러 agent가 조직의 문서와 데이터를 공통으로 활용할 수 있도록 knowledge base를 구성하고 검색·인용·응답 근거를 제공하는 managed knowledge platform이다.",
        "Retrieval Augmented Generation": "모델이 학습 데이터만으로 답하는 한계를 줄이기 위해, 질문 시점에 관련 문서를 검색하고 그 내용을 prompt에 붙여 근거 기반 답변을 생성하는 방식이다.",
        "RAG": "Retrieval Augmented Generation의 약자로, agent가 최신 문서와 내부 지식을 검색해 답변 근거로 사용하는 구조다.",
        "knowledge base": "SharePoint, Azure Blob Storage, OneLake, Azure AI Search 같은 데이터 소스를 업무 도메인 기준으로 묶어 agent가 검색할 수 있게 만든 지식 저장 계층이다.",
        "Azure AI Search": "Foundry IQ의 검색·색인·랭킹 기반을 담당하는 검색 인프라로, chunking, embeddings, semantic ranking, citation 품질에 영향을 준다.",
        "MCP server/client": "MCP server는 agent가 호출할 수 있는 tool catalog를 제공하고, MCP client는 해당 tool을 발견·등록·호출할 수 있게 연결한다.",
        "MCP": "Model Context Protocol의 약자로, agent가 외부 tool/API를 동적으로 발견하고 호출할 수 있게 하는 연결 규격이다.",
        "dynamic tool discovery": "agent 코드에 API를 직접 박아 넣는 대신 실행 시점에 MCP server에서 사용 가능한 tool 목록을 가져와 호출하는 방식이다.",
        "approval mode": "agent가 외부 tool을 호출할 때 항상 승인하거나, 승인 없이 실행하거나, 사람이 개입해 통제할 수 있게 하는 governance 장치다.",
        "agent instructions": "agent가 언제 knowledge base를 검색해야 하는지, citation을 어떻게 달아야 하는지, 모르는 경우 어떻게 fallback해야 하는지를 정하는 운영 규칙이다.",
        "citations and fallback": "agent 답변이 어떤 문서에 근거하는지 표시하고, 근거가 부족할 때 무리하게 답하지 않도록 하는 신뢰성 장치다.",
        "FastMCP": "Python 함수와 docstring을 바탕으로 MCP server의 tool catalog를 빠르게 구성하는 실습 도구로 이해할 수 있다.",
        "server.py": "MCP server에서 tool 정의와 tool catalog 노출을 담당하는 실습 파일이다.",
        "client.py": "MCP server에 연결해 tool 목록을 조회하고 호출 wrapper를 만드는 실습 파일이다.",
        "agent.py": "Azure AI Agent 또는 Foundry agent에 MCP tool이나 knowledge base를 연결해 실행 흐름을 검증하는 실습 파일이다.",
    }
'''

FOUNDRY_FINAL_BLOCK = '''        if article_type == "foundry_iq_mcp_learning":
            lines.append("이번 학습을 통해 enterprise AI agent를 단순한 챗봇이 아니라, 지식 검색과 도구 실행이 결합된 workflow로 이해했다. Foundry IQ는 RAG 기반 knowledge grounding을 담당해 agent가 최신 문서와 내부 지식을 근거로 답변하게 만들고, MCP는 agent가 외부 API, database, internal service 같은 tool을 동적으로 발견하고 호출할 수 있게 한다.")
            lines.append("")
            lines.append("따라서 실무형 agent 설계에서는 어떤 모델을 쓰는가보다 어떤 knowledge base를 연결할 것인가, 어떤 tool을 MCP로 노출할 것인가, citation·fallback·approval을 어떻게 통제할 것인가가 중요하다는 점을 정리할 수 있었다.")
        else:
'''

FOUNDRY_PORTFOLIO_BLOCK = '''        if article_type == "foundry_iq_mcp_learning":
            lines.append("This learning record explains how Microsoft Foundry IQ and MCP extend AI agents beyond simple chatbot interactions. Foundry IQ supports RAG-based knowledge grounding through shared knowledge bases, while MCP enables dynamic tool discovery and controlled tool execution. The key takeaway is that enterprise AI agents require both reliable knowledge access and governed tool integration to support practical business workflows.")
        else:
'''


def main() -> None:
    if not TARGET.exists():
        raise SystemExit(f"ERROR: {TARGET} not found. Run this from project root.")

    text = TARGET.read_text(encoding="utf-8")
    backup = TARGET.with_suffix(".py.before_foundry_sections")
    backup.write_text(text, encoding="utf-8")

    needle = '        desc = concept_descriptions.get(term) or "핵심 개념을 업무 흐름 안에서 어떤 역할을 하는지 기준으로 이해했다."'
    if needle in text and "foundry_iq_descriptions" not in text:
        text = text.replace(
            needle,
            FOUNDRY_DESCRIPTIONS_CODE + "\n" +
            '        desc = concept_descriptions.get(term) or foundry_iq_descriptions.get(term) or "핵심 개념을 업무 흐름 안에서 어떤 역할을 하는지 기준으로 이해했다."',
            1,
        )
    elif "foundry_iq_descriptions" in text:
        print("foundry_iq_descriptions already present")
    else:
        print("WARN: concept description needle not found")

    generic_final = '        lines.append("이번 학습에서는 강의 자료와 실습 단서에 흩어진 개념을 하나의 학습 흐름으로 정리했다. 핵심 개념, 실습 단계, 확인이 필요한 부분을 분리하면서 이후 같은 내용을 다시 설명할 수 있는 기술 학습 기록으로 만들었다.")'
    if generic_final in text and "enterprise AI agent를 단순한 챗봇" not in text:
        text = text.replace(generic_final, FOUNDRY_FINAL_BLOCK + generic_final, 1)
    elif "enterprise AI agent를 단순한 챗봇" in text:
        print("Foundry final summary branch already present")
    else:
        print("WARN: generic final summary needle not found")

    generic_portfolio = '        lines.append("This learning record organizes a technical study topic into a clear learning goal, concept map, workflow summary, and optional follow-up checks.")'
    if generic_portfolio in text and "Foundry IQ supports RAG-based knowledge grounding" not in text:
        text = text.replace(generic_portfolio, FOUNDRY_PORTFOLIO_BLOCK + generic_portfolio, 1)
    elif "Foundry IQ supports RAG-based knowledge grounding" in text:
        print("Foundry portfolio branch already present")
    else:
        print("WARN: generic portfolio summary needle not found")

    TARGET.write_text(text, encoding="utf-8")
    print(f"OK: patched {TARGET}")
    print(f"Backup: {backup}")
    print("Next: python -m py_compile app/main.py")


if __name__ == "__main__":
    main()
