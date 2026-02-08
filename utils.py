from typing import Any, Dict, List
from langchain_core.messages import AnyMessage, AIMessage, HumanMessage, BaseMessage
import tiktoken


def get_task_topic(messages: List[AnyMessage]) -> str:
    """
    Get the query topic from the messages.
    """
    # check if request has a history and combine the messages into a single string
    if len(messages) == 1:
        research_topic = messages[-1].content
    else:
        research_topic = ""
        for message in messages:
            if isinstance(message, HumanMessage):
                research_topic += f"User: {message.content}\n"
            elif isinstance(message, AIMessage):
                research_topic += f"Assistant: {message.content}\n"
    return research_topic #type: ignore


class TokenManger:
    """Manage token counts for conversations"""
    
    def __init__(self, model: str, max_tokens: int = 5000):
        self.model = model
        self.max_tokens= max_tokens
        
        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")
            
    def count_token(self, messages: List[BaseMessage]) -> int:
        """Count total tokens in messages"""
        num_tokens = 0
        
        for message in messages:
            num_tokens += 4
            
            # Content
            if hasattr(message, 'content') and message.content:
                num_tokens += len(self.encoding.encode(str(message.content)))
            
            # Name - FIX: Check if it exists AND is not None
            if hasattr(message, 'name') and message.name is not None:
                num_tokens += len(self.encoding.encode(str(message.name)))  # ✅ Convert to string
        
        num_tokens += 2
        return num_tokens
    

    def count_string_tokens(self, text: str) -> int:
        """Count token in  a string"""
        return len(self.encoding.encode(text))
    
    def should_summarize(self, messages: List[BaseMessage]) -> bool:
        """Check if message exceed token limit"""
        return self.count_token(messages) > self.max_tokens
    
    def get_message_to_keep(self, messages: List[BaseMessage], keep_tokens: int = 1000) -> tuple:
        """Split message into to_summarize and to_keep based on tokens"""
        
        total_tokens = self.count_token(messages)
        if total_tokens <= self.max_tokens:
            return [], messages
        
        to_keep = [] 
        current_tokens = 0
        
        for message in reversed(messages):
            msg_tokens = self.count_tokens([message])
            if current_tokens + msg_tokens > keep_tokens:
                break
                to_keep.insert(0, message)
                current_tokens += msg_tokens
        to_summarize = messages[:len(messages)-len(to_keep)]
            
        return to_summarize, to_keep