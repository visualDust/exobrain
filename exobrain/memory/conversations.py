"""Conversation management for ExoBrain."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from exobrain.memory.storage import ConversationStorage
from exobrain.providers.base import Message

logger = logging.getLogger(__name__)


class ConversationManager:
    """Manage conversation sessions (create, load, save, delete)."""

    def __init__(
        self,
        storage_path: Path,
        model_provider: Any,
        save_tool_history: bool = True,
        tool_content_max_length: int = 1000,
    ):
        """Initialize conversation manager.

        Args:
            storage_path: Root path for conversation storage
            model_provider: Model provider for token counting
            save_tool_history: Whether to save tool messages to conversation history
            tool_content_max_length: Maximum length of tool message content to save
        """
        self.storage = ConversationStorage(storage_path)
        self.model_provider = model_provider
        self.sessions_index = self.storage.load_sessions_index()
        self.save_tool_history = save_tool_history
        self.tool_content_max_length = tool_content_max_length

    def create_session(self, model: str, title: str | None = None) -> str:
        """Create a new conversation session.

        Args:
            model: Model identifier
            title: Optional session title (auto-generated if None)

        Returns:
            Session ID
        """
        # Generate session ID from timestamp
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Create session directory
        self.storage.create_session_directory(session_id)

        # Create metadata
        metadata = {
            "id": session_id,
            "title": title or "New conversation",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "message_count": 0,
            "total_tokens": 0,
            "model": model,
        }

        # Save metadata
        self.storage.save_session_metadata(session_id, metadata)

        # Add to index
        self.sessions_index["sessions"].append(
            {
                "id": session_id,
                "title": metadata["title"],
                "created_at": metadata["created_at"],
                "message_count": 0,
                "last_activity": metadata["created_at"],
            }
        )
        self.sessions_index["current_session"] = session_id
        self.storage.save_sessions_index(self.sessions_index)

        logger.debug(f"Created new session: {session_id}")
        return session_id

    def load_session(self, session_id: str, token_budget: int | None = None) -> dict[str, Any]:
        """Load a conversation session.

        Args:
            session_id: Session identifier
            token_budget: Maximum tokens to load (None = load all)

        Returns:
            Dict with 'messages', 'metadata', and loading stats
        """
        if not self.storage.session_exists(session_id):
            raise ValueError(f"Session not found: {session_id}")

        # Load metadata
        metadata = self.storage.load_session_metadata(session_id)
        if not metadata:
            raise ValueError(f"Session metadata not found: {session_id}")

        # Load messages
        all_messages = self.storage.load_all_messages(session_id)

        # Apply token budget if specified
        if token_budget is not None and all_messages:
            result = self._load_within_budget(all_messages, token_budget)
            loaded_messages = result["messages"]
            load_stats = {
                "loaded_count": result["loaded_count"],
                "loaded_tokens": result["loaded_tokens"],
                "truncated_count": result["truncated_count"],
                "total_count": result["total_count"],
            }
        else:
            loaded_messages = all_messages
            total_tokens = sum(msg.get("tokens", 0) for msg in all_messages)
            load_stats = {
                "loaded_count": len(all_messages),
                "loaded_tokens": total_tokens,
                "truncated_count": 0,
                "total_count": len(all_messages),
            }

        logger.debug(
            f"Loaded session {session_id}: {load_stats['loaded_count']} messages "
            f"({load_stats['loaded_tokens']} tokens)"
        )

        return {
            "messages": loaded_messages,
            "metadata": metadata,
            "stats": load_stats,
        }

    def _load_within_budget(self, all_messages: list[dict], token_budget: int) -> dict[str, Any]:
        """Load messages within token budget, starting from most recent.

        Args:
            all_messages: All available messages
            token_budget: Maximum tokens to load

        Returns:
            Dict with loaded messages and statistics
        """
        # Reverse to start from most recent
        messages_reversed = list(reversed(all_messages))

        loaded = []
        total_tokens = 0

        for msg in messages_reversed:
            msg_tokens = msg.get("tokens", 0)
            if msg_tokens == 0:
                # Estimate if not recorded
                msg_tokens = self.model_provider.count_tokens(msg.get("content", ""))

            if total_tokens + msg_tokens > token_budget:
                # Would exceed budget, stop loading
                break

            loaded.append(msg)
            total_tokens += msg_tokens

        # Reverse back to chronological order
        loaded.reverse()

        return {
            "messages": loaded,
            "loaded_count": len(loaded),
            "loaded_tokens": total_tokens,
            "truncated_count": len(all_messages) - len(loaded),
            "total_count": len(all_messages),
        }

    def save_message(self, session_id: str, message: Message) -> None:
        """Save a message to a session.

        Args:
            session_id: Session identifier
            message: Message to save
        """
        # Skip tool messages if save_tool_history is disabled
        if message.role == "tool" and not self.save_tool_history:
            logger.debug(f"Skipping tool message (save_tool_history=False): {message.name}")
            return

        # Prepare content with truncation for tool messages
        content = message.content
        if message.role == "tool" and isinstance(content, str):
            if len(content) > self.tool_content_max_length:
                content = content[: self.tool_content_max_length] + "... [truncated]"
                logger.debug(
                    f"Truncated tool message content from {len(message.content)} to {self.tool_content_max_length} chars"
                )

        # Count tokens
        tokens = self.model_provider.count_tokens(content if isinstance(content, str) else "")

        # Use message timestamp if available, otherwise use current time
        timestamp = message.timestamp if message.timestamp else datetime.now().isoformat()

        # Prepare message data
        message_data = {
            "role": message.role,
            "content": content,
            "timestamp": timestamp,
            "tokens": tokens,
        }

        # Add optional fields
        if message.name:
            message_data["name"] = message.name
        if message.tool_calls:
            message_data["tool_calls"] = message.tool_calls
        if message.tool_call_id:
            message_data["tool_call_id"] = message.tool_call_id

        # Append to messages file
        self.storage.append_message(session_id, message_data)

        # Update metadata
        metadata = self.storage.load_session_metadata(session_id)
        if metadata:
            metadata["message_count"] += 1
            metadata["total_tokens"] += tokens
            metadata["updated_at"] = datetime.now().isoformat()
            self.storage.save_session_metadata(session_id, metadata)

            # Update index
            self._update_session_in_index(session_id, metadata)

    def _update_session_in_index(self, session_id: str, metadata: dict[str, Any]) -> None:
        """Update session info in the index.

        Args:
            session_id: Session identifier
            metadata: Updated metadata
        """
        for session in self.sessions_index["sessions"]:
            if session["id"] == session_id:
                session["message_count"] = metadata["message_count"]
                session["last_activity"] = metadata["updated_at"]
                break

        self.storage.save_sessions_index(self.sessions_index)

    def list_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent sessions.

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of session info dicts, sorted by last activity
        """
        sessions = self.sessions_index.get("sessions", [])

        # Sort by last activity (most recent first)
        sorted_sessions = sorted(sessions, key=lambda s: s.get("last_activity", ""), reverse=True)

        return sorted_sessions[:limit]

    def get_session_metadata(self, session_id: str) -> dict[str, Any] | None:
        """Get metadata for a specific session.

        Args:
            session_id: Session identifier

        Returns:
            Metadata dict or None if not found
        """
        return self.storage.load_session_metadata(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if successful
        """
        # Delete from storage
        if not self.storage.delete_session(session_id):
            return False

        # Remove from index
        self.sessions_index["sessions"] = [
            s for s in self.sessions_index["sessions"] if s["id"] != session_id
        ]

        # Update current session if deleted
        if self.sessions_index.get("current_session") == session_id:
            self.sessions_index["current_session"] = None

        self.storage.save_sessions_index(self.sessions_index)

        return True

    def get_current_session(self) -> str | None:
        """Get current active session ID.

        Returns:
            Session ID or None
        """
        return self.sessions_index.get("current_session")

    def set_current_session(self, session_id: str) -> None:
        """Set current active session.

        Args:
            session_id: Session identifier
        """
        if not self.storage.session_exists(session_id):
            raise ValueError(f"Session not found: {session_id}")

        self.sessions_index["current_session"] = session_id
        self.storage.save_sessions_index(self.sessions_index)

    def auto_generate_title(self, session_id: str, first_user_message: str) -> None:
        """Auto-generate session title from first user message.

        Args:
            session_id: Session identifier
            first_user_message: First user message content
        """
        # Simple title generation: first 50 chars of message
        title = first_user_message[:50].strip()
        if len(first_user_message) > 50:
            title += "..."

        # Update metadata
        metadata = self.storage.load_session_metadata(session_id)
        if metadata and metadata.get("title") == "New conversation":
            metadata["title"] = title
            self.storage.save_session_metadata(session_id, metadata)

            # Update index
            for session in self.sessions_index["sessions"]:
                if session["id"] == session_id:
                    session["title"] = title
                    break

            self.storage.save_sessions_index(self.sessions_index)
            logger.debug(f"Auto-generated title for {session_id}: {title}")
