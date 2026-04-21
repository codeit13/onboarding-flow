import os
import time
import requests
import json
import base64
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deepgram-service")

# Load environment variables
load_dotenv()

# Set Deepgram API key
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

class DeepgramService:
    """
    A synchronous service for interacting with Deepgram's API for transcription.
    This implementation uses direct HTTP requests instead of the async SDK.
    """
    
    def __init__(self):
        # Clear any proxy environment variables that might affect the client
        if 'HTTP_PROXY' in os.environ:
            del os.environ['HTTP_PROXY']
        if 'HTTPS_PROXY' in os.environ:
            del os.environ['HTTPS_PROXY']
            
        # Base URL for Deepgram API
        self.base_url = "https://api.deepgram.com/v1/listen"
        self.api_key = DEEPGRAM_API_KEY
        
        # Headers for API requests
        self.headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def transcribe_audio_bytes(self, audio_data):
        """Transcribe audio data using Deepgram API with retry + timeout."""
        params = {
            "model": "nova-2",
            "smart_format": "true",
            "detect_language": "true"
        }
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/wav"
        }

        last_error = None
        for attempt in range(3):
            try:
                if attempt > 0:
                    wait = 2 ** attempt  # 2s, 4s
                    logger.warning(f"Deepgram retry {attempt+1}/3 after {wait}s backoff")
                    time.sleep(wait)

                logger.info(f"Sending transcription request to Deepgram (attempt {attempt+1})")
                response = requests.post(
                    self.base_url,
                    params=params,
                    headers=headers,
                    data=audio_data,
                    timeout=30,
                )

                if response.status_code == 200:
                    result = response.json()
                    transcript = result["results"]["channels"][0]["alternatives"][0]["transcript"]
                    return {"success": True, "transcript": transcript}
                else:
                    last_error = f"API error: {response.status_code} - {response.text}"
                    logger.error(f"Deepgram API error (attempt {attempt+1}): {last_error}")
                    if response.status_code < 500:
                        break  # Don't retry client errors (4xx)

            except requests.exceptions.Timeout:
                last_error = "Deepgram request timed out after 30s"
                logger.warning(f"Deepgram timeout (attempt {attempt+1})")
            except requests.exceptions.ConnectionError as e:
                last_error = f"Deepgram connection error: {str(e)}"
                logger.warning(f"Deepgram connection error (attempt {attempt+1}): {e}")
            except Exception as e:
                last_error = f"Transcription error: {str(e)}"
                logger.exception(f"Unexpected error in transcription (attempt {attempt+1})")
                break  # Don't retry unknown errors

        return {"success": False, "error": last_error or "Transcription failed after retries"}
    
    def transcribe_base64_audio(self, base64_audio):
        """
        Transcribe base64 encoded audio data
        
        Args:
            base64_audio (str): Base64 encoded audio string
            
        Returns:
            dict: Result with success flag and transcript or error
        """
        try:
            # Decode base64 string to binary data
            if not base64_audio:
                return {"success": False, "error": "Empty audio data"}
                
            if "," in base64_audio:
                base64_data = base64_audio.split(",")[1]
            else:
                base64_data = base64_audio
                
            logger.info("Decoding base64 audio data")
            audio_data = base64.b64decode(base64_data)
            
            # Use the synchronous method to transcribe
            return self.transcribe_audio_bytes(audio_data)
            
        except Exception as e:
            logger.exception("Error in transcribe_base64_audio")
            return {"success": False, "error": f"Error processing audio: {str(e)}"}