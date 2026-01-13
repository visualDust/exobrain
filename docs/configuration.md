# Configuration Guide

ExoBrain uses YAML configuration files to manage settings. This guide covers the configuration structure, loading mechanism, and available options.

## Configuration Loading

### File Locations

ExoBrain searches for configuration files in the following locations (in order of priority):

1. **User global config** - `~/.config/exobrain/config.yaml` (Linux/macOS) or `%LOCALAPPDATA%\exobrain\config.yaml` (Windows)
2. **Project-level config** - `./.exobrain/config.yaml` (highest priority)

### Loading Mechanism

1. **Hierarchical Loading**: Configuration files are loaded sequentially and merged
2. **Deep Merge**: Nested dictionaries are recursively merged (not replaced)
   - Lists are replaced (not merged)
   - Primitive values (strings, numbers, booleans) are replaced
3. **Environment Variable Expansion**: Applied after merging using `${VAR_NAME}` syntax
4. **Validation**: Final merged configuration is validated against Pydantic schema

**Example of Deep Merge:**

User config (`~/.config/exobrain/config.yaml`):

```yaml
models:
  providers:
    openai:
      models: [gpt-4o, gpt-4o-mini]
```

Project config (`./.exobrain/config.yaml`):

```yaml
models:
  default: openai/gpt-4o # Override default
  providers:
    gemini: # Add new provider
      models: [gemini-2.0-flash]
```

Result: Both providers exist, with `default` set to `openai/gpt-4o`.

### Platform-Specific Paths

**Linux/macOS:**

- User config: `$XDG_CONFIG_HOME/exobrain/config.yaml` or `~/.config/exobrain/config.yaml`
- Home expansion: `~` is expanded to user home directory

**Windows:**

- User config: `%LOCALAPPDATA%\exobrain\config.yaml` or `%APPDATA%\exobrain\config.yaml`

## Configuration Structure

### Root Schema

```yaml
version: "0.1.5" # Config version (should match package version)
models: { ... } # Model providers and settings
agent: { ... } # Agent behavior configuration
tools: { ... } # Tool enablement flags
permissions: { ... } # Fine-grained permissions
skills: { ... } # Skill loading configuration
mcp: { ... } # MCP server configuration
memory: { ... } # Conversation memory settings
cli: { ... } # CLI appearance and behavior
logging: { ... } # Logging configuration
```

### models

Configure model providers and select the default model.

```yaml
models:
  default: "openai/gpt-4o-mini" # Required: format is "provider/model"

  providers: # Required: at least one provider
    openai:
      api_key: "${OPENAI_API_KEY}" # Optional: API key (use env vars)
      base_url: "https://api.openai.com/v1" # Optional: API endpoint

      # Models can be defined in two formats:
      models:
        # 1. Simple format (string)
        - gpt-4o-mini
        - gpt-3.5-turbo

        # 2. Extended format (object)
        - name: gpt-4o
          description: "Most capable model" # Optional: shown in 'models list'
          default_params: # Optional: model-specific defaults
            temperature: 0.7
            max_tokens: 4096

      # Provider-level defaults (legacy support, applies to models without their own defaults)
      default_params:
        temperature: 0.7

    local: # Example: local model hosted via vLLM
      base_url: http://localhost:8000/v1
      models:
        - Qwen/Qwen3-30B-A3B-Instruct-2507-FP8
        - Qwen/QwQ-32B
```

### agent

Configure the AI agent's behavior.

```yaml
agent:
  system_prompt: "You are ExoBrain, a helpful AI assistant." # Required
  constitution_file: null # Optional: path to constitution file or builtin name
  max_iterations: 500 # Optional: max autonomous iterations (-1 for unlimited)
  stream: true # Optional: enable streaming responses
```

**Constitution Files:**

- `null` - No constitution
- `builtin-default` - General-purpose assistant
- `builtin-coding` - Coding-focused assistant
- Custom path: `/path/to/constitution.md` or `~/.exobrain/constitutions/custom.md`

### tools

Enable or disable tool categories (boolean flags).

```yaml
tools:
  file_system: true # Default: true
  web_access: false # Default: false
  location: false # Default: false
  code_execution: false # Default: false
  shell_execution: false # Default: false
  time_management: true # Default: true
```

### permissions

Fine-grained permissions for each tool category (dict per tool).

```yaml
permissions:
  file_system:
    enabled: true
    allowed_paths: [] # Empty list = all paths (use with caution)
    denied_paths: # Takes precedence over allowed_paths
      - "~/.ssh"
      - "~/.aws"
      - "~/.config"
    max_file_size: 10485760 # Bytes (10MB)
    allow_edit: false # Allow file modifications

  code_execution:
    enabled: false
    timeout: 30 # Seconds
    memory_limit: "512MB"
    network_access: true

  shell_execution:
    enabled: false
    timeout: 600 # Seconds (10 minutes)
    allowed_directories:
      - "~/repos"
      - "~/Documents"
    denied_directories: # Takes precedence over allowed
      - "~/.ssh"
      - "/etc"
      - "/sys"
    allowed_commands: # Wildcard supported: "git *" matches all git commands
      - "ls"
      - "ls *"
      - "git *"
      - "python *"
    denied_commands: # Takes precedence over allowed
      - "rm -rf /"
      - "sudo *"

  web_access:
    enabled: false
    max_results: 5
    max_content_length: 10000 # Characters

  location:
    enabled: false
    provider_url: "https://ipinfo.io/json"
    timeout: 10 # Seconds
```

### skills

Configure skill loading and management.

```yaml
skills:
  enabled: true # Default: true
  skills_dir: "~/.exobrain/skills" # Default: "~/.exobrain/skills"
  disabled_skills: [] # List of skill names to disable
```

**Skill Loading Order:**

1. Builtin skills (packaged with ExoBrain)
2. User skills (`~/.exobrain/skills/`)
3. Project skills (`./.exobrain/skills/`)

### mcp

Configure MCP (Model Context Protocol) servers.

```yaml
mcp:
  enabled: false # Default: false
  servers: [] # List of custom MCP server configurations

  # Context7 integration (optional)
  context7:
    enabled: false
    api_key: "${CONTEXT7_API_KEY}"
    endpoint: "https://api.context7.com/v1/search"
    max_results: 5
    timeout: 20
```

**Custom MCP Server Example:**

```yaml
mcp:
  servers:
    - name: my-server
      enabled: true
      transport: stdio # or "http"
      command: python
      args:
        - -m
        - my_mcp_server
      env:
        API_KEY: "${MY_API_KEY}"
```

### memory

Configure conversation memory and history.

```yaml
memory:
  short_term:
    max_messages: 50 # Max messages in active conversation
    summarize_threshold: 40 # Trigger summarization at this count

  long_term:
    enabled: true
    storage_path: "~/.exobrain/data/conversations"

  working:
    max_items: 20 # Max items in working memory during execution

  save_tool_history: true # Save tool execution results to session
  tool_content_max_length: 1000 # Max length of tool message content (chars)
```

### cli

Configure CLI appearance and behavior.

```yaml
cli:
  theme: "auto" # Options: "auto", "light", "dark"
  show_token_usage: true # Show token usage after responses
  render_markdown: true # Render markdown in responses
```

### logging

Configure logging behavior.

```yaml
logging:
  level: "INFO" # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
  file: "~/.exobrain/logs/exobrain.log"
  rotate: true # Enable log rotation
  max_size: 10485760 # Max log file size in bytes (10MB)
  format: "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
```

## Environment Variables

### Variable Expansion

ExoBrain expands environment variables using `${VAR_NAME}` syntax:

```yaml
models:
  providers:
    openai:
      api_key: "${OPENAI_API_KEY}" # Expanded to value of $OPENAI_API_KEY
```

### Home Directory Expansion

Paths starting with `~` are expanded to the user's home directory:

```yaml
skills:
  skills_dir: "~/.exobrain/skills" # Expanded to /home/user/.exobrain/skills
```

### Common Environment Variables

```bash
# Model providers
export OPENAI_API_KEY="sk-..."
export GOOGLE_API_KEY="..."
export ANTHROPIC_API_KEY="..."

# MCP services
export CONTEXT7_API_KEY="..."
```

**Setting Environment Variables:**

Linux/macOS:

```bash
# Add to ~/.bashrc or ~/.zshrc
export OPENAI_API_KEY="sk-..."
```

Windows PowerShell:

```powershell
# Set permanently
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")
```

## CLI Commands

### Configuration Management

```bash
# Initialize configuration
exobrain config init              # Interactive wizard
exobrain config init --wizard     # Force wizard mode

# View configuration
exobrain config show              # Show merged configuration
exobrain config list              # List all config file locations
exobrain config show-path         # Show primary config path
exobrain config get models.default  # Get specific value

# Edit configuration
exobrain config edit              # Open in default editor
exobrain config edit --editor vim # Specify editor

# Reset configuration
exobrain config reset             # Reset to defaults (with confirmation)
exobrain config reset --yes       # Skip confirmation
```

### Model Management

```bash
# List available models
exobrain models list              # Shows models with descriptions

# Add provider/models
exobrain models add               # Interactive wizard
                                  # - Add new provider
                                  # - Add models to existing provider
                                  # - Set descriptions and default params

# Set default model
exobrain models use openai/gpt-4o
exobrain models use               # Interactive selection
```

### Skill Management

```bash
# List skills
exobrain skills list              # List all available skills
exobrain skills list --search term  # Search skills

# Show skill details
exobrain skills show <skill-name>

# Enable/disable skills
exobrain skills enable <skill-name>
exobrain skills disable <skill-name>
```

### MCP Management

```bash
# List MCP servers
exobrain mcp list

# Enable/disable MCP servers
exobrain mcp enable <server-name>
exobrain mcp disable <server-name>
```

## Configuration Examples

### Minimal Configuration

```yaml
models:
  default: "openai/gpt-4o-mini"
  providers:
    openai:
      api_key: "${OPENAI_API_KEY}"
```

### Secure Configuration

Restrictive permissions for maximum security:

```yaml
models:
  default: "openai/gpt-4o"
  providers:
    openai:
      api_key: "${OPENAI_API_KEY}"

agent:
  system_prompt: "You are a helpful AI assistant."
  max_iterations: 500

tools:
  file_system: true
  web_access: true
  shell_execution: false # Disabled
  code_execution: false # Disabled

permissions:
  file_system:
    enabled: true
    allowed_paths:
      - "~/Documents/safe-project"
    denied_paths:
      - "~/.ssh"
      - "~/.aws"
      - "~/.config"
    max_file_size: 1048576 # 1MB
    allow_edit: false # Read-only

  web_access:
    enabled: true
    max_content_length: 5000

memory:
  save_tool_history: true
  tool_content_max_length: 500

logging:
  level: "INFO"
```

### Developer Configuration

Full tool access for development:

```yaml
models:
  default: "openai/gpt-4o"
  providers:
    openai:
      api_key: "${OPENAI_API_KEY}"
      models:
        - name: gpt-4o
          description: "Best for complex tasks"
          default_params:
            temperature: 0.7
        - name: gpt-4o-mini
          description: "Fast for simple tasks"
          default_params:
            temperature: 0.5

agent:
  constitution_file: "builtin-coding"
  max_iterations: 1000
  stream: true

tools:
  file_system: true
  shell_execution: true
  code_execution: true
  web_access: true

permissions:
  file_system:
    enabled: true
    allowed_paths: [] # All paths
    allow_edit: true

  shell_execution:
    enabled: true
    timeout: 600
    allowed_directories:
      - "~/repos"
      - "~/projects"
    allowed_commands:
      - "*" # All commands (use with caution)
    denied_commands:
      - "rm -rf /"
      - "sudo rm *"

  code_execution:
    enabled: true
    timeout: 30
    network_access: true

memory:
  save_tool_history: true
  tool_content_max_length: 2000

logging:
  level: "DEBUG"
```

### Project-Level Override

`.exobrain/config.yaml` in your project (merged with user config):

```yaml
# Override only what's different for this project
models:
  default: "gemini/gemini-2.0-flash" # Use faster model for this project

agent:
  constitution_file: ".exobrain/constitutions/project-assistant.md"
  max_iterations: 200

permissions:
  file_system:
    allowed_paths:
      - "." # Only this project directory
```

### Multi-Model Configuration

Configure multiple providers with different models:

```yaml
models:
  default: "openai/gpt-4o"

  providers:
    openai:
      api_key: "${OPENAI_API_KEY}"
      base_url: "https://api.openai.com/v1"
      models:
        - name: gpt-4o
          description: "Most capable"
          default_params:
            temperature: 0.7
        - name: gpt-4o-mini
          description: "Fast and cheap"
          default_params:
            temperature: 0.5
            max_tokens: 2000

    gemini:
      api_key: "${GOOGLE_API_KEY}"
      base_url: "https://generativelanguage.googleapis.com/v1beta"
      models:
        - name: gemini-2.0-flash
          description: "Very fast responses"
          default_params:
            temperature: 0.3

    local:
      base_url: "http://localhost:8000/v1"
      models:
        - name: llama-3.1-70b
          description: "Local model"
          default_params:
            temperature: 0.8
```

## Troubleshooting

### Configuration Validation

ExoBrain validates configuration on load:

```bash
exobrain config show  # Shows validation errors if any
```

### Common Issues

**Issue: "Configuration file not found"**

```bash
exobrain config init
```

**Issue: "Invalid API key"**

```bash
# Check environment variable
echo $OPENAI_API_KEY

# Set if not defined
export OPENAI_API_KEY="sk-..."
```

**Issue: "Permission denied"**

```bash
# Check permissions in config
exobrain config get permissions.file_system.allowed_paths
```

**Issue: "Model not found"**

```bash
# List available models
exobrain models list

# Check provider configuration
exobrain config get models.providers
```

**Issue: "Version mismatch"**

If config version doesn't match package version, backup and regenerate:

```bash
cp ~/.config/exobrain/config.yaml ~/.config/exobrain/config.yaml.backup
exobrain config init
```

### Debug Mode

Enable verbose logging:

```bash
# Temporary (CLI flag)
exobrain --verbose chat

# Permanent (config)
exobrain config edit
# Set: logging.level: DEBUG
```

## Version Compatibility

The `version` field in your config should match the ExoBrain package version. If there's a mismatch, ExoBrain will error and prompt you to regenerate the config.

```yaml
version: "0.1.5" # Should match `exobrain --version`
```

To check compatibility:

```bash
exobrain --version           # Check package version
exobrain config show | head  # Check config version
```
