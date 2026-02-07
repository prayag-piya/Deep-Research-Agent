import os
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from enum import Enum
import json
from dotenv import find_dotenv, load_dotenv
from tavily import TavilyClient
from langchain_core.tools import tool

load_dotenv(find_dotenv())

class DirectoryMapping(Enum):
    QUESTION = "questions"
    SOURCE = "sources"
    NOTE = "notes"
    CLAIM = "claims"
    DRAFT = "drafts"
    STATE = "states"
    TODO = "todo"

root_dir = "/mnt/d/Personal Projects/deep_agent/research"
TAVILY_CLIENT = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

@tool
def tavily_search(query: str) -> str:
    """Search the web for information on a given topic.

    Args:
        query: The search query string
    """
    try:
        results = TAVILY_CLIENT.search(
            query=query,
            max_results=5,
            search_depth="advanced",
            include_answer=True,
            include_images=False,
            time_range="year",
            # No start_date or end_date
        )
        return json.dumps(results)  # Always return valid JSON string
    except Exception as e:
        return json.dumps({"error": str(e), "results": []})


@tool
def tavily_search_basic(query: str) -> str:
    """Search the web for basic information on a given topic.

    Args:
        query: The search query string
    """
    try:
        results = TAVILY_CLIENT.search(
            query=query,
            max_results=5,
            search_depth="basic",
            include_answer=True,
            include_images=False,
            time_range="year",
        )
        return json.dumps(results)
    except Exception as e:
        return json.dumps({"error": str(e), "results": []})


def search_tool(state, thread_id: str) -> str | None:
    """_summary_

    Args:
        state (_type_): _description_
        thread_id (str): _description_
    """
    date = datetime.now().date()
    target_folder = f"{getattr(DirectoryMapping, state["phase"]).value}_{thread_id}"
    directory = Path(root_dir).joinpath(target_folder)
    if Path.is_dir(directory):
        for file in Path(directory).glob("*.json"):
            if file.name.startswith(f"{date}"):
                return file.name
    else:
        return None


def read_todo(thread_id: str) -> dict:
    """Read todo function reads the todo task

    Args:
        thread_id (str): thread_id is used to name file and search the file

    Returns:
        dict: Returns TODO which is list of task 
    """
    file_name = search_tool({"phase": "TODO"}, thread_id)
    if file_name != None:
        root_path = f"{Path(root_dir).joinpath(f"todo_{thread_id}")}/{file_name}"
        with open(root_path, "r") as file:
            return json.load(file)
    return {"Error": "No todos found in research folder"}

def write_todo(thread_id: str, content) -> dict:
    """Create or update the todo list
    calls search tool to locate the file if no file is found creates a todo list file
    Args:
        thread_id (str): thread_id is used to name file and search the file
        content (dict): Data to update todo list or create todo list

    Returns:
        dict: returns the content argument
    """
    file_name = search_tool({"phase": "TODO"}, thread_id)
    if file_name != None:
        root_path = f"{Path(root_dir).joinpath(f"todo_{thread_id}")}/{file_name}"
        with open(root_path, "r") as file:
            todos = json.load(file)
        for count, todo in enumerate(todos):
            if todo["id"] == content["id"]:
                todos[count] = content
        with open(root_path, "w") as file:
            json.dump(todos, file)
        return content
    else:
        date = datetime.now().date()
        Path(f"{root_dir}/todo_{thread_id}").mkdir(parents=True, exist_ok=True)
        root_path = f"{Path(root_dir).joinpath(f"todo_{thread_id}")}/{date}-{uuid4().hex[:8]}.json"
        with open(root_path, "w") as file:
            json.dump(content, file)
        return content
        

def read_file(folder: str, thread_id: str, filename = None) -> list:
    """Read file function reads specific file if filename provided or read entire folder

    Args:
        folder (str): Name of the folder where file is located
        thread_id (str): thread_id is used to name file and search the file
        filename (_type_, optional): Filename if you want to read only specific file. Defaults to None.

    Returns:
        dict: return contains of the folder or content of folder in key value pair with filename as key 
    """
    if filename != None:
        target_file = Path(root_dir).joinpath(f"{folder}_{thread_id}/{filename}")
        with open(target_file, "r") as file:
            data = json.load(file)
            return data
    else:
        datas = []
        target_folder = Path(root_dir).joinpath(f"{folder}_{thread_id}")
        for files in Path(target_folder).glob("*.json"):
            data = json.loads(files.read_text())
            datas.extend(data)
        return datas

def edit_file(content: dict, filename: Path):
    data = json.loads(filename.read_text())
    id = len(data) + 1
    content["id"] = id
    data.append(content)
    with open(filename, "w") as file:
        json.dump(data, file)

def write_file(folder: str, thread_id: str, contents: list[dict]) -> list[dict]:
    date = datetime.now().date()
    root_path = f"{Path(root_dir).joinpath(f"{folder}_{thread_id}")}"
    Path(root_path).mkdir(parents=True, exist_ok=True)
    for file in Path(root_path).glob("*.json"):
        filename = "-".join(file.name.split("-")[:-1])
        if filename == f"{date}":
            for content in contents:
                edit_file(content, file)
            return contents
    with open(f"{root_path}/{date}-{uuid4().hex[:8]}.json", "w") as file:
        json.dump(contents, file)
    return contents






































def write_json_tool(state, content, thread_id: str, filename=None):
    """This tool write content to file for agent memory

    Args:
        state (dict): LLM agent states where we can check what kind of task we are working on
        content (dict | str): Either string or json we can pass to dump on file

    Returns:
        str: File path
    """
    target_folder = f"{getattr(DirectoryMapping, state["phase"]).value}_{thread_id}"
    directory = Path(root_dir).joinpath(target_folder)
    Path(directory).mkdir(parents=True, exist_ok=True)
    if filename:
        filepath = Path(directory) / filename
        if os.path.exists(filepath):
            with open(filepath, "r") as file:
                data = json.load(file)
                for d in content:
                    d["id"] += len(data)
                    data.append(d)
                filepath.write_text(json.dumps(data))
    else:
        filename = f"{datetime.now().date()}-{uuid4().hex[:8]}.json"
        filepath = Path(directory) / filename
        filepath.write_text(json.dumps(content))
    
    return filepath
   
 
def read_tool(state, thread_id: str, filename):
    """This tool reads file content provided in filepath argument

    Args:
        state (dict): LLM agent states where we can check what kind of task we are working on
        filepath (str): File path
    
    Returns:
        str: File content
    """
    
    target_folder = f"{getattr(DirectoryMapping, state["phase"]).value}_{thread_id}"
    directory = Path(root_dir).joinpath(target_folder)
    
    if Path.is_dir(directory):
        file_path = Path(directory).joinpath(filename)
        with open(file_path, "r") as file:
            return file.read()


     
def edit_json_tool(state, content, thread_id: str, filename: None | str):
    """This tool edit file with provided content"""
    
    target_folder = f"{getattr(DirectoryMapping, state['phase']).value}_{thread_id}"
    directory = Path(root_dir).joinpath(target_folder)
    
    if directory.is_dir():
        if filename:
            file_path = directory.joinpath(filename)
            
            with open(file_path, "r") as file:
                datas = json.load(file)
            
            # Fix: Update using index
            for i, data in enumerate(datas):
                if data["id"] == content["id"]:
                    # Update the item in the list
                    datas[i] = {**data, **content}  # Merge with new content
                    print(f"Updated: {datas[i]}")
            
            # Write back to file
            with open(file_path, "w") as file:
                json.dump(datas, file, indent=2)

def search_file_with_keyword(state, query, key, thread_id: str, filename = None | str):
    """This is used for keyword searching in  file to retrive related information

    Args:
        state (_type_): LLM agent states where we can check what kind of task we are working on
        query (_type_): question or query that needs to be searched
        key (_type_): which key is it stored on in file since everything is in json
        filename (str | None): if filename is provided it will just search and return content from that file

    Returns:
        _type_: None or List of file path
    """
    target_folder = f"{getattr(DirectoryMapping, state["phase"]).value}_{thread_id}"
    directory = Path(root_dir).joinpath(target_folder)
    results = []
    if Path.is_dir(directory):
        if filename:
            file_path = Path(directory).joinpath(filename)
            data = json.loads(Path.read_text(file_path))
            if query.lower() in data[key].lower():
                results.append(file_path)
                return results
        else:
            for file in Path(directory).glob("*.json"):
                data = json.loads(file.read_text())
                if query.lower() in data["claim"].lower():
                    results.append(file)
            return results
    else:
        return None

# write_file("todo", "quantum", [{"some": "new"}])