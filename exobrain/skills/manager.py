"""Skills manager for selecting and applying skills to agents."""

import logging
from typing import List, Optional

from exobrain.skills.loader import Skill

logger = logging.getLogger(__name__)


class SkillsManager:
    """Manager for selecting and applying skills to agents."""

    def __init__(self, skills: dict[str, Skill]):
        """Initialize skills manager.

        Args:
            skills: Dictionary of skill name to Skill object
        """
        self.skills = skills

    def select_skills_for_query(self, query: str, max_skills: int = 3) -> List[Skill]:
        """Select relevant skills based on user query.

        Args:
            query: User's query or message
            max_skills: Maximum number of skills to select

        Returns:
            List of selected skills
        """
        query_lower = query.lower()
        scored_skills: List[tuple[Skill, float]] = []

        for skill in self.skills.values():
            score = self._score_skill_relevance(skill, query_lower)
            if score > 0:
                scored_skills.append((skill, score))

        # Sort by score descending
        scored_skills.sort(key=lambda x: x[1], reverse=True)

        # Return top skills
        selected = [skill for skill, score in scored_skills[:max_skills]]

        if selected:
            logger.info(
                f"Selected {len(selected)} skills for query: " f"{[s.name for s in selected]}"
            )

        return selected

    def _score_skill_relevance(self, skill: Skill, query_lower: str) -> float:
        """Score how relevant a skill is to the query.

        Args:
            skill: Skill to score
            query_lower: Lowercase query string

        Returns:
            Relevance score (0-1)
        """
        score = 0.0

        # Check skill name
        if skill.name.lower() in query_lower:
            score += 0.5

        # Check description keywords
        description_lower = skill.description.lower()
        description_words = set(description_lower.split())
        query_words = set(query_lower.split())

        # Calculate word overlap
        overlap = len(description_words & query_words)
        if overlap > 0:
            score += min(overlap * 0.1, 0.3)

        # Check for specific keywords in query
        keywords = self._extract_keywords(description_lower)
        for keyword in keywords:
            if keyword in query_lower:
                score += 0.2

        return min(score, 1.0)

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract important keywords from text.

        Args:
            text: Text to extract keywords from

        Returns:
            List of keywords
        """
        # Simple keyword extraction - look for quoted words or technical terms
        keywords = []

        # Common skill-related keywords
        common_keywords = [
            "pdf",
            "docx",
            "pptx",
            "xlsx",
            "excel",
            "word",
            "powerpoint",
            "mcp",
            "server",
            "api",
            "web",
            "frontend",
            "design",
            "art",
            "document",
            "spreadsheet",
            "presentation",
            "skill",
            "create",
            "build",
            "generate",
            "analyze",
            "test",
            "github",
            "slack",
            "brand",
            "communication",
            "internal",
            "coauthor",
        ]

        for keyword in common_keywords:
            if keyword in text:
                keywords.append(keyword)

        return keywords

    def build_skills_context(self, skills: List[Skill]) -> str:
        """Build context string from selected skills.

        Args:
            skills: List of skills to include

        Returns:
            Combined skills instructions
        """
        if not skills:
            return ""

        parts = ["\n# Available Skills\n"]
        parts.append(
            "You have access to the following specialized skills. "
            "Use them when the user's request matches the skill's description.\n"
        )

        for skill in skills:
            parts.append(f"\n## Skill: {skill.name}\n")
            parts.append(f"**Description**: {skill.description}\n")
            parts.append(f"\n{skill.instructions}\n")
            parts.append("\n---\n")

        return "".join(parts)

    def get_all_skills_summary(self) -> str:
        """Get a summary of all available skills.

        Returns:
            Summary string listing all skills
        """
        if not self.skills:
            return ""

        parts = ["\n# Available Skills Summary\n"]
        parts.append(
            "The following specialized skills are available. "
            "When you recognize a task that matches a skill's description, "
            "let me know and I'll provide detailed instructions.\n\n"
        )

        for skill in self.skills.values():
            parts.append(f"- **{skill.name}**: {skill.description}\n")

        return "".join(parts)

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a specific skill by name.

        Args:
            name: Skill name

        Returns:
            Skill object or None
        """
        return self.skills.get(name)

    def list_skills(self) -> List[str]:
        """List all skill names.

        Returns:
            List of skill names
        """
        return list(self.skills.keys())
