import os
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from enum import Enum


class DirectoryMapping(Enum):
    QUESTION = "questions"
    SOURCE = "sources"
    NOTE = "notes"
    CLAIM = "claims"
    DRAFT = "drafts"
    STATE = "states"
    TODO = "todo"

root_dir = "/mnt/d/Personal Projects/deep_agent/research"


def search_tool(state, thread_id: str):
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

edit_json_tool({"phase": "TODO"}, {"id": 1, "status": "In Progress"}, "quatum_beats", "2026-01-17-10361edb.json")