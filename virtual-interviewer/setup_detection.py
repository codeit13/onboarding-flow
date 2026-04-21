"""
Detection System Setup Script
This script checks and installs dependencies required for the detection system.
"""
import os
import sys
import subprocess
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("setup_detection")

def check_pip():
    """Check if pip is installed and working"""
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', '--version'], 
                             stdout=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def install_dependencies():
    """Install all required dependencies"""
    logger.info("Installing detection system dependencies...")
    
    # Read requirements from requirements.txt
    try:
        with open('requirements.txt', 'r') as f:
            requirements = f.read().splitlines()
    except FileNotFoundError:
        logger.error("requirements.txt not found!")
        return False
    
    # Install each dependency
    success = True
    for req in requirements:
        if not req or req.startswith('#'):
            continue
            
        logger.info(f"Installing {req}...")
        try:
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install', req,
                '--no-cache-dir'
            ], stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            logger.error(f"Failed to install {req}")
            success = False
    
    return success

def validate_environment():
    """Validate that key dependencies are importable"""
    logger.info("Validating detection system environment...")
    
    # Test imports for key modules
    dependencies = [
        'cv2',
        'mediapipe',
        'numpy',
        'base64',
        'fastapi'
    ]
    
    all_passed = True
    for dep in dependencies:
        try:
            if dep == 'cv2':
                import cv2
                logger.info(f"✓ OpenCV version: {cv2.__version__}")
            elif dep == 'mediapipe':
                import mediapipe
                logger.info(f"✓ MediaPipe imported successfully")
            elif dep == 'numpy':
                import numpy
                logger.info(f"✓ NumPy version: {numpy.__version__}")
            elif dep == 'base64':
                import base64
                logger.info(f"✓ base64 imported successfully")
            elif dep == 'fastapi':
                import fastapi
                logger.info(f"✓ FastAPI version: {fastapi.__version__}")
        except ImportError:
            logger.error(f"✗ Failed to import {dep}")
            all_passed = False
    
    return all_passed

def create_test_environment():
    """Create directories needed for the detection system"""
    os.makedirs('logs', exist_ok=True)
    logger.info("Created logs directory for detection system")

def main():
    logger.info("Starting detection system setup...")
    
    # Check pip installation
    if not check_pip():
        logger.error("pip is not installed or not working correctly!")
        return False
    
    # Install dependencies
    if not install_dependencies():
        logger.error("Failed to install all dependencies!")
        return False
    
    # Validate environment
    if not validate_environment():
        logger.warning("Some dependencies failed to import!")
    
    # Create necessary directories 
    create_test_environment()
    
    logger.info("Detection system setup completed successfully!")
    return True

if __name__ == "__main__":
    successful = main()
    if not successful:
        logger.error("Setup failed!")
        sys.exit(1)
    sys.exit(0) 