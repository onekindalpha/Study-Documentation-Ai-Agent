from pathlib import Path

p = Path("app/main.py")
text = p.read_text(encoding="utf-8")
backup = p.with_suffix(".py.before_foundry_longform_v4")
backup.write_text(text, encoding="utf-8")

if "Foundry IQ knowledge base를 agent 지식 계층으로 분리" in text:
    print("Already patched.")
    raise SystemExit(0)

start_marker = '    lines.append("## Key skills practiced")'
start = text.find(start_marker)
if start == -1:
    raise SystemExit("ERROR: Key skills section marker not found")

return_marker = '    return "\\n".join(lines)'
ret = text.find(return_marker, start)
if ret == -1:
    raise SystemExit("ERROR: return join marker not found after Key skills section")

replacement = r'''    article_body = "\n".join(lines)

    if "is_foundry_iq_mcp_article" in locals() and is_foundry_iq_mcp_article:
        stronger_problem = (
            "기업용 AI agent를 단순 챗봇이 아니라 실무 workflow에 연결하려면, "
            "내부 지식을 신뢰할 수 있게 검색하는 knowledge grounding 계층과 "
            "외부 tool/API를 안전하게 실행하는 tool execution 계층을 분리해 설계해야 하는 것이 핵심 문제였다."
        )

        article_body = article_body.replace(
            "- 핵심 문제: Foundry IQ가 RAG 기반 지식 연결을 담당하고, MCP가 외부 도구 호출을 확장하는 구조를 구분해 이해하는 것이 핵심 문제였다.",
            f"- 핵심 문제: {stronger_problem}",
        )

        article_body = article_body.replace(
            "처음 헷갈린 지점은 Foundry IQ가 RAG 기반 지식 연결을 담당하고, MCP가 외부 도구 호출을 확장하는 구조를 구분해 이해하는 것이 핵심 문제였다.\\n"
            "핵심은 용어를 나열하는 것이 아니라, 그 개념이 어떤 업무 흐름에서 쓰이고 왜 중요한지 설명하는 것이었다.",
            "처음 헷갈린 지점은 Foundry IQ와 MCP를 단순히 새로운 Microsoft AI 기능으로 나열하는 것이 아니라, enterprise AI agent 설계에서 각각 어떤 문제를 해결하는 계층인지 구분하는 것이었다. 기업용 agent는 단순히 질문에 답하는 챗봇으로 끝나지 않는다. 최신 내부 문서에 접근해야 하고, 답변의 근거를 남겨야 하며, 필요한 경우 외부 API나 업무 시스템까지 호출해야 한다.\\n\\n"
            "따라서 이 학습의 핵심은 Foundry IQ와 MCP를 기능 이름으로 외우는 것이 아니라, 하나의 실무형 agent workflow 안에서 역할을 분리하는 데 있었다. Foundry IQ는 RAG 기반 knowledge grounding 문제를 해결하는 계층으로, MCP는 외부 tool/API 실행을 확장하고 통제하는 계층으로 볼 수 있었다. 이 차이를 이해해야 agent가 왜 knowledge base, citation, fallback, approval mode 같은 운영 기준을 함께 가져야 하는지 설명할 수 있다.",
        )

        article_body = article_body.replace(
            "Foundry IQ가 RAG 기반 지식 연결을 담당하고, MCP가 외부 도구 호출을 확장하는 구조를 구분해 이해하는 것이 핵심 문제였다.\\n\\n"
            "이 문제는 개념 정의만 외우는 것으로 해결되지 않는다. 핵심 개념을 업무 흐름, 조치, 확인 기준과 연결해야 한다.",
            stronger_problem + "\\n\\n"
            "이 문제는 개념 정의만 외우는 것으로 해결되지 않는다. Foundry IQ, RAG, knowledge base, Azure AI Search, MCP server/client, dynamic tool discovery, approval mode를 각각 따로 이해하는 것만으로는 부족하다. 중요한 것은 이 요소들이 왜 함께 필요한지, 그리고 어떤 순서로 agent workflow 안에 배치되는지 설명하는 것이다.\\n\\n"
            "특히 Lab instruction에는 MCP server/client 구성, Foundry IQ knowledge base 연결, agent 실행 흐름이 함께 포함되어 있었다. 그래서 이 글에서는 강의를 요약하는 데서 끝내지 않고, 지식 검색 계층과 도구 실행 계층을 분리해 설계하는 문제로 재정의했다.",
        )

        extra_experiences = """
### 5. Foundry IQ knowledge base를 agent 지식 계층으로 분리
문제/제약: 기업용 agent가 정확한 답변을 하려면 모델의 사전학습 지식만으로는 부족하다. 제품 문서, 정책 문서, 내부 매뉴얼처럼 계속 바뀌는 자료를 반영하지 못하면 답변은 그럴듯해 보여도 실제 업무에서는 신뢰하기 어렵다.

원인/핵심 쟁점: 이 문제의 핵심은 모델 성능보다 knowledge base 구성에 있었다. Foundry IQ는 SharePoint, Azure Blob Storage, OneLake, Azure AI Search 같은 데이터 소스를 연결해 여러 agent가 공유할 수 있는 지식 기반을 구성하는 방향으로 이해할 수 있다.

조치: Foundry IQ를 단순 검색 기능이 아니라 agent가 업무 문서를 근거로 답변하기 위한 knowledge grounding 계층으로 정리했다. 이 과정에서 knowledge base는 단순 파일 저장소가 아니라, 검색·색인·랭킹·인용 품질을 결정하는 agent 운영 기반으로 보았다.

확인 기준: agent가 내부 문서를 검색하고, 답변에 citation을 붙이며, 근거가 부족할 때 fallback할 수 있는 구조로 설명할 수 있다면 Foundry IQ의 역할을 제대로 이해한 것으로 볼 수 있다.

### 6. Retrieval instruction, citation, fallback 기준 정리
문제/제약: knowledge base를 연결했다고 해서 agent가 항상 좋은 답변을 하는 것은 아니다. 언제 검색해야 하는지, 어떤 형식으로 근거를 제시해야 하는지, 문서에 답이 없을 때 어떻게 행동해야 하는지가 정해져 있지 않으면 응답 품질이 흔들릴 수 있다.

원인/핵심 쟁점: RAG 기반 agent의 품질은 검색 자체뿐 아니라 instruction 설계에 영향을 받는다. retrieval instruction이 모호하면 agent가 문서를 충분히 검색하지 않거나, citation 없이 일반적인 답변을 생성할 수 있다.

조치: agent instructions를 “항상 knowledge base를 확인할지”, “citation을 어떤 방식으로 표시할지”, “답을 찾지 못한 경우 어떤 fallback 문장을 사용할지”를 통제하는 운영 규칙으로 정리했다.

확인 기준: 단순히 knowledge base가 연결되었다는 사실이 아니라, 답변 근거와 fallback 기준까지 설명할 수 있어야 실무형 agent 설계로 볼 수 있다.

### 7. MCP server/client를 tool execution 계층으로 분리
문제/제약: Foundry IQ가 지식 검색을 담당한다면, agent가 외부 API, database, internal service를 호출하는 문제는 별도의 계층으로 다루어야 한다. 지식 검색과 도구 실행을 같은 문제로 보면 agent 구조가 흐려진다.

원인/핵심 쟁점: MCP는 agent가 사용할 수 있는 tool을 서버에서 노출하고, client가 이를 발견해 agent에 연결하는 구조다. 즉 MCP의 핵심은 tool을 하드코딩하지 않고 runtime에 discovery하고 호출할 수 있게 만드는 데 있다.

조치: MCP server/client 구조를 tool execution 계층으로 분리했다. MCP server는 tool catalog를 제공하고, MCP client는 tool 목록을 조회한 뒤 agent가 호출할 수 있는 wrapper 또는 tool object로 연결하는 흐름으로 이해했다.

확인 기준: Foundry IQ는 “무엇을 근거로 답할 것인가”의 문제이고, MCP는 “어떤 외부 기능을 안전하게 실행할 것인가”의 문제라고 설명할 수 있다면 두 계층을 구분한 것이다.

### 8. FastMCP, server.py, client.py, agent.py 역할 연결
문제/제약: Lab instruction에 등장하는 파일들이 단순 실습 파일처럼 보일 수 있지만, 실제로는 MCP 기반 agent 구조를 나누어 이해하는 단서가 된다. 파일 이름만 나열하면 포트폴리오 글의 문제 해결 흐름이 약해진다.

원인/핵심 쟁점: server.py, client.py, agent.py는 각각 tool 정의, tool discovery, agent 연결이라는 역할을 가진다. 이 역할을 분리하지 않으면 MCP 실습이 단순 코드 실행으로만 보이고, agent architecture 관점의 의미가 드러나지 않는다.

조치: FastMCP는 Python 함수와 docstring을 바탕으로 tool catalog를 구성하는 도구로, server.py는 tool을 노출하는 MCP server 역할로, client.py는 tool 목록을 조회하고 호출 가능한 형태로 연결하는 역할로, agent.py는 agent workflow에 MCP tool을 통합하는 역할로 정리했다.

확인 기준: Lab 파일을 “실습에 사용한 코드”가 아니라 agent 구조를 분리해 이해하는 증거로 설명할 수 있으면, 단순 학습 요약보다 문제해결형 포트폴리오 글에 가까워진다.

### 9. approval mode와 governance 기준 연결
문제/제약: agent가 외부 tool을 호출할 수 있게 되면 편리하지만, 동시에 보안과 통제 문제가 생긴다. 특히 외부 API나 내부 시스템을 호출하는 agent는 잘못된 tool invocation이 실제 업무 영향으로 이어질 수 있다.

원인/핵심 쟁점: MCP와 Foundry agent 흐름에서는 tool 실행을 단순 자동화로만 보면 안 된다. approval mode, per-run headers, 인증 정보, 허용된 tool 범위 같은 governance 기준이 함께 필요하다.

조치: approval mode를 agent가 외부 tool을 호출할 때 사람의 승인을 요구하거나, 특정 조건에서는 자동 실행하도록 통제하는 장치로 정리했다. 또한 per-run headers는 실행 단위의 인증·권한 정보를 전달하는 방식으로 이해했다.

확인 기준: agent가 tool을 사용할 수 있다는 사실보다, 어떤 tool을 언제 승인하고 어떤 인증 기준으로 실행할지 설명할 수 있어야 enterprise workflow에 적용 가능한 설계로 볼 수 있다.
"""

        complex_section = """
## 복잡한 문제 해결 경험
이번 학습에서 가장 복잡한 지점은 Foundry IQ와 MCP를 하나의 기능 묶음으로 이해하지 않고, 서로 다른 문제를 해결하는 두 계층으로 분리하는 것이었다. Foundry IQ는 agent가 신뢰할 수 있는 내부 지식을 검색하고 citation을 남기는 문제를 다룬다. 반면 MCP는 agent가 외부 tool/API를 동적으로 발견하고 호출하는 문제를 다룬다.

이 구분이 중요한 이유는 enterprise AI agent가 단순히 “답변을 잘 생성하는 모델”로 끝나지 않기 때문이다. 실제 업무에서는 최신 문서 반영, 검색 정확도, citation, fallback, tool execution, approval, authentication이 함께 작동해야 한다. 따라서 이 학습은 개념을 외우는 과정이 아니라, agent architecture를 knowledge grounding과 tool execution으로 분리해 설계 기준을 세우는 문제 해결 경험으로 볼 수 있다.
"""

        if "### 5. Foundry IQ knowledge base를 agent 지식 계층으로 분리" not in article_body:
            article_body = article_body.replace("\\n## 성과\\n", "\\n" + extra_experiences + "\\n" + complex_section + "\\n## 성과\\n")

        article_body = article_body.replace(
            "## Key skills practiced\\n"
            "- Understanding Foundry IQ and RAG concepts\\n"
            "- Mapping knowledge bases to enterprise agent workflows\\n"
            "- Separating knowledge grounding from MCP tool execution\\n"
            "- Reading AI Skills Navigator source packs\\n"
            "- Documenting AI agent architecture for developer portfolios",
            "## Key skills practiced\\n"
            "- Understanding Foundry IQ and RAG concepts\\n"
            "- Mapping knowledge bases to enterprise agent workflows\\n"
            "- Separating knowledge grounding from MCP tool execution\\n"
            "- Interpreting knowledge base design as an agent architecture problem\\n"
            "- Connecting Azure AI Search, embeddings, ranking, and citations\\n"
            "- Understanding MCP server/client tool discovery\\n"
            "- Mapping FastMCP, server.py, client.py, and agent.py roles\\n"
            "- Explaining approval mode and governance for agent tool execution\\n"
            "- Reading AI Skills Navigator source packs\\n"
            "- Documenting AI agent architecture for developer portfolios",
        )

        if "## 이미지 번호와 캡션 목록" not in article_body:
            article_body += (
                "\\n\\n## 이미지 번호와 캡션 목록\\n"
                "- 이미지 없음: 이번 글은 강의 URL, source pack, 영상 후보 URL, Lab instruction을 기반으로 작성했다."
            )

    return article_body'''

text = text[:ret] + replacement + text[ret + len(return_marker):]

p.write_text(text, encoding="utf-8")
print("OK patched:", p)
print("Backup:", backup)
