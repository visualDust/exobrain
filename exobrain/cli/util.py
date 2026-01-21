import logging
from pathlib import Path
from typing import Any

from exobrain.agent.base import Agent
from exobrain.cli import load_constitution
from exobrain.config import Config
from exobrain.providers.factory import ModelFactory
from exobrain.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


def auto_register_tools(config: Config, tool_registry: ToolRegistry) -> None:
    """Automatically register all tools from global tool class registry.

    This function iterates through all tool classes that have been registered
    via the @register_tool decorator and creates instances based on configuration.

    Args:
        config: Application configuration
        tool_registry: Tool registry to register tools into
    """
    # Import tools package to trigger @register_tool decorators
    import exobrain.tools  # noqa: F401

    # Track registered tools by category for logging
    registered_by_category: dict[str, list[str]] = {}

    # Iterate through all registered tool classes
    for config_key, tool_class_list in ToolRegistry.get_tool_classes().items():
        # Handle both single class and list of classes (for backward compatibility)
        tool_classes = tool_class_list if isinstance(tool_class_list, list) else [tool_class_list]

        for tool_class in tool_classes:
            try:
                # Create tool instance from config
                tool_instance = tool_class.from_config(config)

                if tool_instance is not None:
                    tool_registry.register(tool_instance)

                    # Track for logging
                    category = (
                        config_key if config_key != "__always_enabled__" else "always_enabled"
                    )
                    if category not in registered_by_category:
                        registered_by_category[category] = []
                    registered_by_category[category].append(tool_instance.name)

                    logger.debug(f"Registered tool: {tool_instance.name} (category: {category})")
            except Exception as e:
                logger.error(f"Failed to register tool {tool_class.__name__}: {e}")

    # Log summary
    total_tools = sum(len(tools) for tools in registered_by_category.values())
    logger.debug(
        f"Auto-registered {total_tools} tools across {len(registered_by_category)} categories"
    )
    for category, tool_names in registered_by_category.items():
        logger.debug(f"  {category}: {', '.join(tool_names)}")


def create_agent_from_config(
    config: Config,
    model_spec: str | None = None,
    constitution_file: str | None = None,
) -> tuple[Agent, Any]:
    """Create an agent from configuration.

    Args:
        config: Application configuration
        model_spec: Optional model specification (overrides config default)
        constitution_file: Optional constitution file path (overrides config)

    Returns:
        Tuple of (Configured Agent instance, Skills manager or None)
    """
    # Create model factory and get provider
    model_factory = ModelFactory(config)
    model_provider = model_factory.get_provider(model_spec)

    # Create tool registry
    tool_registry = ToolRegistry()

    # Check if .exobrain folder exists in current directory (workspace config)
    # If it exists, automatically add current directory to allowed directories
    cwd = Path.cwd()
    exobrain_dir = cwd / ".exobrain"
    if exobrain_dir.exists() and exobrain_dir.is_dir():
        # Ensure shell_execution permissions exist in config
        if not hasattr(config.permissions, "shell_execution"):
            logger.warning("shell_execution permissions not found in config")
        else:
            shell_exec_config = config.permissions.shell_execution
            # shell_exec_config is a dict, not an object with attributes
            if "allowed_directories" not in shell_exec_config:
                # Initialize allowed_directories if it doesn't exist
                shell_exec_config["allowed_directories"] = []

            # Add current directory if not already in allowed list
            cwd_str = str(cwd)
            if cwd_str not in shell_exec_config["allowed_directories"]:
                shell_exec_config["allowed_directories"].append(cwd_str)
                logger.info(
                    f"Detected .exobrain workspace config, automatically allowing current directory: {cwd_str}"
                )

    # Auto-register all tools from configuration (including skill tools)
    auto_register_tools(config, tool_registry)

    # Load constitution document (defaults to builtin-default if not specified)
    # Use passed constitution_file parameter if provided, otherwise use config
    if constitution_file is None:
        constitution_file = getattr(config.agent, "constitution_file", None)
    constitution_content = load_constitution(constitution_file)

    # Build system prompt with constitution
    system_prompt_parts = [config.agent.system_prompt]
    if constitution_content:
        system_prompt_parts.append("\n\n# Constitution and Behavioral Guidelines\n")
        system_prompt_parts.append(constitution_content)

    # Add skills summary to system prompt if skills are loaded
    skills_summary = ""
    skills_manager = None
    if getattr(config.skills, "enabled", True):
        # Import here to avoid circular dependency
        from exobrain.skills.loader import load_default_skills
        from exobrain.skills.manager import SkillsManager

        loader = load_default_skills(config)
        skills_manager = SkillsManager(loader.skills)

        if skills_manager.skills:
            skills_summary = skills_manager.get_all_skills_summary()
            if skills_summary:
                system_prompt_parts.append("\n\n# Available Skills\n")
                system_prompt_parts.append(skills_summary)
                logger.debug(f"Added skills summary to system prompt")

    # Log tool registrations with names for visibility
    tools = tool_registry.list_tools()
    tool_names = [t.name for t in tools]
    logger.debug(f"Registered {len(tools)} tools: {', '.join(tool_names)}")

    # Combine all parts into final system prompt
    system_prompt = "".join(system_prompt_parts)

    # Create agent
    agent = Agent(
        model_provider=model_provider,
        tool_registry=tool_registry,
        system_prompt=system_prompt,
        max_iterations=getattr(config.agent, "max_iterations", 100),
        temperature=getattr(config.agent, "temperature", 0.7),
        stream=config.agent.stream,
    )

    # Debug: Calculate character counts for constitution, skills, and tools
    import json

    constitution_chars = len(constitution_content) if constitution_content else 0
    skills_chars = len(skills_summary) if skills_summary else 0

    # Calculate tools schema size (JSON representation)
    tools_schemas = []
    for tool in tools:
        # Use Anthropic format as it's more compact and commonly used
        schema = tool.to_anthropic_format()
        tools_schemas.append(schema)
    tools_json = json.dumps(tools_schemas, ensure_ascii=False)
    tools_chars = len(tools_json)

    # Log debug information
    logger.debug(
        f"Prefix usage (characters):\n"
        f"  Constitution: {constitution_chars:,} chars\n"
        f"  Skills summary: {skills_chars:,} chars\n"
        f"  Tools schemas: {tools_chars:,} chars ({len(tools)} tools)\n"
        f"  Total: {constitution_chars + skills_chars + tools_chars:,} chars"
    )

    return agent, skills_manager
