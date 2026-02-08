import os

from pydantic import BaseModel, Field
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

class Configration(BaseModel):
    """
    The configration for the agent.
    """
    
    query_generation_model: str = Field(
        default="llama3.2:latest",
        description="Name of the model for to use for query generation"
    )
    
    query_count: int = Field(
        default=3,
        description="Number of inital search to generate query"
    )
    
    max_question: int = Field(
        default=3,
        description="Number of question to understand user query"
    )
    
    max_research_loop: int = Field(
        default=3,
        description="Maximum number of research loop to perform in certain topic"
    )
    
    max_follow_up_question: int = Field(
        default=3,
        description="Maximum number of follow up question asked by user."
    )
    
    
    
    @classmethod
    def from_runnable_config(cls, config: Optional[RunnableConfig] = None) -> "Configration":
        """Create a Configuration instance from a RunnableConfig."""
        
        configurable = (
            config["configurable"] if config and "configurable" in config else {}
        )
        
        raw_values: dict[str, Any] = {
            name: os.environ.get(name.upper(), configurable.get(name))
            for name in cls.model_fields.keys()
        }

        values = {k: v for k, v in raw_values.items() if v is not None}
        
        return cls(**values)