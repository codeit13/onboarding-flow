import json
from typing import Dict, List, Any, Optional
import os

class MCPService:
    """A simple implementation of the Message Chain Protocol for our interviewer"""
    
    def __init__(self):
        """Initialize the MCP service"""
        self.messages = []
        
    def add_system_message(self, content: str) -> None:
        """Add a system message to the chain"""
        self.messages.append({
            "role": "system",
            "content": content
        })
    
    def add_user_message(self, content: str) -> None:
        """Add a user message to the chain"""
        self.messages.append({
            "role": "user",
            "content": content
        })
    
    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to the chain"""
        self.messages.append({
            "role": "assistant",
            "content": content
        })
    
    def get_messages(self) -> List[Dict[str, str]]:
        """Get all messages in the chain"""
        return self.messages
    
    def clear_messages(self) -> None:
        """Clear all messages in the chain"""
        self.messages = []
    
    def save_to_file(self, file_path: str) -> None:
        """Save the message chain to a file"""
        with open(file_path, 'w') as f:
            json.dump(self.messages, f, indent=2)
    
    def load_from_file(self, file_path: str) -> None:
        """Load a message chain from a file"""
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                self.messages = json.load(f)
    
    def get_last_n_messages(self, n: int) -> List[Dict[str, str]]:
        """Get the last n messages from the chain"""
        return self.messages[-n:] if n < len(self.messages) else self.messages
    
    def to_openai_messages(self) -> List[Dict[str, str]]:
        """Convert the message chain to OpenAI format"""
        return self.messages 