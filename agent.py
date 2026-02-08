import os
import json
import ast 
from typing import Literal
from functools import lru_cache
from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send, Command
from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableConfig
from langchain.agents import create_agent

from states import OverallState, TaskListState, Query
from schema import TaskListSchema, FollowQuestion, Classifier
from configration import Configration
from prompt import todo_task, ask_detail_question, brief_answer, question_generator, classifier, draft_writer
from utils import get_task_topic
from tools import write_file, write_todo, tavily_search_basic, tavily_search

from langchain_ollama import ChatOllama
# from langchain_openai import ChatOpenAI
from writer_agent import run_writer_agent

load_dotenv(find_dotenv())

thread_id = "hsi"


if os.getenv("OPENROUTER_API_KEY") is None:
    raise ValueError("OPENROUTER Key not Found.")

if os.getenv("TAVILY_API_KEY") is None:
    raise ValueError("Tavily Key not Found.")

@lru_cache(maxsize=None)
def get_llm(model: str = "llama3.2:latest", temperature: float = 0.7) -> ChatOllama:
    return ChatOllama(
        model=model,
        temperature=temperature,
    )


def indepth_reasoning(state: OverallState, config: RunnableConfig):
    """Langgraph node that asks user question to understand about their query
    
    Uses llama3.2:latest to create an optimized question to understand users initial query.

    Args:
        state (OverallState): Current graph state containing the User's question
        config (RunnableConfig): Configration for the runnable, including LLM provideer settings
    """
    
    configurable =  Configration.from_runnable_config(config)
    llm = get_llm(temperature=0.5)
    formatted_prompt = f"""
                        {ask_detail_question}
                        \n\n
                        context:
                        {get_task_topic(state["messages"])}. ask me {configurable.max_question} question
                        """
    result = llm.invoke(formatted_prompt)
    # This to ask user questtion to understand their intend
    print(result.content)
    user_input = input(">>")
    state["messages"] += [HumanMessage(content=user_input)]
    breif_task_prompt = f"""
                        {brief_answer}
                        \n\n
                        {state["messages"]}
                        """
    result = llm.invoke(breif_task_prompt)
    return {"brief": result.content}



def generate_tasklist(state: OverallState, config: RunnableConfig) -> TaskListState:
    """Langgraph node that generate overall plan for the task base on user's question.
    
    Uses llama3.2:latest to create an optimized refine plan to solve user query.

    Args:
        state (OverallState): Current graph state containing the User's question
        config (RunnableConfig): Configration for the runnable, including LLM provideer settings

    Returns:
        TaskListState: Dictionary with state update and tasking for agent planning.
    """
    configurable = Configration.from_runnable_config(config)
    llm = get_llm(temperature=0.3)
    llm = llm.bind(format="json")
    structured_llm = llm.with_structured_output(TaskListSchema)
    formatted_prompt = f"""
                        {todo_task}
                        \n\n
                        context:
                        {state["brief"]}
                    """
    
    result = structured_llm.invoke(formatted_prompt)
    savestate = [r.model_dump() for r in result.tasks]
    write_todo(thread_id, savestate)    
    
    return {"task_list": savestate}


def select_next_task(state: OverallState):
    """Select the next task to work on"""
    tasks = state.get("task_list", [])
    
    for task in tasks:
        if task["status"] == "Not Started":  # Not task["status"]
            content = {"task": task["task"], "id": task["id"], "status": "In Progress"}
            task["status"] = "In Progress"
            write_todo(thread_id, content)
            return {"current_task": task["task"], "current_task_id": task["id"]}
    # All tasks completed
    return {"current_task": None, "current_task_id": None}

def task_router(state: OverallState) -> Literal["task", "completed"]:
    """Task router for agent"""
    if state["current_task"] != None and state["current_task_id"] != None:
        return "task"
    return "completed"


# Optimizing code

def surface_research(state: OverallState, config: RunnableConfig):
    """Surface Research as name suggest does a light research on following topic and return a notes strcture format 

    Args:
        state (OverallState): Current graph state containing the User's question
        config (RunnableConfig): Configration for the runnable, including LLM provideer settings
    """
    configurable =  Configration.from_runnable_config(config)
    
    # Setup
    llm = get_llm(temperature=0.3) 

    agent = create_agent(llm, tools=[tavily_search_basic])

    surface_research_prompt = f"You are a light research agent whos task is search web for a topic provide by a user. \n\n you will be provided with breif task, which will be the end goal and each task to will take you closer to end goal your task is to foucs on task provided and research web but make sure you research supports the end goal. \n\n"
    
    message = f"Breif Task: {state["brief"]}, Your Task to Resaerch : {state["current_task"]}"
    response = agent.invoke({"messages": [SystemMessage(content=surface_research_prompt), HumanMessage(content=message)]})
    joined_text = ""
    for message in response["messages"]:
        if isinstance(message, ToolMessage) and message.name == "tavily_search_basic":
            try:
                # Handle empty content
                if not message.content or message.content.strip() == "":
                    print("Skipping empty message content")
                    continue
                    
                content = json.loads(message.content)
                
                if "error" in content:
                    print(f"Skipping error message: {content['error']}")
                    continue
                
                if "results" not in content:
                    continue
                
                for count, result in enumerate(content["results"]):
                    if "content" in result and result["content"]:
                        joined_text += result["content"] + "\n\n"
                        result["id"] = count
                write_file("sources", thread_id, content["results"])
            except json.JSONDecodeError as e:
                print(f"Failed to parse message content as JSON: {e}")
                print(f"Content was: {message.content[:200]}...")  # Show first 200 chars
                continue
            except Exception as e:
                print(f"Unexpected error processing message: {e}")
                continue
            notes = [{
                "id": 1,
                "question": state["current_task"],
                "note": content.get("answer", "No answer available")
            }]
            write_file("notes", thread_id, notes)

    joined_text = joined_text.strip()
    return {"research": joined_text}
    
                                                                                                                                                                                                                                                                                                                                                                                                                                                        

def generate_followup_question(state: OverallState, config: RunnableConfig):
    """Generate follow-up question based on initial research"""

    configurable =  Configration.from_runnable_config(config)
    llm = get_llm(temperature=0.3)
    llm = llm.bind(format="json")
    formatted_prompt = question_generator.format(research_task=state["brief"], search_result=state["research"], number_of_question=configurable.max_follow_up_question)
    structured_llm = llm.with_structured_output(FollowQuestion)
    
    response = structured_llm.invoke(formatted_prompt)
    
    if response:
        question = [ques.model_dump() for ques in response.question]
        write_file("question", thread_id, question)
        
    return {"query": response.question}

    

def parallel_research(state: OverallState, config: RunnableConfig):
    """Parallel research agent which search web for follow up question"""
    
    configurable = Configration.from_runnable_config(config)
    sends = [Send("deep_research", {"query": q}) for q in state["query"]]
    
    return Command(
        update={},
        goto=sends
    )


def deep_research(state: Query, config: RunnableConfig):
    """Deep research function researchs deep about the following problem"""
    
    configurable = Configration.from_runnable_config(config)
    llm = get_llm(temperature=0)
    agent = create_agent(llm, tools=[tavily_search])
    
    
    query_obj = state["query"]
    if hasattr(query_obj, 'query'):
        query_text = query_obj.query
    elif hasattr(query_obj, 'model_dump'):
        query_data = query_obj.model_dump()
        query_text = query_data.get('query', str(query_obj))
    else:
        query_text = str(query_obj)
    
    
    response  = agent.invoke({"messages": HumanMessage(content=query_text)})
    sources = []
    notes = []
    
    for count, resp in enumerate(reversed(response["messages"])):
        if isinstance(resp, ToolMessage):
            try:
                # First try JSON parsing
                content = json.loads(resp.content)
            except json.JSONDecodeError:
                try:
                    # Then try literal eval
                    content = ast.literal_eval(resp.content)
                except (ValueError, SyntaxError):
                    # If both fail, skip this message or handle as plain text
                    print(f"Could not parse tool message content: {resp.content[:100]}...")
                    continue
            
            if isinstance(content, str):
                # If content is just a string, skip it
                print(f"Skipping string content: {content[:100]}...")
                continue
            
            if not isinstance(content, dict):
                print(f"Content is not a dictionary: {type(content)}")
                continue
            
            if "error" in content:
                print(f"Search tool returned error: {content['error']}")
                continue
            
            if "query" not in content or "results" not in content:
                print(f"Invalid content structure: {content.keys()}")
                continue
            
            note_data = {
                "id": count,
                "question": content.get("query", "Unknown"),
                "note": content.get("answer", "No answer available")
            }
            
            for count, source in enumerate(content.get("results", [])):
                source["id"] = count
                sources.append(source)
            notes.append(note_data)     
    write_file("notes", thread_id, notes)
    write_file("sources", thread_id, sources)
    
    return {"search_response": sources, "search_notes": notes}
    
def classifier_research(state: OverallState, config: RunnableConfig):
    """Classifer to determine research heading"""
    
    content = "Notes: \n"
    
    for note in state["search_notes"]:
        content += (note.get("note") or "") + "\n"
        
    content += "\n Sources: \n"
    for source in state["search_response"]:
        content += (source.get("content") or "") + "\n\n"
    
    llm = get_llm(temperature=0.3)
    llm = llm.bind(format="json")
    structure_llm = llm.with_structured_output(Classifier)
    
    response = structure_llm.invoke([SystemMessage(content=classifier), HumanMessage(content=content)])
    return {"classifier": response.sections}



def parallel_drafter(state: OverallState, config: RunnableConfig):
    """If classifier has two section it will sent to drafter according"""
    
    configurable = Configration.from_runnable_config(config)
    sends = [Send("generate_draft", {"classifier": q, 
                                    "search_response": state.get("search_response", []),
                                    "research_notes": state.get("research_notes", []),
                                    "current_task_id": state.get("current_task_id"),
                                    "current_task": state.get("current_task"),
                                    "brief": state.get("brief")}) for q in state["classifier"]]
    return Command(
        update={},
        goto=sends
    )


def generate_draft(state: OverallState, config: RunnableConfig):
    """Generate draft according user input for section"""
    
    configrurable = Configration.from_runnable_config(config)
    llm = get_llm(temperature=1.0)
    formatted_prompt = f"\n\nSection: \n\n {state["classifier"]} \n\n Researching about : {state["brief"]} \n\n Research data : {state["search_response"]}"
    # formatted_prompt = draft_writer.format(section_name=state["classifier"], target_audience="Academic Researcher", tone="Professional", research_data=state["search_response"], brief_question=state["brief"])
    response = llm.invoke([SystemMessage(content=draft_writer), HumanMessage(content=formatted_prompt)])
    
    resp = {"content": response.content, "id": 1, "section": state["classifier"]}
    
    
    current_task_id = state.get("current_task_id")
    if current_task_id is not None:
        write_todo(thread_id, {"task": state.get("current_task", ""), "id": current_task_id, "status": "Completed"})
    write_file("draft", thread_id, [resp])
    
    return {"search_response": [], "search_notes": [], "draft": [resp]}
    
    
def reroute_task_selection(state: OverallState, config: RunnableConfig):
    """Check if all tasks are done; if so, route to writer, else next task."""
    tasks = state.get("task_list", [])
    if not tasks:
        return "completed"
    all_done = all(t.get("status") == "Completed" for t in tasks)
    if all_done:
        print("[reroute] All tasks completed — routing to write_report")
        return "completed"
    remaining = [t["task"] for t in tasks if t.get("status") != "Completed"]
    print(f"[reroute] {len(remaining)} tasks remaining — continuing research")
    return "task"


def write_report_node(state: OverallState, config: RunnableConfig):
    """Run the writer agent to produce the final formatted report."""
    report = run_writer_agent(tid=thread_id)
    print(f"[write_report_node] Final report generated ({len(report)} chars)")
    return {"messages": [AIMessage(content=report)]}
    
    

def summarize_conversation_node(state: OverallState, config: RunnableConfig):
    """Mark current task as completed in state, then summarize conversation."""
    
    # ── Update task_list to mark current task completed ──
    current_task_id = state.get("current_task_id")
    tasks = state.get("task_list", [])
    if current_task_id is not None:
        for task in tasks:
            if task["id"] == current_task_id:
                task["status"] = "Completed"
                break
    
    configrurable = Configration.from_runnable_config(config)
    llm = get_llm(temperature=0.5)  # Lower temp for more consistent summaries
    
    # Only summarize if we have more than 3 messages
    if len(state["messages"]) > 3:
        # Keep the last 3 messages, summarize the rest
        messages_to_summarize = state["messages"][:-3]
        messages_to_keep = state["messages"][-3:]
        
        # Build conversation text from messages to summarize
        previous_conversation = ""
        for msg in messages_to_summarize:
            if isinstance(msg, HumanMessage):
                previous_conversation += f"User: {msg.content}\n\n"
            elif isinstance(msg, AIMessage):
                previous_conversation += f"Assistant: {msg.content}\n\n"
            elif isinstance(msg, SystemMessage):
                previous_conversation += f"System: {msg.content}\n\n"
            elif isinstance(msg, ToolMessage):
                previous_conversation += f"Tool ({msg.name}): {msg.content[:200]}...\n\n"
        
        # Create summarization prompt
        system_prompt = """You are a helpful assistant whose task is to gather information from the conversation history 
                and keep all the important information while summarizing the memory. Focus on:
                - Key decisions and conclusions
                - Important facts and data discovered
                - User's goals and requirements
                - Progress made on tasks

                Create a concise summary that preserves critical context."""
                        
        user_prompt = f"""Summarize this conversation history:

                {previous_conversation}

                Provide a concise summary that captures all important information."""

        try:
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ])
            
            # Create a summary message
            summary_message = SystemMessage(
                content=f"[Conversation Summary]: {response.content}"
            )
            
            # Return summary + recent messages
            return {"messages": [summary_message] + messages_to_keep, "task_list": tasks}
            
        except Exception as e:
            print(f"Summarization failed: {e}")
            # If summarization fails, just keep recent messages
            return {"messages": messages_to_keep, "task_list": tasks}
    
    # If 3 or fewer messages, no need to summarize
    return {"messages": state["messages"], "task_list": tasks}





checkpointer = MemorySaver()
config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 150}
builder = StateGraph(OverallState, context_schema=Configration)


builder.add_node("indepth_reasoning", indepth_reasoning)
builder.add_node("generate_tasklist", generate_tasklist)
builder.add_node("select_next_task", select_next_task)
builder.add_node("task_router", task_router)
builder.add_node("surface_research", surface_research)
builder.add_node("generate_followup_question", generate_followup_question)
builder.add_node("parallel_research", parallel_research)
builder.add_node("deep_research", deep_research)
builder.add_node("classifier_research", classifier_research)
builder.add_node("parallel_drafter", parallel_drafter)
builder.add_node("generate_draft", generate_draft)
builder.add_node("reroute_task_selection", reroute_task_selection)
builder.add_node("summarize_conversation_node", summarize_conversation_node)
builder.add_node("write_report", write_report_node)


builder.add_edge(START, "indepth_reasoning")
builder.add_edge("indepth_reasoning", "generate_tasklist")
builder.add_edge("generate_tasklist", "select_next_task")
builder.add_conditional_edges("select_next_task", task_router, {"task": "surface_research", "completed": "write_report"})
builder.add_edge("write_report", END)
builder.add_edge("surface_research", "generate_followup_question")
builder.add_edge("generate_followup_question", "parallel_research")
builder.add_edge("deep_research", "classifier_research")
builder.add_edge("classifier_research", "parallel_drafter")
builder.add_edge("generate_draft", "summarize_conversation_node")
builder.add_conditional_edges(
    "summarize_conversation_node", reroute_task_selection, {
        "task": "select_next_task",
        "completed": "write_report"
    }
)

graph = builder.compile(name="pro-search-agent")

user_input = input("Enter research question >> ")
thread_id = input("Enter unique thread id >> ")

for chunk in graph.stream(
    {"messages": [HumanMessage(content=user_input)]}, 
    stream_mode="updates",
    config=config
):
    print(chunk)