#!/usr/bin/env python3
"""
Robust script for running the Virtual Interviewer API.
This script:
1. Ensures environment variables are properly set
2. Clears proxy settings that might interfere with API calls
3. Creates necessary directories
4. Validates and fixes any corrupted interview data
5. Starts the FastAPI application with Uvicorn
"""

import os
import sys
import json
import logging
from pathlib import Path
from glob import glob
from datetime import datetime

# Configure logging with both console and file output
log_file = f"logs/app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, mode='a')
    ]
)

logger = logging.getLogger("virtual-interviewer")

def validate_interview_data():
    """Check and fix any inconsistencies in interview data files"""
    logger.info("Validating interview data files...")
    
    interview_files = glob("interview_data/*.json")
    fixed_count = 0
    
    for file_path in interview_files:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Ensure current_question_index is valid
            if "current_question_index" not in data:
                data["current_question_index"] = 0
                fixed_count += 1
            
            # Ensure questions array exists
            if "questions" not in data or not isinstance(data["questions"], list):
                data["questions"] = []
                fixed_count += 1
            
            # If any fixes were made, save the file
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error validating {file_path}: {str(e)}")
    
    logger.info(f"Validated {len(interview_files)} interview files, fixed {fixed_count} issues")

# First, ensure we're in the correct directory
backend_dir = Path(__file__).resolve().parent
os.chdir(backend_dir)

# Ensure logs directory exists before setting up logging
os.makedirs("logs", exist_ok=True)

# Print startup banner
logger.info("="*80)
logger.info("STARTING VIRTUAL INTERVIEWER API")
logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info(f"Log file: {log_file}")
logger.info("="*80)

# Clear any proxy environment variables that might cause issues
proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]
for var in proxy_vars:
    if var in os.environ:
        logger.info(f"Removing {var} from environment variables")
        os.environ.pop(var, None)

# Set no_proxy to bypass all proxy settings
os.environ['no_proxy'] = '*'

# Ensure data directories exist
os.makedirs("interview_data", exist_ok=True)
os.makedirs("mcp_data", exist_ok=True)

# Validate existing interview data
validate_interview_data()

# Ensure .env file exists
if not os.path.exists(".env"):
    logger.info("Creating .env file")
    try:
        from create_env import create_env_file
        create_env_file()
    except ImportError:
        # If create_env.py doesn't have a function, run it as a script
        logger.info("Running create_env.py script")
        exec(open("create_env.py").read())

# Load environment
from dotenv import load_dotenv
load_dotenv()

# Check critical environment variables
required_vars = ["OPENAI_API_KEY", "DEEPGRAM_API_KEY"]
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    logger.error("Please set them in the .env file and restart the application")
    sys.exit(1)

# Get host and port from environment
host = os.getenv("HOST", "0.0.0.0")
port = int(os.getenv("PORT", 8000))

if __name__ == "__main__":
    logger.info(f"Starting Virtual Interviewer API on {host}:{port}")
    
    try:
        import uvicorn
        uvicorn.run("app.main:app", host=host, port=port, reload=True)
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")
        sys.exit(1) 