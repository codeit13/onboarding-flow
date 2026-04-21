#!/usr/bin/env python3
"""Script to create a properly encoded .env file with necessary environment variables"""
import os

def create_env_file():
    """Create a .env file with necessary environment variables"""
    # Define the environment variables
    env_vars = {
        "OPENAI_API_KEY": "",  # Replace with actual key
        "DEEPGRAM_API_KEY": "",  # Replace with actual key
        "HOST": "0.0.0.0",
        "PORT": "8000"
    }

    # Write to .env file
    with open('.env', 'w', encoding='utf-8') as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")

    print("Created .env file successfully!")
    return True

if __name__ == "__main__":
    create_env_file() 