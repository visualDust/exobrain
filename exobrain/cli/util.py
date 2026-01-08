import logging
from typing import Any

from exobrain.agent.base import Agent
from exobrain.cli import load_constitution
from exobrain.config import Config
from exobrain.providers.factory import ModelFactory
from exobrain.tools.base import ToolRegistry
from exobrain.tools.context7_tools import Context7SearchTool
from exobrain.tools.file_tools import (
    EditFileTool,
    GrepFileTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from exobrain.tools.math_tools import MathEvaluateTool
from exobrain.tools.shell_tools import GetOSInfoTool, GetUserInfoTool, ShellExecuteTool
from exobrain.tools.time_tools import GetCurrentTimeTool, GetWorldTimeTool
from exobrain.tools.web_tools import WebFetchTool, WebSearchTool

logger = logging.getLogger(__name__)


def create_agent_from_config(
    config: Config, model_spec: str | None = None, enable_skills: bool = True
) -> tuple[Agent, Any]:  # Returns (agent, skills_manager)
    """Create an agent from configuration.

    Args:
        config: Application configuration
        model_spec: Optional model specification (overrides config default)
        enable_skills: Whether to enable skills (default: True)

    Returns:
        Tuple of (Configured Agent instance, Skills manager)
    """
    # Create model factory and get provider
    model_factory = ModelFactory(config)
    model_provider = model_factory.get_provider(model_spec)

    # Create tool registry
    tool_registry = ToolRegistry()

    # Register tools based on configuration
    if config.tools.file_system and config.permissions.file_system.get("enabled", True):
        fs_perms = config.permissions.file_system
        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []
        max_file_size = fs_perms.get("max_file_size", 10485760)
        allow_edit = fs_perms.get("allow_edit", False)

        tool_registry.register(ReadFileTool(allowed_paths, denied_paths))
        tool_registry.register(
            WriteFileTool(
                allowed_paths,
                denied_paths,
                max_file_size,
                allow_edit=allow_edit,
            )
        )
        tool_registry.register(
            EditFileTool(
                allowed_paths,
                denied_paths,
                max_file_size,
                allow_edit=allow_edit,
            )
        )
        tool_registry.register(ListDirectoryTool(allowed_paths, denied_paths))
        tool_registry.register(SearchFilesTool(allowed_paths, denied_paths))
        tool_registry.register(GrepFileTool(allowed_paths, denied_paths))

    if config.tools.time_management:
        tool_registry.register(GetCurrentTimeTool())
        tool_registry.register(GetWorldTimeTool())

    # Math evaluation and OS info are always available and require no extra permissions
    tool_registry.register(MathEvaluateTool())
    tool_registry.register(GetOSInfoTool())
    tool_registry.register(GetUserInfoTool())

    # Register shell execution tool if enabled
    if getattr(config.tools, "shell_execution", False) and config.permissions.shell_execution.get(
        "enabled", False
    ):
        shell_perms = config.permissions.shell_execution
        allowed_dirs = shell_perms.get("allowed_directories") or []
        denied_dirs = shell_perms.get("denied_directories") or []
        allowed_cmds = shell_perms.get("allowed_commands") or []
        denied_cmds = shell_perms.get("denied_commands") or []
        timeout = shell_perms.get("timeout", 30)

        tool_registry.register(
            ShellExecuteTool(
                allowed_directories=allowed_dirs,
                denied_directories=denied_dirs,
                allowed_commands=allowed_cmds,
                denied_commands=denied_cmds,
                timeout=timeout,
            )
        )

    # Register web tools if enabled
    if getattr(config.tools, "web_access", False) and config.permissions.web_access.get(
        "enabled", False
    ):
        max_results = config.permissions.web_access.get("max_results", 5)
        max_content_length = config.permissions.web_access.get("max_content_length", 10000)

        tool_registry.register(WebSearchTool(max_results=max_results))
        tool_registry.register(WebFetchTool(max_content_length=max_content_length))
        # Context7 search (uses the same web_access permission scope)
        ctx7_cfg = getattr(config.mcp, "context7", {}) or {}
        if ctx7_cfg.get("enabled") and ctx7_cfg.get("api_key"):
            from exobrain.mcp.context7_client import Context7Client

            ctx7_client = Context7Client(
                api_key=ctx7_cfg["api_key"],
                endpoint=ctx7_cfg.get("endpoint", "https://api.context7.com/v1/search"),
                timeout=ctx7_cfg.get("timeout", 20),
                max_results=ctx7_cfg.get("max_results", max_results),
            )
            tool_registry.register(Context7SearchTool(ctx7_client))
    # Register location tool if enabled
    if getattr(config.tools, "location", False) and config.permissions.location.get(
        "enabled", False
    ):
        from exobrain.tools.location_tools import GetUserLocationTool

        location_perms = config.permissions.location
        provider_url = location_perms.get("provider_url", "https://ipinfo.io/json")
        timeout = location_perms.get("timeout", 10)
        token = location_perms.get("token")

        tool_registry.register(
            GetUserLocationTool(provider_url=provider_url, timeout=timeout, token=token)
        )

    # Load constitution document (defaults to builtin-default if not specified)
    constitution_file = getattr(config.agent, "constitution_file", None)
    constitution_content = load_constitution(constitution_file)

    # Build system prompt with constitution
    system_prompt_parts = [config.agent.system_prompt]
    if constitution_content:
        system_prompt_parts.append("\n\n# Constitution and Behavioral Guidelines\n")
        system_prompt_parts.append(constitution_content)

    # Load skills if enabled
    skills_manager = None
    skills_summary = ""

    if enable_skills and getattr(config.skills, "enabled", True):
        from exobrain.skills.loader import load_default_skills
        from exobrain.skills.manager import SkillsManager
        from exobrain.tools.skill_tools import GetSkillTool, ListSkillsTool, SearchSkillsTool

        logger.debug("Loading skills...")
        loader = load_default_skills(config)
        skills_manager = SkillsManager(loader.skills)

        # Register skill tools
        if skills_manager.skills:
            get_skill_tool = GetSkillTool(skills_manager)
            search_skills_tool = SearchSkillsTool(skills_manager)
            list_skills_tool = ListSkillsTool(skills_manager)

            tool_registry.register(get_skill_tool)
            tool_registry.register(search_skills_tool)
            tool_registry.register(list_skills_tool)

            logger.debug(f"Registered {len(skills_manager.skills)} skills")

        # Add skills summary to system prompt
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
    logger.info(
        f"Model context usage (characters):\n"
        f"  Constitution: {constitution_chars:,} chars\n"
        f"  Skills summary: {skills_chars:,} chars\n"
        f"  Tools schemas: {tools_chars:,} chars ({len(tools)} tools)\n"
        f"  Total: {constitution_chars + skills_chars + tools_chars:,} chars"
    )

    return agent, skills_manager
