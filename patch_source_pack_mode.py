from __future__ import annotations

from pathlib import Path

path = Path('app/main.py')
text = path.read_text(encoding='utf-8')
orig = text

foundry_steps = '''
    if kind == "foundry_iq":
        return [
            {
                "title": "단일 챗봇 한계에서 지식 기반 Agent 문제로 재정의",
                "problem": "처음에는 AI agent가 답변을 생성하는 구조만 이해했지만, 기업 업무에서는 최신 문서와 내부 지식을 근거로 답해야 한다는 점이 핵심 제약이었다.",
                "action": "Foundry IQ를 RAG 기반 knowledge platform으로 보고, SharePoint, Azure Blob Storage, OneLake, Azure AI Search 같은 데이터 소스를 knowledge base로 연결하는 흐름을 정리했다.",
                "verification": "agent가 학습 데이터만으로 답하는 것이 아니라, knowledge base를 검색하고 citation과 fallback 규칙을 통해 검증 가능한 답변을 만드는 구조로 설명할 수 있게 되었다.",
            },
            {
                "title": "Foundry IQ와 RAG의 역할 구분",
                "problem": "RAG는 개념으로 이해했지만, Foundry IQ가 그 개념을 실제 서비스 구조에서 어떤 부분까지 대신해 주는지 모호했다.",
                "action": "RAG를 검색-증강-생성 흐름으로, Foundry IQ를 indexing, embeddings, ranking, citation을 중앙화하는 managed knowledge platform으로 분리해 이해했다.",
                "verification": "개별 agent마다 RAG 파이프라인을 새로 만드는 대신, 공유 knowledge base를 만들고 여러 agent가 재사용하는 구조를 설명할 수 있게 되었다.",
            },
            {
                "title": "MCP를 도구 확장 계층으로 연결",
                "problem": "Foundry IQ가 지식을 연결한다면, MCP는 agent가 외부 tool/API를 어떻게 호출하게 하는지 구분이 필요했다.",
                "action": "MCP server/client 구조, dynamic tool discovery, approval mode, per-run headers를 agent가 외부 도구를 안전하게 호출하는 연결 방식으로 정리했다.",
                "verification": "Foundry IQ는 knowledge grounding을, MCP는 tool execution 확장을 담당한다는 차이를 설명할 수 있게 되었다.",
            },
            {
                "title": "실무 적용 기준 정리",
                "problem": "강의 내용이 Foundry IQ, RAG, MCP, governance로 넓게 퍼져 있어 포트폴리오 글의 중심을 잡기 어려웠다.",
                "action": "문서 기반 support/HR assistant는 Foundry IQ와 RAG로, API/DB/internal service 호출은 MCP tool로 연결하는 식으로 사용 기준을 나누었다.",
                "verification": "AI agent 설계를 단순 챗봇이 아니라 지식 검색, 도구 호출, 보안 승인, fallback 정책이 결합된 enterprise workflow로 정리할 수 있게 되었다.",
            },
        ]
'''
needle = '    return []\n\ndef build_url_assisted_medium_draft('
if 'if kind == "foundry_iq"' not in text:
    text = text.replace(needle, foundry_steps + '    return []\n\ndef build_url_assisted_medium_draft(')

# Add foundry_iq detection inside build_url_assisted_medium_draft
old = '''    source = f"{raw_text}\\n{memo}"
    azure = is_azure_devops_mcp_context(raw_text, memo)
    agent_orch = is_agent_orchestration_context(raw_text, memo) and not azure
    github = is_github_agentic_context(raw_text, memo) and not azure and not agent_orch
'''
new = '''    source = f"{raw_text}\\n{memo}"
    source_lower = source.lower()
    foundry_iq = any(
        term in source_lower
        for term in [
            "foundry iq",
            "microsoft iq overview",
            "work iq",
            "fabric iq",
            "retrieval augmented generation",
            "knowledge-enhanced ai agents",
            "azure ai search",
            "knowledge base",
            "model context protocol",
            "dynamic tool discovery",
        ]
    )
    azure = is_azure_devops_mcp_context(raw_text, memo) and "azure devops" in source_lower
    agent_orch = is_agent_orchestration_context(raw_text, memo) and not azure and not foundry_iq
    github = is_github_agentic_context(raw_text, memo) and not azure and not agent_orch and not foundry_iq
'''
if old in text:
    text = text.replace(old, new)
elif 'foundry_iq = any(' not in text:
    raise SystemExit('Could not patch source/foundry detection block. app/main.py structure differs.')

old = '''    elif github:
        if not steps or sum(not is_weak_learning_step(step) for step in steps[:4]) < 2:
            steps = practical_problem_steps_for_topic("github_agentic")

    if not section_plan and steps:
'''
new = '''    elif github:
        if not steps or sum(not is_weak_learning_step(step) for step in steps[:4]) < 2:
            steps = practical_problem_steps_for_topic("github_agentic")
    elif foundry_iq:
        # Source Pack mode: do not let stale Power BI/general fallback steps leak in.
        steps = practical_problem_steps_for_topic("foundry_iq")

    if not section_plan and steps:
'''
if old in text:
    text = text.replace(old, new)
elif 'practical_problem_steps_for_topic("foundry_iq")' not in text:
    raise SystemExit('Could not patch steps override block. app/main.py structure differs.')

old = '''    elif github:
        title = "GitHub Agentic Workflows 실습: workflow_dispatch와 자동화 실행 흐름 이해하기"
        subtitle = "Understanding workflow_dispatch, pull requests, and result verification"
        core_problem = "GitHub Agentic Workflows에서 workflow_dispatch, workflow 파일, activation, Pull Request, conclusion이 자동화 실행 흐름 안에서 어떤 의미를 갖는지 이해하는 것이 핵심 문제였다."
        key_terms = ["GitHub Agentic Workflows", "GitHub Actions", "workflow_dispatch", "Pull Request", "activation", "conclusion"]
        final_result = "GitHub Agentic Workflows에서 workflow_dispatch, workflow 파일, activation, Pull Request, conclusion이 자동화 실행 조건과 결과 검증 흐름으로 어떻게 연결되는지 정리했다."
        skills = [
            "Understanding GitHub agentic workflow concepts",
            "Reading workflow_dispatch triggers",
            "Connecting workflow files with pull request review",
            "Separating confirmed evidence from assumptions",
            "Documenting GitHub automation learning for developer portfolios",
        ]
    else:
'''
new = '''    elif github:
        title = "GitHub Agentic Workflows 실습: workflow_dispatch와 자동화 실행 흐름 이해하기"
        subtitle = "Understanding workflow_dispatch, pull requests, and result verification"
        core_problem = "GitHub Agentic Workflows에서 workflow_dispatch, workflow 파일, activation, Pull Request, conclusion이 자동화 실행 흐름 안에서 어떤 의미를 갖는지 이해하는 것이 핵심 문제였다."
        key_terms = ["GitHub Agentic Workflows", "GitHub Actions", "workflow_dispatch", "Pull Request", "activation", "conclusion"]
        final_result = "GitHub Agentic Workflows에서 workflow_dispatch, workflow 파일, activation, Pull Request, conclusion이 자동화 실행 조건과 결과 검증 흐름으로 어떻게 연결되는지 정리했다."
        skills = [
            "Understanding GitHub agentic workflow concepts",
            "Reading workflow_dispatch triggers",
            "Connecting workflow files with pull request review",
            "Separating confirmed evidence from assumptions",
            "Documenting GitHub automation learning for developer portfolios",
        ]
    elif foundry_iq:
        title = "Foundry IQ와 MCP 학습: 지식 기반 AI Agent Workflow 이해하기"
        subtitle = "Understanding RAG, knowledge bases, and MCP tool integration for enterprise AI agents"
        core_problem = "Foundry IQ가 RAG 기반 지식 연결을 담당하고, MCP가 외부 도구 호출을 확장하는 구조를 구분해 이해하는 것이 핵심 문제였다."
        key_terms = [
            "Microsoft IQ",
            "Foundry IQ",
            "Retrieval Augmented Generation",
            "knowledge base",
            "Azure AI Search",
            "MCP server/client",
            "dynamic tool discovery",
            "approval mode",
            "agent instructions",
            "citations and fallback",
        ]
        final_result = "Foundry IQ를 knowledge grounding 계층으로, MCP를 tool execution 확장 계층으로 이해하고, enterprise AI agent가 지식 검색·도구 호출·보안 통제를 결합하는 흐름을 정리했다."
        skills = [
            "Understanding Foundry IQ and RAG concepts",
            "Mapping knowledge bases to enterprise agent workflows",
            "Separating knowledge grounding from MCP tool execution",
            "Reading AI Skills Navigator source packs",
            "Documenting AI agent architecture for developer portfolios",
        ]
    else:
'''
if old in text:
    text = text.replace(old, new)
elif 'elif foundry_iq:' not in text:
    raise SystemExit('Could not patch title/key terms block. app/main.py structure differs.')

# Replace generic intro branch with Foundry-specific intro
old = '''    elif github:
        lines.append("이번 학습은 GitHub Agentic Workflows에서 `workflow_dispatch`가 자동화 실행 조건으로 어떤 의미를 갖는지 이해하는 데서 출발했다. workflow 파일이 실행 조건을 정의하고, activation 이후 변경사항이 Pull Request 검토 흐름으로 이어질 수 있다는 점을 중심으로 GitHub 기반 자동화 구조를 살펴보았다.")
    else:
        lines.append("이번 학습은 강의 자료와 실습 단서에 남아 있는 핵심 개념과 작업 흐름을 이해하는 데서 출발했다. 자료에 남은 제목, 용어, 단계 정보를 바탕으로 학습 목표와 개념 간 관계를 정리했다.")
'''
new = '''    elif github:
        lines.append("이번 학습은 GitHub Agentic Workflows에서 `workflow_dispatch`가 자동화 실행 조건으로 어떤 의미를 갖는지 이해하는 데서 출발했다. workflow 파일이 실행 조건을 정의하고, activation 이후 변경사항이 Pull Request 검토 흐름으로 이어질 수 있다는 점을 중심으로 GitHub 기반 자동화 구조를 살펴보았다.")
    elif foundry_iq:
        lines.append("이번 학습은 Microsoft IQ 흐름 안에서 Foundry IQ, RAG, MCP가 각각 어떤 역할을 하는지 구분하는 데서 출발했다. Foundry IQ는 enterprise knowledge를 agent에 연결하는 지식 기반 계층으로, MCP는 agent가 외부 tool과 API를 안전하게 호출하도록 돕는 확장 계층으로 이해했다.")
    else:
        lines.append("이번 학습은 강의 자료와 실습 단서에 남아 있는 핵심 개념과 작업 흐름을 이해하는 데서 출발했다. 자료에 남은 제목, 용어, 단계 정보를 바탕으로 학습 목표와 개념 간 관계를 정리했다.")
'''
if old in text:
    text = text.replace(old, new)

if text == orig:
    raise SystemExit('No changes made. Patch did not match app/main.py')
path.write_text(text, encoding='utf-8')
print('patched app/main.py: source_pack Foundry IQ mode enabled')
