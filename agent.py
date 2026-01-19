import os
import json
from pydantic import SecretStr
from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send, Command
from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableConfig
from langchain.agents import create_agent

from states import OverallState, QueryGenerationState, TaskListState, Query
from schema import TaskListSchema, FollowQuestion
from configration import Configration
from prompt import todo_task, ask_detail_question, brief_answer, question_generator
from utils import get_task_topic
from tools import read_tool, write_json_tool, search_file_with_keyword, edit_json_tool, search_tool

from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch

load_dotenv(find_dotenv())

thread_id = "quantum"

if os.getenv("OPENROUTER_API_KEY") is None:
    raise ValueError("OPENROUTER Key not Found.")

if os.getenv("TAVILY_API_KEY") is None:
    raise ValueError("Tavily Key not Found.")


def indepth_reasoning(state: OverallState, config: RunnableConfig):
    """Langgraph node that asks user question to understand about their query
    
    Uses Nvidia Nemontron 3 to create an optimized question to understand users initial query.

    Args:
        state (OverallState): Current graph state containing the User's question
        config (RunnableConfig): Configration for the runnable, including LLM provideer settings
    """
    
    configurable =  Configration.from_runnable_config(config)
    
    llm = ChatOpenAI(
        api_key=SecretStr(os.getenv("OPENROUTER_API_KEY") or ""),
        temperature=1.0,
        base_url="https://openrouter.ai/api/v1"
    )
    
    formatted_prompt = f"""
                        {ask_detail_question}
                        \n\n
                        context:
                        {get_task_topic(state["messages"])}. ask me {configurable.max_question} question
                        """
    result = llm.invoke(formatted_prompt)
    print(result)
    # This to ask user questtion to understand their intend
    user_input = input(">>")
    state["messages"] += HumanMessage(content=user_input)
    breif_task_prompt = f"""
                        {brief_answer}
                        \n\n
                        {state["messages"]}
                        """
    result = llm.invoke(breif_task_prompt)
    return {"brief": result.content}

def generate_tasklist(state: OverallState, config: RunnableConfig) -> TaskListState:
    """Langgraph node that generate overall plan for the task base on user's question.
    
    Uses Nvidia Nemotron 3 to create an optimized refine plan to solve user query.

    Args:
        state (OverallState): Current graph state containing the User's question
        config (RunnableConfig): Configration for the runnable, including LLM provideer settings

    Returns:
        TaskListState: Dictionary with state update and tasking for agent planning.
    """
    state["phase"] = "TODO"
    configurable = Configration.from_runnable_config(config)
    
    llm = ChatOpenAI(
        api_key=SecretStr(os.getenv("OPENROUTER_API_KEY") or ""),
        temperature=1.0,
        base_url="https://openrouter.ai/api/v1",
    )
    
    structured_llm = llm.with_structured_output(TaskListSchema)
    formatted_prompt = f"""
                        {todo_task}
                        \n\n
                        context:
                        {state["brief"]}
                    """
    
    result = structured_llm.invoke(formatted_prompt)
    savestate = [r.model_dump() for r in result.tasks]
    filename = search_tool(state, thread_id)
    if filename:
        write_json_tool(state, savestate, thread_id, filename)
    else:
        write_json_tool(state, savestate, thread_id)
    return {"task_list": result.tasks}


def select_next_task(state: OverallState):
    """Select the next task to work on"""
    tasks = state.get("task_list", [])
    
    for task in tasks:
        if task.status == "Not Started":  # Not task["status"]
            state["phase"] = "TODO"
            filename = search_tool(state, thread_id)
            content = {"task": task.task, "id": task.id, "status": "In Progress"}
            edit_json_tool(state, content, thread_id, filename)
            return {"current_task": task.task, "current_task_id": task.id}
    # All tasks completed
    return {"current_task": None, "current_task_id": None}




def generate_follow_question(state: OverallState, config: RunnableConfig) -> QueryGenerationState:
    """_summary_

    Args:
        state (OverallState): _description_
        config (RunnableConfig): _description_

    Returns:
        QueryGenerationState: _description_
    """
    configurable = Configration.from_runnable_config(config) 
    llm = ChatOpenAI(
        api_key=SecretStr(os.getenv("OPENROUTER_API_KEY") or ""),
        temperature=1.0,
        base_url="https://openrouter.ai/api/v1"
    )   
    browser_client = TavilySearch(max_results=5, 
                                topic="general", 
                                search_depth="basic",
                                response_format="content",
                                include_answer=True
                                )

    agent = create_agent(llm, tools=[browser_client])
    response  = agent.invoke({"messages": state["messages"][0].content})
    formatted_prompt = f"{question_generator}".format(user_question=state["messages"][0].content, search_result=response["messages"][-1].content, number_of_question=5, research_task=state["current_task"])
    structured_llm = llm.with_structured_output(FollowQuestion)
    result = structured_llm.invoke(formatted_prompt)
    
    state["phase"] = "NOTE"
    filename = search_tool(state, thread_id)
    if filename:
        write_json_tool(state, [{"id":1, "question": state["messages"][0].content, "note": response["messages"][-1].content}], thread_id, filename)
    else:
        write_json_tool(state, [{"id":1, "question": state["messages"][0].content, "note": response["messages"][-1].content}], thread_id)
    
    state["phase"] = "QUESTION"
    savestate = [r.model_dump() for r in result.question]
    filename = search_tool(state, thread_id)
    if filename:
        write_json_tool(state, savestate, thread_id, filename)
    else:
        write_json_tool(state, savestate, thread_id)
        
    state["phase"] = "SOURCE"
    sources = []
    for msg in response["messages"]:
        if isinstance(msg, ToolMessage):
            for count, i in enumerate(json.loads(msg.content)["results"]):
                i["id"] = count
                sources.append(i)
    filename = search_tool(state, thread_id)
    if filename:
        write_json_tool(state, sources, thread_id, filename)
    else:
        write_json_tool(state, sources, thread_id)
        
    return {"query": result.question}




def summarize_conversation_node(state: OverallState):
    """Node function to summarize conversation"""
    messages = state.get("messages", [])
    
    # Don't summarize if not needed
    if len(messages) <= 10:
        return {}

    
    llm = ChatOpenAI(
        api_key=SecretStr(os.getenv("OPENROUTER_API_KEY") or ""),
        temperature=1.0,
        base_url="https://openrouter.ai/api/v1"
    ) 
    
    # Summarize old messages, keep recent ones
    to_summarize = messages[:-5]
    to_keep = messages[-5:]
    
    if to_summarize:
        summary_prompt = f"""Briefly summarize this research conversation:

        {chr(10).join([f"{m.type}: {m.content[:150]}..." for m in to_summarize])}

        Provide a 2-3 sentence summary:"""
        
        summary = llm.invoke(summary_prompt)
        
        return {
            "messages": [
                SystemMessage(content=f"📋 Summary: {summary.content}"),
                *to_keep
            ]
        }
    
    return {}

def deep_research(state: Query, config: RunnableConfig) -> OverallState:
    configurable = Configration.from_runnable_config(config) 
    llm = ChatOpenAI(
        api_key=SecretStr(os.getenv("OPENROUTER_API_KEY") or ""),
        temperature=1.0,
        base_url="https://openrouter.ai/api/v1"
    )  
    browser_client = TavilySearch(max_results=5, 
                                topic="general", 
                                search_depth="advanced",
                                response_format="content",
                                include_answer=True
                                )
    agent = create_agent(llm, tools=[browser_client])
    response  = agent.invoke({"messages": state.query}, config={"max_tokens": 1000})
    
    phase = {"phase":"SOURCE"}
    sources = []
    for msg in response["messages"]:
        if isinstance(msg, ToolMessage):
            for count, i in enumerate(json.loads(msg.content)["results"]):
                i["id"] = count
                sources.append(i)
    filename = search_tool(phase, thread_id)
    if filename:
        write_json_tool(phase, sources, thread_id, filename)
    else:
        write_json_tool(phase, sources, thread_id)


    for message in response["messages"]:
        if isinstance(message, ToolMessage):            
            phase = {"phase":"NOTE"}
            filename = search_tool(phase, thread_id)
            if filename:
                write_json_tool(phase, [{"id":1, "question": json.loads(message.content)["query"], "note": json.loads(message.content)["answer"]}], thread_id, filename)
            else:
                write_json_tool(phase, [{"id":1, "question": json.loads(message.content)["query"], "note": json.loads(message.content)["answer"]}], thread_id)
            
            phase = {"phase":"SOURCE"}
            sources = []
            for count, i in enumerate(json.loads(message.content)["results"]):
                i["id"] = count
                sources.append(i)
            filename = search_tool(phase, thread_id)
            if filename:
                write_json_tool(phase, sources, thread_id, filename)
            else:
                write_json_tool(phase, sources, thread_id)
        
    return {"sources": sources}
    

    
def fan_out_followups(state: OverallState):
    
    queries = state.get("query", [])
    
    if not queries:
        print("WARNING: No queries to fan out!")
        return {}
    
    # Send each Query object to deep_research
    sends = [
        Send("deep_research", query)  # Send the entire Query dict
        for query in queries
    ]
    
    return Command(goto=sends)
checkpointer = MemorySaver()
config = {"configurable": {"thread_id": thread_id}}
builder = StateGraph(OverallState, context_schema=Configration)
builder.add_node("generate_breif_question", indepth_reasoning)
builder.add_node("generate_todo", generate_tasklist)
builder.add_node("select_next_task", select_next_task)
builder.add_node("summarize_messages", summarize_conversation_node)
builder.add_node("generate_follow_question", generate_follow_question)
builder.add_node("fan_out_followups", fan_out_followups)
builder.add_node("deep_research", deep_research)

builder.add_edge(START, "generate_breif_question")
builder.add_edge("generate_breif_question", "generate_todo")
builder.add_edge("generate_todo", "select_next_task")
builder.add_edge("select_next_task", "summarize_messages")
builder.add_edge("summarize_messages", "generate_follow_question")
builder.add_edge("generate_follow_question", "fan_out_followups")
builder.add_edge("deep_research", END)

# graph = builder.compile(name="pro-search-agent", checkpointer=checkpointer)
graph = builder.compile(name="pro-search-agent")
for chunk in graph.stream({"messages": HumanMessage(content="I need to research about quantum computing and its mordern application,")}, stream_mode="updates", config=config):
    print(chunk)
# 

