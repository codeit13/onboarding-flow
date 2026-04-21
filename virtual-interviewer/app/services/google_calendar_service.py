import base64
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
import requests

load_dotenv()

logger = logging.getLogger("google-calendar-service")


class GoogleCalendarService:
    def __init__(self):
        self.client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip().strip("'\"")
        self.client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip().strip("'\"")
        self.redirect_uri = os.getenv(
            "GOOGLE_OAUTH_REDIRECT_URI",
            "http://localhost:8000/api/interview/google-auth/callback",
        ).strip().strip("'\"")
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "").strip().strip("'\"")
        self.timezone = os.getenv("INTERVIEWER_TIMEZONE", "Asia/Kolkata")
        self.duration_minutes = int(os.getenv("MEET_DURATION_MINUTES", "60"))
        self.interviewer_email = os.getenv("INTERVIEWER_EMAIL", "").strip().strip("'\"")
        self.token_path = os.getenv(
            "GOOGLE_OAUTH_TOKEN_PATH",
            os.path.join(os.getcwd(), "interview_data", "google_oauth_token.json"),
        ).strip().strip("'\"")
        self.scopes = ["https://www.googleapis.com/auth/calendar"]

    def _client_config(self) -> Dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Google OAuth client credentials are missing. "
                "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env."
            )

        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.redirect_uri],
            }
        }

    def _encode_state(self, payload: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

    def _decode_state(self, value: Optional[str]) -> Dict[str, Any]:
        if not value:
            return {}
        try:
            padded = value + "=" * (-len(value) % 4)
            return json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
        except Exception:
            return {}

    def _load_token_info(self) -> Optional[Dict[str, Any]]:
        try:
            with open(self.token_path, "r", encoding="utf-8") as token_file:
                token_info = json.load(token_file)
                token_info.setdefault("client_id", self.client_id)
                token_info.setdefault("client_secret", self.client_secret)
                token_info.setdefault("token_uri", "https://oauth2.googleapis.com/token")
                token_info.setdefault("scopes", self.scopes)
                return token_info
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.error(f"Failed to load Google OAuth token: {exc}")
            return None

    def _save_token_info(self, token_info: Dict[str, Any]) -> None:
        enriched_token_info = {
            **token_info,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": self.scopes,
        }
        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
        with open(self.token_path, "w", encoding="utf-8") as token_file:
            json.dump(enriched_token_info, token_file, indent=2)

    def is_authorized(self) -> bool:
        return self._load_token_info() is not None

    def get_authorization_url(self, return_url: Optional[str] = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": self._encode_state({"return_url": return_url}),
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    def exchange_code(self, code: str, state: Optional[str] = None) -> Dict[str, Any]:
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        token_response.raise_for_status()
        token_info = token_response.json()
        self._save_token_info(token_info)
        logger.info(f"Google OAuth token saved to {self.token_path}")
        return token_info

    def get_callback_redirect(self, state: Optional[str], error: Optional[str] = None) -> str:
        payload = self._decode_state(state)
        return_url = payload.get("return_url") or "http://localhost:3000/virtual-interviewer"
        separator = "&" if "?" in return_url else "?"
        if error:
            return f"{return_url}{separator}google_auth=error&message={quote(error)}"
        return f"{return_url}{separator}google_auth=success"

    def _build_service(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_info = self._load_token_info()
        if not token_info:
            raise ValueError(
                "Google Calendar OAuth is not connected. "
                "Complete the Google sign-in flow before scheduling a Meet."
            )

        credentials = Credentials.from_authorized_user_info(token_info, self.scopes)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self._save_token_info(json.loads(credentials.to_json()))

        if not credentials.valid:
            raise ValueError(
                "Google Calendar OAuth token is invalid. Reconnect Google Calendar and try again."
            )

        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    def get_status(self) -> Dict[str, Any]:
        token_info = self._load_token_info()
        return {
            "connected": token_info is not None,
            "calendar_id": self.calendar_id,
            "interviewer_email": self.interviewer_email,
        }

    def create_interview_event(
        self,
        candidate_name: str,
        candidate_email: str,
        start_datetime: datetime,
    ) -> dict:
        try:
            service = self._build_service()
            end_datetime = start_datetime + timedelta(minutes=self.duration_minutes)

            calendar_id = self.calendar_id or "primary"
            event_body = {
                "summary": f"2nd Round Interview – {candidate_name}",
                "description": (
                    f"2nd Round Interview\n"
                    f"Candidate: {candidate_name} ({candidate_email})\n\n"
                    f"This meeting has been automatically scheduled based on "
                    f"the candidate's preferred time slot."
                ),
                "start": {
                    "dateTime": start_datetime.isoformat(),
                    "timeZone": self.timezone,
                },
                "end": {
                    "dateTime": end_datetime.isoformat(),
                    "timeZone": self.timezone,
                },
                "attendees": [
                    {"email": candidate_email, "displayName": candidate_name},
                ],
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"xchat-{candidate_email}-{int(start_datetime.timestamp())}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "email", "minutes": 60},
                        {"method": "popup", "minutes": 15},
                    ],
                },
                "guestsCanModifyEvent": False,
            }

            if self.interviewer_email:
                event_body["attendees"].append(
                    {"email": self.interviewer_email, "displayName": "Interviewer"}
                )

            created = service.events().insert(
                calendarId=calendar_id,
                body=event_body,
                conferenceDataVersion=1,
                sendUpdates="all",
            ).execute()

            meet_link = created.get("hangoutLink", "")
            event_link = created.get("htmlLink", "")

            logger.info(
                f"Google Meet event created for {candidate_name} "
                f"at {start_datetime.isoformat()} | meet: {meet_link}"
            )

            return {
                "success": True,
                "meet_link": meet_link,
                "event_link": event_link,
                "start": start_datetime.isoformat(),
                "end": end_datetime.isoformat(),
            }

        except Exception as exc:
            logger.error(f"Failed to create Google Meet event: {exc}")
            return {"success": False, "error": str(exc), "meet_link": ""}
