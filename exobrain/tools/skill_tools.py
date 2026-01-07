"""Skill management tools for agent."""

import logging
from typing import Any

from exobrain.tools.base import Tool, ToolParameter

logger = logging.getLogger(__name__)


class GetSkillTool(Tool):
    """Tool for getting detailed instructions for a specific skill."""

    def __init__(self, skills_manager: Any):
        """Initialize GetSkillTool.

        Args:
            skills_manager: SkillsManager instance
        """
        super().__init__(
            name="get_skill",
            description=(
                "Get detailed instructions for a specific skill by name. "
                "Use this when you need to know how to accomplish a task using a skill. "
                "The skill will provide comprehensive instructions, code examples, and best practices."
            ),
            parameters={
                "skill_name": ToolParameter(
                    type="string",
                    description="The exact name of the skill to retrieve (e.g., 'slack-gif-creator', 'web-artifacts-builder')",
                    required=True,
                )
            },
        )

        # Set skills_manager after super().__init__()
        self.skills_manager = skills_manager

    async def execute(self, **kwargs: Any) -> str:
        """Execute the get_skill tool.

        Args:
            **kwargs: Tool parameters including 'skill_name'

        Returns:
            Detailed skill instructions or error message
        """
        skill_name = kwargs.get("skill_name", "").strip()

        if not skill_name:
            return "Error: skill_name parameter is required"

        # Get the skill
        skill = self.skills_manager.get_skill(skill_name)

        if not skill:
            available = ", ".join(self.skills_manager.list_skills())
            return (
                f"Error: Skill '{skill_name}' not found.\n\n"
                f"Available skills: {available}\n\n"
                f"Tip: Use the 'list_skills' or 'search_skills' tool to find the right skill."
            )

        # Build detailed response
        result = [
            f"# Skill: {skill.name}\n",
            f"**Description**: {skill.description}\n\n",
            "---\n\n",
            skill.instructions,
        ]

        logger.debug(f"Retrieved skill: {skill_name}")
        return "".join(result)


class SearchSkillsTool(Tool):
    """Tool for searching skills by query."""

    def __init__(self, skills_manager: Any):
        """Initialize SearchSkillsTool.

        Args:
            skills_manager: SkillsManager instance
        """
        super().__init__(
            name="search_skills",
            description=(
                "Search for skills relevant to a query. Returns a list of matching skills "
                "with their descriptions. Use this when you're not sure which skill to use, "
                "or want to find skills related to a topic."
            ),
            parameters={
                "query": ToolParameter(
                    type="string",
                    description="Search query (e.g., 'create gif', 'web design', 'document editing')",
                    required=True,
                ),
                "max_results": ToolParameter(
                    type="integer",
                    description="Maximum number of results to return (default: 5)",
                    required=False,
                ),
            },
        )

        # Set skills_manager after super().__init__()
        self.skills_manager = skills_manager

    async def execute(self, **kwargs: Any) -> str:
        """Execute the search_skills tool.

        Args:
            **kwargs: Tool parameters including 'query' and optional 'max_results'

        Returns:
            List of matching skills or error message
        """
        query = kwargs.get("query", "").strip()
        max_results = kwargs.get("max_results", 5)

        if not query:
            return "Error: query parameter is required"

        # Search for skills
        selected_skills = self.skills_manager.select_skills_for_query(query, max_skills=max_results)

        if not selected_skills:
            return (
                f"No skills found matching '{query}'.\n\n"
                f"Tip: Use 'list_skills' to see all available skills."
            )

        # Build response
        result = [f"Found {len(selected_skills)} skill(s) matching '{query}':\n\n"]

        for i, skill in enumerate(selected_skills, 1):
            result.append(f"{i}. **{skill.name}**\n")
            result.append(f"   {skill.description}\n\n")

        result.append(
            '\nTo get detailed instructions for a skill, use: get_skill(skill_name="skill-name")'
        )

        logger.debug(f"Searched skills with query '{query}', found {len(selected_skills)} results")
        return "".join(result)


class ListSkillsTool(Tool):
    """Tool for listing all available skills."""

    def __init__(self, skills_manager: Any):
        """Initialize ListSkillsTool.

        Args:
            skills_manager: SkillsManager instance
        """
        super().__init__(
            name="list_skills",
            description=(
                "List all available skills with their names and descriptions. "
                "Use this to see what skills are available, or to find the exact name "
                "of a skill you want to use."
            ),
            parameters={},
        )

        # Set skills_manager after super().__init__()
        self.skills_manager = skills_manager

    async def execute(self, **kwargs: Any) -> str:
        """Execute the list_skills tool.

        Args:
            **kwargs: Tool parameters (none required for this tool)

        Returns:
            List of all available skills
        """
        # No parameters needed for this tool
        skills = self.skills_manager.skills

        if not skills:
            return "No skills are currently loaded."

        # Build response
        result = [f"Available Skills ({len(skills)} total):\n\n"]

        # Sort by name for consistent output
        sorted_skills = sorted(skills.items(), key=lambda x: x[0])

        for skill_name, skill in sorted_skills:
            result.append(f"• **{skill_name}**\n")
            result.append(f"  {skill.description}\n\n")

        result.append(
            '\nTo get detailed instructions for a skill, use: get_skill(skill_name="skill-name")\n'
            'To search for specific skills, use: search_skills(query="your search")'
        )

        logger.debug(f"Listed {len(skills)} skills")
        return "".join(result)
