"""Storage utilities for conversation persistence."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ConversationStorage:
    """Handle file I/O for conversation data."""

    def __init__(self, storage_path: Path):
        """Initialize storage.

        Args:
            storage_path: Root path for conversation storage
        """
        self.storage_path = Path(storage_path)
        self.sessions_dir = self.storage_path / "sessions"
        self.index_file = self.storage_path / "sessions.json"

        # Ensure directories exist
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def load_sessions_index(self) -> dict[str, Any]:
        """Load sessions index file.

        Returns:
            Sessions index data, or empty structure if not exists
        """
        if not self.index_file.exists():
            return {"current_session": None, "sessions": []}

        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load sessions index: {e}")
            return {"current_session": None, "sessions": []}

    def save_sessions_index(self, index_data: dict[str, Any]) -> None:
        """Save sessions index file.

        Args:
            index_data: Sessions index data to save
        """
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save sessions index: {e}")

    def create_session_directory(self, session_id: str) -> Path:
        """Create directory for a new session.

        Args:
            session_id: Session identifier

        Returns:
            Path to the created session directory
        """
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def get_session_directory(self, session_id: str) -> Path:
        """Get path to session directory.

        Args:
            session_id: Session identifier

        Returns:
            Path to session directory
        """
        return self.sessions_dir / session_id

    def session_exists(self, session_id: str) -> bool:
        """Check if a session exists.

        Args:
            session_id: Session identifier

        Returns:
            True if session directory exists
        """
        return self.get_session_directory(session_id).exists()

    def load_session_metadata(self, session_id: str) -> dict[str, Any] | None:
        """Load session metadata.

        Args:
            session_id: Session identifier

        Returns:
            Metadata dict or None if not found
        """
        metadata_file = self.get_session_directory(session_id) / "metadata.json"
        if not metadata_file.exists():
            return None

        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load metadata for {session_id}: {e}")
            return None

    def save_session_metadata(self, session_id: str, metadata: dict[str, Any]) -> None:
        """Save session metadata.

        Args:
            session_id: Session identifier
            metadata: Metadata to save
        """
        metadata_file = self.get_session_directory(session_id) / "metadata.json"

        try:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save metadata for {session_id}: {e}")

    def append_message(self, session_id: str, message_data: dict[str, Any]) -> None:
        """Append a message to session's messages file.

        Args:
            session_id: Session identifier
            message_data: Message data to append
        """
        messages_file = self.get_session_directory(session_id) / "messages.jsonl"

        try:
            with open(messages_file, "a", encoding="utf-8") as f:
                json.dump(message_data, f, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            logger.error(f"Failed to append message to {session_id}: {e}")

    def load_all_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Load all messages from a session.

        Args:
            session_id: Session identifier

        Returns:
            List of message dicts
        """
        messages_file = self.get_session_directory(session_id) / "messages.jsonl"
        if not messages_file.exists():
            return []

        messages = []
        try:
            with open(messages_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        messages.append(json.loads(line))
        except Exception as e:
            logger.error(f"Failed to load messages from {session_id}: {e}")

        return messages

    def delete_session(self, session_id: str) -> bool:
        """Delete a session directory.

        Args:
            session_id: Session identifier

        Returns:
            True if successful
        """
        session_dir = self.get_session_directory(session_id)
        if not session_dir.exists():
            return False

        try:
            import shutil

            shutil.rmtree(session_dir)
            logger.debug(f"Deleted session: {session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False
