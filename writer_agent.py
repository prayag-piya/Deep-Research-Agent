import os
import json
import operator
from functools import lru_cache
import re
from datetime import datetime
from pathlib import Path
from typing import TypedDict, Annotated

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import START, END, StateGraph
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from langgraph.types import Send

from tools import read_file, tavily_search, root_dir
from configration import Configration
from schema import Topics, QualityCheck, FollowQuestion
from prompt import (
    topic_generator,
    summarizer,
    section_writer_prompt,
    quality_checker_prompt,
    follow_up_prompt,
    section_rewriter_prompt,
)

thread_id = "hsi"




class SectionState(TypedDict, total=False):
    """Per-section state used inside the section subgraph."""

    heading: str
    sources: str
    notes: str
    draft: str
    order: int
    section_content: str
    quality_passed: bool
    follow_up_context: str
    sections: Annotated[list, operator.add]


class State(TypedDict, total=False):
    """Main pipeline state."""

    topic: list
    requirements: str
    notes: str
    draft: str
    sources: str
    sections: Annotated[list, operator.add]
    final_report: str




@lru_cache(maxsize=None)
def get_llm(model: str = "llama3.2:latest", temperature: float = 0.7) -> ChatOllama:
    return ChatOllama(model=model, temperature=temperature)



def read_sources(state: State, config: RunnableConfig):
    """Read and summarize sources, notes, and draft from research files."""

    configurable = Configration.from_runnable_config(config)
    llm = get_llm(temperature=1)

    all_sources = read_file("sources", thread_id)
    all_notes = read_file("notes", thread_id)
    all_draft = read_file("draft", thread_id)

    all_sources = llm.invoke(
        [SystemMessage(content=summarizer), HumanMessage(content=f"{all_sources}")]
    )
    all_notes = llm.invoke(
        [SystemMessage(content=summarizer), HumanMessage(content=f"{all_notes}")]
    )
    all_draft = llm.invoke(
        [SystemMessage(content=summarizer), HumanMessage(content=f"{all_draft}")]
    )

    return {
        "sources": all_sources.content,
        "notes": all_notes.content,
        "draft": all_draft.content,
    }


def heading_generator(state: State, config: RunnableConfig):
    """Generate IEEE report topic headings from summarized research."""

    content = f"All Research Source: {state['sources']}\n\n"
    content += f"\n\n All Draft : {state['draft']}\n\n"
    content += f"\n\n All Notes : {state['notes']}\n\n"

    llm = get_llm(temperature=1)
    structured_llm = llm.with_structured_output(Topics)
    prompt = [SystemMessage(content=topic_generator), HumanMessage(content=content)]

    topic = structured_llm.invoke(prompt)
    print(f"[heading_generator] Generated {len(topic.report)} topics")
    return {"topic": [t.model_dump() for t in topic.report]}


def process_topic(state: State):
    """Fan-out: dispatch every topic to the section pipeline in parallel."""

    return [
        Send(
            "section_pipeline",
            {
                "heading": topic["topic"],
                "sources": state["sources"],
                "notes": state["notes"],
                "draft": state["draft"],
                "order": idx,
            },
        )
        for idx, topic in enumerate(state["topic"])
    ]


def _slugify(text: str) -> str:
    """Convert heading text to a markdown-safe anchor slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug


def _extract_subsections(content: str) -> list[tuple[str, str]]:
    """Pull out any ## or ### sub-headings from a section's content.

    Returns list of (heading_text, slug) pairs.
    """
    subs = []
    for m in re.finditer(r"^#{2,3}\s+(.+)$", content, re.MULTILINE):
        heading = m.group(1).strip()
        # strip any existing numbering like "1.1 " at the start
        heading_clean = re.sub(r"^\d+(\.\d+)*\.?\s*", "", heading)
        if heading_clean:
            subs.append((heading_clean, _slugify(heading_clean)))
    return subs


def _renumber_content(content: str, section_num: int) -> str:
    """Re-number subsection headings inside a section to IEEE style (2.1, 2.2 …).

    Also converts raw <cite source="id">…</cite> tags to IEEE [id] brackets.
    """
    sub_counter = 0

    def _sub_heading(m):
        nonlocal sub_counter
        sub_counter += 1
        title = m.group(2).strip()
        title_clean = re.sub(r"^\d+(\.\d+)*\.?\s*", "", title)
        return f"### {section_num}.{sub_counter}. {title_clean}"

    content = re.sub(r"^(#{2,3})\s+(.+)$", _sub_heading, content, flags=re.MULTILINE)

    # Convert <cite source="X">text</cite> → text [X]
    content = re.sub(
        r'<cite\s+source="([^"]+)">(.*?)</cite>',
        r"\2 [\1]",
        content,
    )

    return content


def collect_sections(state: State):
    """Collect all parallel section results, format with TOC + headings, and write to file."""

    sections = state.get("sections", [])
    sorted_sections = sorted(sections, key=lambda s: s.get("order", 0))

    today = datetime.now().strftime("%B %d, %Y")

    # ── 1. Renumber content & collect TOC entries ──
    toc_lines: list[str] = []
    formatted_bodies: list[str] = []
    all_refs: list[str] = []

    for idx, section in enumerate(sorted_sections, start=1):
        heading = section["heading"]
        slug = _slugify(heading)
        raw_content = section["content"]

        # Strip any leading H1/H2 the LLM may have put at the top of the section
        raw_content = re.sub(r"^#{1,2}\s+.*\n+", "", raw_content, count=1)

        renumbered = _renumber_content(raw_content, idx)

        # Collect sub-headings for TOC
        toc_lines.append(f"{idx}. [{heading}](#{slug})")
        for sub_title, sub_slug in _extract_subsections(renumbered):
            toc_lines.append(f"   - [{sub_title}](#{sub_slug})")

        # Build section block
        block = f"## {idx}. {heading}\n\n{renumbered}"
        formatted_bodies.append(block)

        # Harvest bracketed references like [1], [2] from content
        refs_in_section = re.findall(r"\[(\d+)\]", renumbered)
        for r in refs_in_section:
            ref_entry = f"[{r}]"
            if ref_entry not in all_refs:
                all_refs.append(ref_entry)

    # ── 2. Generate abstract via LLM ──
    llm = get_llm(temperature=0.3)
    section_summaries = "\n".join(
        f"- {s['heading']}: {s['content'][:300]}..." for s in sorted_sections
    )
    abstract_resp = llm.invoke([
        SystemMessage(
            content=(
                "Write a concise 150-250 word academic abstract summarizing the "
                "following report sections. Use formal IEEE academic tone. "
                "Return ONLY the abstract text, no headings or labels."
            )
        ),
        HumanMessage(content=section_summaries),
    ])
    abstract_text = abstract_resp.content.strip()

    # ── 3. Assemble the full document ──
    toc_block = "\n".join(toc_lines)
    sections_block = "\n\n---\n\n".join(formatted_bodies)

    # Build references block
    if all_refs:
        ref_lines = "\n".join(
            f"{ref} Source {ref.strip('[]')}" for ref in sorted(set(all_refs), key=lambda x: int(x.strip("[]")))
        )
    else:
        ref_lines = "*No references collected.*"

    final_report = f"""# Technical Report

> **Date:** {today}
> **Authors:** [Author Names]

---

## Abstract

{abstract_text}

---

## Table of Contents

{toc_block}

---

{sections_block}

---

## References

{ref_lines}
"""

    # ── 4. Write to file ──
    output_dir = Path(root_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"report_{thread_id}.md"
    output_path.write_text(final_report, encoding="utf-8")
    print(f"[collect_sections] Report ({len(sorted_sections)} sections) written to {output_path}")

    return {"final_report": final_report}


def generate_section(state: SectionState):
    """
    Generate a report section (500-2000 words) for the given heading.
    Uses summarized sources, notes, and draft as context.
    """

    llm = get_llm(temperature=0.7)

    context = f"## Research Sources Summary:\n{state['sources']}\n\n"
    context += f"## Research Notes Summary:\n{state['notes']}\n\n"
    context += f"## Draft Summary:\n{state['draft']}\n\n"

    prompt = [
        SystemMessage(content=section_writer_prompt),
        HumanMessage(
            content=(
                f"Write a comprehensive section for: **{state['heading']}**\n\n"
                f"Use the following research context:\n\n{context}\n\n"
                f"Requirements:\n"
                f"- Minimum 500 words, Maximum 2000 words\n"
                f"- IEEE academic style with proper citations\n"
                f"- Be thorough, analytical, and well-structured\n"
                f"- Include critical analysis, not just description"
            )
        ),
    ]

    response = llm.invoke(prompt)
    print(f"[generate_section] Wrote section: {state['heading']}")
    return {"section_content": response.content}


def check_quality(state: SectionState):
    """
    Evaluate the quality of a generated section.
    Returns pass/fail status, a score, and actionable feedback.
    """

    llm = get_llm(temperature=0.3)
    structured_llm = llm.with_structured_output(QualityCheck)

    prompt = [
        SystemMessage(content=quality_checker_prompt),
        HumanMessage(
            content=(
                f"## Section Title: {state['heading']}\n\n"
                f"## Section Content:\n{state['section_content']}\n\n"
                f"## Original Research Context (excerpt):\n"
                f"Sources: {state['sources'][:1000]}\n"
                f"Notes: {state['notes'][:1000]}\n\n"
                f"Evaluate the quality of this section."
            )
        ),
    ]

    result = structured_llm.invoke(prompt)
    print(
        f"[check_quality] '{state['heading']}': "
        f"passed={result.passed}, score={result.score}"
    )

    feedback_str = "\n".join(result.feedback) if not result.passed else ""
    return {"quality_passed": result.passed, "follow_up_context": feedback_str}


def quality_router(state: SectionState) -> str:
    """Route based on quality check: pass → finalize, fail → more research."""

    if state.get("quality_passed", False):
        return "pass"
    return "fail"


def followup_research(state: SectionState):
    """
    Generate follow-up search queries from quality feedback,
    execute web searches via Tavily, and collect results.
    """

    llm = get_llm(temperature=0.5)
    structured_llm = llm.with_structured_output(FollowQuestion)

    prompt = [
        SystemMessage(content=follow_up_prompt),
        HumanMessage(
            content=(
                f"Section Title: {state['heading']}\n\n"
                f"Current Section Content:\n{state['section_content']}\n\n"
                f"Quality Issues Identified:\n"
                f"{state.get('follow_up_context', 'General improvement needed')}\n\n"
                f"Generate 2-3 targeted search queries to find additional information "
                f"that will address the quality issues and improve this section."
            )
        ),
    ]

    result = structured_llm.invoke(prompt)

    # Execute web searches for each follow-up query
    search_results = []
    for q in result.question:
        try:
            search_result = tavily_search.invoke(q.query)
            search_results.append(f"Query: {q.query}\nResults: {search_result}")
        except Exception as e:
            search_results.append(f"Query: {q.query}\nError: {str(e)}")

    combined = "\n\n---\n\n".join(search_results)
    print(
        f"[followup_research] Completed {len(result.question)} searches "
        f"for '{state['heading']}'"
    )
    return {"follow_up_context": combined}


def rewrite_section(state: SectionState):
    """
    Rewrite the section incorporating new research findings
    and addressing quality issues.
    """

    llm = get_llm(temperature=0.7)

    prompt = [
        SystemMessage(content=section_rewriter_prompt),
        HumanMessage(
            content=(
                f"## Section Title: {state['heading']}\n\n"
                f"## Previous Draft:\n{state['section_content']}\n\n"
                f"## Original Research Context:\n"
                f"Sources: {state['sources']}\n"
                f"Notes: {state['notes']}\n"
                f"Draft: {state['draft']}\n\n"
                f"## Additional Research Findings:\n{state['follow_up_context']}\n\n"
                f"Rewrite and substantially improve this section.\n"
                f"Must be 500-2000 words. Address all quality issues and "
                f"incorporate the new research."
            )
        ),
    ]

    response = llm.invoke(prompt)
    print(f"[rewrite_section] Rewrote section: {state['heading']}")
    return {"section_content": response.content}


def finalize_section(state: SectionState):
    """Package the completed section for collection in the main state."""

    return {
        "sections": [
            {
                "heading": state["heading"],
                "content": state["section_content"],
                "order": state.get("order", 0),
            }
        ]
    }



section_builder = StateGraph(SectionState)
section_builder.add_node("generate_section", generate_section)
section_builder.add_node("check_quality", check_quality)
section_builder.add_node("followup_research", followup_research)
section_builder.add_node("rewrite_section", rewrite_section)
section_builder.add_node("finalize_section", finalize_section)

section_builder.add_edge(START, "generate_section")
section_builder.add_edge("generate_section", "check_quality")
section_builder.add_conditional_edges(
    "check_quality",
    quality_router,
    {"pass": "finalize_section", "fail": "followup_research"},
)
section_builder.add_edge("followup_research", "rewrite_section")
section_builder.add_edge("rewrite_section", "finalize_section")
section_builder.add_edge("finalize_section", END)

section_pipeline = section_builder.compile()


def run_section_pipeline(state: SectionState):
    """Wrapper that invokes the section subgraph and returns only 'sections'.

    This prevents parallel subgraphs from writing non-annotated keys
    (sources, notes, draft, etc.) back to the parent State concurrently.
    """
    result = section_pipeline.invoke(dict(state))
    return {"sections": result.get("sections", [])}



g = StateGraph(State)
g.add_node("read_sources", read_sources)
g.add_node("heading_generator", heading_generator)
g.add_node("section_pipeline", run_section_pipeline)
g.add_node("collect_sections", collect_sections)

g.add_edge(START, "read_sources")
g.add_edge("read_sources", "heading_generator")
g.add_conditional_edges("heading_generator", process_topic, ["section_pipeline"])
g.add_edge("section_pipeline", "collect_sections")
g.add_edge("collect_sections", END)

app = g.compile()


def run_writer_agent(tid: str = "hsi") -> str:
    """Public entry point: run the writer pipeline and return the final report.

    Args:
        tid: thread id used to locate research files.

    Returns:
        The formatted final report string.
    """
    global thread_id
    thread_id = tid

    result = app.invoke({"requirements": ""})
    return result.get("final_report", "No report generated")


if __name__ == "__main__":
    report = run_writer_agent()
    print("\n\n========== FINAL REPORT ==========\n")
    print(report)
