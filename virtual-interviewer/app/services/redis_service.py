import redis
import json
import os
from typing import Dict, Any, Optional, List
import logging
import certifi

logger = logging.getLogger(__name__)

class RedisService:
    def __init__(self):
        # When running the service standalone (e.g. `docker run ...`) Redis may
        # not be available. We fall back to an in-memory session store so the
        # API can still start for local/dev usage.
        self.redis_client: Optional[redis.Redis] = None
        self._memory_sessions: Dict[str, Dict[str, Any]] = {}
        try:
            redis_host = os.getenv("REDIS_HOST")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_password = os.getenv("REDIS_PASSWORD") or None
            redis_ssl = os.getenv("REDIS_SSL", "false").lower() in {"1", "true", "yes"}

            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                ssl=redis_ssl,
                ssl_cert_reqs=("required" if redis_ssl else None),
                ssl_ca_certs=(certifi.where() if redis_ssl else None),
                decode_responses=True
            )
            # Test the connection
            self.redis_client.ping()
            logger.info("Successfully connected to Redis at %s:%s", 
                       redis_host,
                       redis_port)
        except redis.ConnectionError as e:
            # Don't crash the whole API if Redis is down/misconfigured.
            # We'll operate in memory for this process lifetime.
            logger.error("Failed to connect to Redis (falling back to in-memory sessions): %s", str(e))
            self.redis_client = None
        except Exception as e:
            logger.error("Unexpected error connecting to Redis (falling back to in-memory sessions): %s", str(e))
            self.redis_client = None

    def verify_connection(self) -> bool:
        """Verify Redis connection is still active"""
        try:
            if self.redis_client is None:
                return False
            self.redis_client.ping()
            logger.info("Redis connection is active")
            return True
        except Exception as e:
            logger.error("Redis connection is not active: %s", str(e))
            return False

    def get_all_sessions(self) -> List[str]:
        """Get all active session IDs"""
        try:
            if not self.verify_connection():
                return list(self._memory_sessions.keys())
            # Get all keys matching the session pattern
            session_keys = self.redis_client.keys("session:*")
            # Remove the 'session:' prefix from each key
            sessions = [key.replace("session:", "") for key in session_keys]
            logger.info(f"Retrieved {len(sessions)} active sessions from Redis")
            return sessions
        except Exception as e:
            logger.error(f"Error getting all sessions from Redis: {str(e)}")
            return []

    def get_history(self, interview_id: str) -> List[Dict[str, Any]]:
        """Get session history"""
        try:
            session = self.get_session(interview_id)
            if session and 'history' in session:
                logger.info(f"Retrieved history for session {interview_id} with {len(session['history'])} items")
                return session['history']
            return []
        except Exception as e:
            logger.error(f"Error getting history from Redis: {str(e)}")
            return []

    def trim_history(self, interview_id: str, max_items: int = 10) -> bool:
        """Trim session history to specified number of items"""
        try:
            session = self.get_session(interview_id)
            if session and 'history' in session:
                old_length = len(session['history'])
                session['history'] = session['history'][-max_items:]
                logger.info(f"Trimmed history for session {interview_id} from {old_length} to {len(session['history'])} items")
                return self.set_session(interview_id, session)
            return False
        except Exception as e:
            logger.error(f"Error trimming history in Redis: {str(e)}")
            return False

    def set_session(self, interview_id: str, session_data: Dict[str, Any], expiry: int = 3600) -> bool:
        """Store session data in Redis with expiry"""
        try:
            if not self.verify_connection():
                self._memory_sessions[interview_id] = session_data
                return True
            success = self.redis_client.setex(
                f"session:{interview_id}",
                expiry,
                json.dumps(session_data)
            )
            if success:
                logger.info(f"Successfully created/updated session {interview_id} with expiry {expiry}s")
            else:
                logger.error(f"Failed to create/update session {interview_id}")
            return success
        except Exception as e:
            logger.error(f"Error setting session in Redis: {str(e)}")
            return False

    def get_session(self, interview_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data from Redis"""
        try:
            if not self.verify_connection():
                return self._memory_sessions.get(interview_id)
            data = self.redis_client.get(f"session:{interview_id}")
            if data:
                logger.info(f"Successfully retrieved session {interview_id}")
                return json.loads(data)
            logger.info(f"No session found for {interview_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting session from Redis: {str(e)}")
            return None

    def delete_session(self, interview_id: str) -> bool:
        """Delete session data from Redis"""
        try:
            if not self.verify_connection():
                self._memory_sessions.pop(interview_id, None)
                return True
            # Check if session exists before deletion
            exists = self.redis_client.exists(f"session:{interview_id}")
            if exists:
                success = bool(self.redis_client.delete(f"session:{interview_id}"))
                if success:
                    logger.info(f"Successfully deleted session {interview_id}")
                else:
                    logger.error(f"Failed to delete session {interview_id}")
                return success
            else:
                logger.info(f"Session {interview_id} not found for deletion")
                return True
        except Exception as e:
            logger.error(f"Error deleting session from Redis: {str(e)}")
            return False

    def update_session_state(self, interview_id: str, state_data: Dict[str, Any]) -> bool:
        """Update specific state data in session"""
        try:
            session = self.get_session(interview_id)
            if session:
                session['current_state'] = state_data
                success = self.set_session(interview_id, session)
                if success:
                    logger.info(f"Successfully updated state for session {interview_id}")
                return success
            logger.warning(f"Cannot update state - session {interview_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error updating session state in Redis: {str(e)}")
            return False

    def append_to_history(self, interview_id: str, history_item: Dict[str, Any]) -> bool:
        """Append item to session history"""
        try:
            session = self.get_session(interview_id)
            if session:
                if 'history' not in session:
                    session['history'] = []
                session['history'].append(history_item)
                # Keep only last 10 items
                old_length = len(session['history'])
                session['history'] = session['history'][-10:]
                success = self.set_session(interview_id, session)
                if success:
                    logger.info(f"Successfully appended to history for session {interview_id} (length: {len(session['history'])})")
                return success
            logger.warning(f"Cannot append to history - session {interview_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error appending to session history in Redis: {str(e)}")
            return False 