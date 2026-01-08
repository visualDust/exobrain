"""Skills loader for ExoBrain."""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Skill(BaseModel):
    """Skill model."""

    name: str
    description: str
    instructions: str
    license: Optional[str] = None
    metadata: Dict[str, Any] = {}
    source_path: Optional[Path] = None


class SkillLoader:
    """Loader for Agent Skills in SKILL.md format."""

    def __init__(self, skill_paths: List[str | Path]):
        """Initialize skill loader.

        Args:
            skill_paths: List of paths to search for skills
        """
        self.skill_paths = [Path(p).expanduser() for p in skill_paths]
        self.skills: Dict[str, Skill] = {}

    def load_all_skills(self) -> Dict[str, Skill]:
        """Load all skills from configured paths.

        Returns:
            Dictionary of skill name to Skill object
        """
        for skill_path in self.skill_paths:
            if not skill_path.exists():
                logger.warning(f"Skill path does not exist: {skill_path}")
                continue

            logger.info(f"Loading skills from: {skill_path}")
            self._load_skills_from_directory(skill_path)

        logger.info(f"Loaded {len(self.skills)} skills")
        return self.skills

    def _load_skills_from_directory(self, directory: Path) -> None:
        """Load skills from a directory.

        Args:
            directory: Directory to search for SKILL.md files
        """
        # Find all SKILL.md files
        skill_files = list(directory.rglob("SKILL.md"))

        for skill_file in skill_files:
            try:
                skill = self._load_skill_file(skill_file)
                if skill:
                    self.skills[skill.name] = skill
                    logger.debug(f"Loaded skill: {skill.name}")
            except Exception as e:
                logger.error(f"Error loading skill from {skill_file}: {e}")

    def _load_skill_file(self, skill_file: Path) -> Optional[Skill]:
        """Load a single SKILL.md file.

        Args:
            skill_file: Path to SKILL.md file

        Returns:
            Skill object or None if invalid
        """
        with open(skill_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse YAML frontmatter
        frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)

        if not frontmatter_match:
            logger.warning(f"No frontmatter found in {skill_file}")
            return None

        frontmatter_str = frontmatter_match.group(1)
        instructions = frontmatter_match.group(2).strip()

        try:
            frontmatter = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML frontmatter in {skill_file}: {e}")
            return None

        # Validate required fields
        if "name" not in frontmatter:
            logger.error(f"Missing 'name' field in {skill_file}")
            return None

        if "description" not in frontmatter:
            logger.error(f"Missing 'description' field in {skill_file}")
            return None

        # Create skill object
        skill = Skill(
            name=frontmatter["name"],
            description=frontmatter["description"],
            instructions=instructions,
            license=frontmatter.get("license"),
            metadata=frontmatter,
            source_path=skill_file,
        )

        return skill

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name.

        Args:
            name: Skill name

        Returns:
            Skill object or None if not found
        """
        return self.skills.get(name)

    def list_skills(self) -> List[str]:
        """List all loaded skill names.

        Returns:
            List of skill names
        """
        return list(self.skills.keys())

    def search_skills(self, query: str) -> List[Skill]:
        """Search skills by name or description.

        Args:
            query: Search query

        Returns:
            List of matching skills
        """
        query_lower = query.lower()
        results = []

        for skill in self.skills.values():
            if query_lower in skill.name.lower() or query_lower in skill.description.lower():
                results.append(skill)

        return results


def load_default_skills(config: Any) -> SkillLoader:
    """Load skills from default locations.

    Skills loading priority (lowest to highest):
    1. Builtin skills (submodules) - exobrain/skills/{anthropic,obsidian}/
    2. Configured skills directory - from config.skills.skills_dir
    3. User global skills - ~/.exobrain/skills
    4. Project-level skills - ./.exobrain/skills (highest priority)

    Args:
        config: Application configuration

    Returns:
        SkillLoader with loaded skills
    """
    skill_paths = []

    # 1. Add builtin skills (from submodules) - lowest priority
    # Add Anthropic skills
    anthropic_skills_path = Path(__file__).parent / "anthropic" / "skills"
    if anthropic_skills_path.exists():
        skill_paths.append(anthropic_skills_path)
        logger.debug(f"Added Anthropic skills path: {anthropic_skills_path}")

    # Add Obsidian skills
    obsidian_skills_path = Path(__file__).parent / "obsidian"
    if obsidian_skills_path.exists():
        skill_paths.append(obsidian_skills_path)
        logger.debug(f"Added Obsidian skills path: {obsidian_skills_path}")

    # 2. Add configured skills directory (if specified in config)
    if hasattr(config, "skills") and hasattr(config.skills, "skills_dir"):
        configured_path = Path(config.skills.skills_dir).expanduser()
        if configured_path.exists():
            skill_paths.append(configured_path)
            logger.debug(f"Added configured skills path: {configured_path}")

    # 3. Add user global skills
    user_skills_path = Path.home() / ".exobrain" / "skills"
    if user_skills_path.exists():
        skill_paths.append(user_skills_path)
        logger.debug(f"Added user global skills path: {user_skills_path}")

    # 4. Add project-level skills - highest priority
    project_skills_path = Path.cwd() / ".exobrain" / "skills"
    if project_skills_path.exists():
        skill_paths.append(project_skills_path)
        logger.info(f"Found project-level skills at: {project_skills_path}")

    if skill_paths:
        logger.info(
            f"Skills loading priority (low to high): "
            f"{' > '.join(str(p.name) if p.name != 'skills' else str(p.parent.name) + '/skills' for p in skill_paths)}"
        )

    loader = SkillLoader(skill_paths)
    loader.load_all_skills()

    return loader
