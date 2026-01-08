"""Configuration management for ExoBrain."""

import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class ModelProviderConfig(BaseModel):
    """Configuration for a model provider."""

    api_key: str | None = None
    base_url: str | None = None
    models: list[str] = []
    default_params: dict[str, Any] = Field(default_factory=dict)


class ModelsConfig(BaseModel):
    """Models configuration."""

    default: str
    providers: dict[str, ModelProviderConfig]
    embedding: dict[str, Any] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    """Agent configuration."""

    system_prompt: str
    constitution_file: str | None = None  # Path to constitution document
    max_iterations: int = (
        500  # Maximum autonomous iterations per user message. Negative value for unlimited
    )
    stream: bool = True


class ToolsConfig(BaseModel):
    """Tools configuration."""

    file_system: bool = True
    web_access: bool = False
    location: bool = False
    code_execution: bool = False
    shell_execution: bool = False
    time_management: bool = True


class PermissionsConfig(BaseModel):
    """Permissions configuration."""

    file_system: dict[str, Any] = Field(default_factory=dict)
    code_execution: dict[str, Any] = Field(default_factory=dict)
    shell_execution: dict[str, Any] = Field(default_factory=dict)
    web_access: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, Any] = Field(default_factory=dict)


class SkillsConfig(BaseModel):
    """Skills configuration."""

    enabled: bool = True
    skills_dir: str = "~/.exobrain/skills"
    builtin_skills: list[str] = Field(default_factory=list)
    auto_load: bool = True


class MCPConfig(BaseModel):
    """MCP configuration."""

    enabled: bool = False
    servers: list[dict[str, Any]] = Field(default_factory=list)
    context7: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": False,
            "api_key": None,
            "endpoint": "https://api.context7.com/v1/search",
            "max_results": 5,
            "timeout": 20,
        }
    )


class MemoryConfig(BaseModel):
    """Memory configuration."""

    short_term: dict[str, Any] = Field(default_factory=dict)
    long_term: dict[str, Any] = Field(default_factory=dict)
    save_tool_history: bool = True  # Save tool messages to conversation history
    tool_content_max_length: int = 1000  # Maximum length of tool message content to save


class CLIConfig(BaseModel):
    """CLI configuration."""

    theme: str = "auto"
    show_timestamps: bool = False
    show_token_usage: bool = True
    syntax_highlighting: bool = True
    render_markdown: bool = True


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    file: str = "~/.exobrain/logs/exobrain.log"
    rotate: bool = True
    max_size: int = 10485760
    backup_count: int = 5
    format: str = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    audit: dict[str, Any] = Field(default_factory=dict)


class PerformanceConfig(BaseModel):
    """Performance configuration."""

    cache: dict[str, Any] = Field(default_factory=dict)
    concurrency: dict[str, Any] = Field(default_factory=dict)


class Config(BaseModel):
    """Main configuration."""

    version: str | None = None  # Config version, should match package version
    models: ModelsConfig
    agent: AgentConfig
    tools: ToolsConfig
    permissions: PermissionsConfig
    skills: SkillsConfig
    mcp: MCPConfig
    memory: MemoryConfig
    cli: CLIConfig
    logging: LoggingConfig
    performance: PerformanceConfig


def expand_env_vars(data: Any) -> Any:
    """Recursively expand environment variables in configuration."""
    if isinstance(data, dict):
        return {key: expand_env_vars(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [expand_env_vars(item) for item in data]
    elif isinstance(data, str):
        # Expand ${VAR_NAME} syntax
        if data.startswith("${") and data.endswith("}"):
            var_name = data[2:-1]
            return os.environ.get(var_name, data)
        # Expand ~ for home directory
        if data.startswith("~"):
            return str(Path(data).expanduser())
        return data
    return data


def get_user_config_directory() -> Path:
    """Get platform-specific user config directory for ExoBrain.

    Returns:
        Path to user config directory:
        - Windows: %LOCALAPPDATA%/exobrain or %APPDATA%/exobrain
        - Linux/macOS: $XDG_CONFIG_HOME/exobrain or ~/.config/exobrain
    """
    if os.name == "nt":
        # Windows: prefer LOCALAPPDATA, fallback to APPDATA
        appdata = os.getenv("LOCALAPPDATA")
        if appdata:
            return Path(appdata) / "exobrain"
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "exobrain"
        # Fallback to home directory
        return Path.home() / "exobrain"

    # Linux/macOS: use XDG_CONFIG_HOME if set, else ~/.config
    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "exobrain"
    return Path.home() / ".config" / "exobrain"


def get_user_config_path() -> Path:
    """Get user config file path.

    Returns:
        Path to user config.yaml file
    """
    return get_user_config_directory() / "config.yaml"


def merge_configs(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two configuration dictionaries.

    Args:
        base: Base configuration
        override: Configuration to merge (takes priority)

    Returns:
        Merged configuration
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursively merge nested dicts
            result[key] = merge_configs(result[key], value)
        else:
            # Override value
            result[key] = value

    return result


def get_default_config() -> dict[str, Any]:
    """Get default configuration.

    Returns:
        Default configuration dictionary
    """
    # This would ideally load from a default config file or return a dict
    # For now, return minimal required structure
    return {
        "models": {"default": "openai/gpt-4o", "providers": {}},
        "agent": {
            "system_prompt": "You are a helpful AI assistant.",
            "max_iterations": 500,
            "stream": True,
        },
        "tools": {},
        "permissions": {},
        "skills": {"enabled": True},
        "mcp": {"servers": {}},
        "memory": {},
        "cli": {},
        "logging": {},
        "performance": {},
    }


def load_config(
    config_path: str | Path | None = None,
) -> tuple[Config, dict[str, Any]]:
    """Load configuration with hierarchical fallback.

    Configuration priority (lowest to highest):
    1. Default config
    2. User global config (~/.config/exobrain/config.yaml)
    3. Project root config (./config.yaml)
    4. Project-level config (./.exobrain/config.yaml) - highest priority

    Or if config_path is specified, only that file is loaded.

    Args:
        config_path: Path to configuration file. If None, uses hierarchical loading.

    Returns:
        Tuple of (loaded Config, metadata dict with 'sources' list and 'primary_source')

    Raises:
        FileNotFoundError: If no configuration file is found
        ValueError: If configuration is invalid
    """
    # Start with default config
    config_data = get_default_config()
    config_sources = []  # Track all loaded config files

    # If specific path provided, use only that file
    if config_path is not None:
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f)

        config_data = merge_configs(config_data, user_config)
        config_sources.append(("specified", str(config_path)))
        logger.debug(f"Loaded config from: {config_path}")

    else:
        # Hierarchical loading - merge in priority order (low to high)
        found_any = False

        # 1. Try user global config (~/.config/exobrain/config.yaml)
        user_config_path = get_user_config_path()
        if user_config_path.exists():
            with open(user_config_path, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f)
            config_data = merge_configs(config_data, user_config)
            config_sources.append(("user", str(user_config_path)))
            found_any = True
            logger.debug(f"Loaded user config from: {user_config_path}")

        # # 2. Try legacy location for backwards compatibility
        # old_config_path = Path.home() / ".exobrain" / "config.yaml"
        # if old_config_path.exists() and old_config_path != user_config_path:
        #     with open(old_config_path, "r", encoding="utf-8") as f:
        #         old_config = yaml.safe_load(f)
        #     config_data = merge_configs(config_data, old_config)
        #     config_sources.append(("legacy", str(old_config_path)))
        #     found_any = True
        #     logger.info(f"Loaded config from legacy location: {old_config_path}")

        # 3. Try project-level config (./.exobrain/config.yaml) - highest priority
        project_level_config_path = Path.cwd() / ".exobrain" / "config.yaml"
        if project_level_config_path.exists():
            with open(project_level_config_path, "r", encoding="utf-8") as f:
                project_level_config = yaml.safe_load(f)
            config_data = merge_configs(config_data, project_level_config)
            config_sources.append(("project-level", str(project_level_config_path)))
            found_any = True
            logger.info(f"Loaded project-level config from: {project_level_config_path}")

        if not found_any:
            raise FileNotFoundError(
                f"Configuration file not found. Please create one using:\n"
                f"  exobrain config init\n\n"
                f"Or manually create either:\n"
                f"  - User level: {user_config_path}\n"
                f"  - Project level: {project_level_config_path}\n"
            )

    # Expand environment variables
    expanded_config = expand_env_vars(config_data)

    # Validate and parse
    try:
        config = Config(**expanded_config)

        # Check version compatibility
        from exobrain import __version__ as package_version

        config_version = config.version
        if config_version is not None and config_version != package_version:
            error_msg = (
                f"\n{'=' * 60}\n"
                f"ERROR: Configuration version mismatch!\n\n"
                f"  Config version:  {config_version}\n"
                f"  Package version: {package_version}\n\n"
                f"Your configuration file is incompatible with the current version.\n"
                f"Please run 'exobrain config init' to regenerate your configuration.\n\n"
                f"Note: This will overwrite your current configuration.\n"
                f"You may want to backup your existing config first:\n"
                f"  cp {config_sources[-1][1] if config_sources else 'config.yaml'} config.yaml.backup\n"
                f"{'=' * 60}\n"
            )
            logger.error(error_msg)
            print(error_msg, file=sys.stderr)
            sys.exit(1)

        # Prepare metadata
        metadata = {
            "sources": config_sources,
            "primary_source": config_sources[-1] if config_sources else ("default", "builtin"),
        }

        logger.debug(f"Successfully loaded config from: {[s[1] for s in config_sources]}")
        return config, metadata
    except Exception as e:
        primary_source = config_sources[-1][1] if config_sources else "default"
        raise ValueError(f"Invalid configuration in {primary_source}: {e}") from e


def create_default_config(output_path: str | Path) -> None:
    """Create a default configuration file.

    Args:
        output_path: Where to write the configuration file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    default_config = {
        "models": {
            "default": "openai/gpt-4o-mini",
            "providers": {
                "openai": {
                    "api_key": "${OPENAI_API_KEY}",
                    "base_url": "https://api.openai.com/v1",
                    "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
                    "default_params": {"temperature": 0.7},
                }
            },
            "embedding": {
                "default": "local",
                "providers": {
                    "local": {
                        "model": "sentence-transformers/all-MiniLM-L6-v2",
                        "device": "cpu",
                    }
                },
            },
        },
        "agent": {
            "system_prompt": "You are ExoBrain, a helpful personal AI assistant.",
            "max_iterations": 500,
            "stream": True,
        },
        "tools": {
            "file_system": True,
            "web_access": False,
            "code_execution": False,
            "time_management": True,
        },
        "permissions": {
            "file_system": {
                "enabled": True,
                "allowed_paths": ["~/Documents", "~/Desktop"],
                "denied_paths": ["~/.ssh", "~/.aws"],
                "max_file_size": 10485760,
                "allow_edit": False,
            },
            "code_execution": {"enabled": False, "timeout": 30},
            "web_access": {"enabled": False},
        },
        "skills": {
            "enabled": True,
            "skills_dir": "~/.exobrain/skills",
            "builtin_skills": ["note_manager"],
            "auto_load": True,
        },
        "mcp": {"enabled": False, "servers": []},
        "memory": {
            "short_term": {"max_messages": 50, "summarize_threshold": 40},
            "long_term": {
                "enabled": True,
                "storage_path": "~/.exobrain/data/conversations",
                "auto_save_interval": 60,
            },
            "save_tool_history": True,
            "tool_content_max_length": 1000,
        },
        "cli": {
            "theme": "auto",
            "show_timestamps": False,
            "show_token_usage": True,
            "syntax_highlighting": True,
            "render_markdown": True,
        },
        "logging": {
            "level": "INFO",
            "file": "~/.exobrain/logs/exobrain.log",
            "rotate": True,
            "max_size": 10485760,
            "backup_count": 5,
            "format": "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            "audit": {"enabled": True, "file": "~/.exobrain/logs/audit.log"},
        },
        "performance": {
            "cache": {"enabled": True, "ttl": 3600, "max_size": 100},
            "concurrency": {
                "max_concurrent_requests": 5,
                "max_concurrent_tools": 3,
            },
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(default_config, f, default_flow_style=False, sort_keys=False)
