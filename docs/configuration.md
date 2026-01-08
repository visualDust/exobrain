# Configuration File Structure

ExoBrain uses YAML configuration files to customize behavior, model providers, tools, permissions, and more. This document provides a comprehensive guide to the configuration structure.

## Configuration File Locations

ExoBrain supports multiple configuration file locations with a priority hierarchy:

1. **Default config (builtin)** - Hard-coded defaults in the application
2. **User global config** - `~/.config/exobrain/config.yaml` or `~/.exobrain/config.yaml`
3. **Project-level config** - `./.exobrain/config.yaml` (highest priority)

### Configuration Loading

- Configurations are loaded sequentially and **deep merged**
- Each layer only needs to specify overrides (partial configuration)
- Nested dictionaries are merged recursively (not replaced entirely)
- Primitive values (strings, numbers, booleans) are replaced
- Environment variables are expanded after merging (e.g., `${OPENAI_API_KEY}`)
- The final merged configuration is validated against the Pydantic schema

## Configuration Sections

### 1. Version

```yaml
version: "0.1.0"
```

The ExoBrain version. This is auto-updated during `exobrain config init`.

### 2. Models

Configure model providers and select the default model.

```yaml
models:
  default: openai/gpt-5-mini # Format: provider/model
  providers:
    openai:
      api_key: ${OPENAI_API_KEY} # Environment variable
      base_url: https://api.openai.com/v1
      models:
        - gpt-5-pro
        - gpt-5
        - gpt-5-mini
        - gpt-5-nano
        - gpt-4
        - gpt-4o
        - gpt-4o-mini
        - gpt-3.5-turbo
      default_params:
        temperature: 0.7
        # max_tokens: 4096  # Optional
```

#### Adding Third-Party Providers

You can add any OpenAI-compatible API provider:

```yaml
models:
  providers:
    custom-provider:
      api_key: ${CUSTOM_API_KEY}
      base_url: https://api.custom-provider.com/v1
      models:
        - custom-model-1
        - custom-model-2
      default_params:
        temperature: 0.7
```

**CLI Command:**

```bash
exobrain models add  # Interactive wizard for adding providers
exobrain models list # List available models
exobrain models use provider/model  # Set default model
```

#### Supported Providers

- **openai** - OpenAI API (gpt-4, gpt-5, etc.)
- **gemini** - Google Gemini API
- **local** - Local models via OpenAI-compatible server (vLLM, Ollama, etc.)
- **custom** - Any OpenAI-compatible API

### 3. Agent

Configure the AI agent's behavior and personality.

```yaml
agent:
  system_prompt: "You are ExoBrain, a personal AI assistant focused on productivity."
  constitution_file: # Options: builtin-default, builtin-coding, or path to custom .md file
  max_iterations: 500 # Max autonomous iterations. Use -1 for unlimited
  stream: true # Enable streaming responses
  temperature: 0.7 # Optional: override provider default
```

#### Constitution Files

Constitution files define the agent's personality and behavioral guidelines:

- `builtin-default` - General-purpose assistant (default)
- `builtin-coding` - Coding-focused assistant
- Custom path - Path to your own constitution markdown file
  - Absolute: `/path/to/constitution.md`
  - Relative to project: `.exobrain/constitutions/custom.md`
  - Relative to user: `~/.exobrain/constitutions/custom.md`

**Example:**

```yaml
agent:
  constitution_file: builtin-coding
```

### 4. Tools

Enable or disable tool categories.

```yaml
tools:
  file_system: true # File read/write/search
  web_access: true # Web search and fetch
  location: true # Get user location
  code_execution: true # Execute Python code
  shell_execution: true # Execute shell commands
  time_management: true # Time and timezone tools
```

### 5. Permissions

Fine-grained permissions for each tool category.

#### File System Permissions

```yaml
permissions:
  file_system:
    enabled: true
    allowed_paths: [] # Empty = all paths allowed
    denied_paths: # Blacklist specific paths
      - ~/.ssh
      - ~/.aws
      - ~/.config
      - ~/.*credentials*
    max_file_size: 10485760 # 10MB in bytes
    allow_edit: false # Allow file modifications
```

**Security Notes:**

- `allowed_paths: []` means no restrictions (use with caution)
- `denied_paths` takes precedence over `allowed_paths`
- Glob patterns are supported (e.g., `~/.*credentials*`)

#### Shell Execution Permissions

```yaml
permissions:
  shell_execution:
    enabled: true
    timeout: 30 # seconds
    allowed_directories:
      - ~/repos
      - ~/Documents
      - ~/Desktop
    denied_directories:
      - ~/.ssh
      - ~/.aws
      - /etc
      - /sys
      - /proc
    allowed_commands:
      - ls
      - ls *
      - pwd
      - git *
      - python *
      - npm *
      # ... (see config.example.yaml for full list)
    denied_commands:
      - rm -rf /
      - sudo *
      - shutdown *
      # ... (see config.example.yaml for full list)
```

**Command Matching:**

- Exact match: `ls` only matches `ls`
- Wildcard: `git *` matches `git status`, `git commit`, etc.
- Denied commands take precedence over allowed commands

#### Code Execution Permissions

```yaml
permissions:
  code_execution:
    enabled: true
    timeout: 30 # seconds
    memory_limit: 512MB
    network_access: true
```

#### Web Access Permissions

```yaml
permissions:
  web_access:
    enabled: true
    max_results: 5 # Max search results
    max_content_length: 10000 # Max fetched content length (chars)
```

#### Location Permissions

```yaml
permissions:
  location:
    enabled: true
    provider_url: https://ipinfo.io/json
    timeout: 10
    # token: <OPTIONAL_TOKEN>  # For premium providers
```

### 6. Skills

Configure skill loading and management.

```yaml
skills:
  enabled: true
  skills_dir: ~/.exobrain/skills # Custom skills directory
  builtin_skills:
    - note_manager
  auto_load: true # Auto-load skills from skills_dir
```

**Skill Locations:**

1. Builtin skills (packaged with ExoBrain)
2. User skills (`~/.exobrain/skills/`)
3. Project skills (`./.exobrain/skills/`)

**CLI Commands:**

```bash
exobrain skills list           # List all available skills
exobrain skills show <name>    # Show skill details
exobrain skills list --search <term>  # Search skills
```

### 7. MCP (Model Context Protocol)

Configure MCP servers for extended capabilities.

```yaml
mcp:
  enabled: true
  servers: [] # Custom MCP servers
  context7:
    enabled: true
    api_key: ${CONTEXT7_API_KEY}
    endpoint: https://api.context7.com/v1/search
    max_results: 5
    timeout: 20
```

#### Adding Custom MCP Servers

```yaml
mcp:
  servers:
    - name: my-mcp-server
      enabled: true
      transport: stdio # or http
      command: python
      args:
        - -m
        - my_mcp_server
      env:
        API_KEY: ${MY_MCP_API_KEY}
```

**CLI Commands:**

```bash
exobrain mcp list              # List MCP servers
exobrain mcp enable <name>     # Enable a server
exobrain mcp disable <name>    # Disable a server
```

### 8. Memory

Configure conversation history and memory management.

```yaml
memory:
  short_term:
    max_messages: 50
    summarize_threshold: 40
  long_term:
    enabled: true
    storage_path: ~/.exobrain/data/conversations
    auto_save_interval: 60 # seconds
  working:
    max_items: 20
  save_tool_history: true # Save tool execution results
  tool_content_max_length: 1000 # Max tool message length (chars)
```

**Memory Types:**

- **Short-term** - Recent messages in active conversation
- **Long-term** - Persistent conversation storage
- **Working** - Current context items during agent execution

**Tool History:**

- `save_tool_history: true` - Save tool execution results to session
- `tool_content_max_length` - Limit tool message size to prevent bloat
  - Set to 500-1000 for compact storage
  - Set to 5000+ for detailed debugging

### 9. CLI

Configure CLI behavior and appearance.

```yaml
cli:
  theme: auto # auto, light, dark
  show_timestamps: false
  show_token_usage: true
  syntax_highlighting: true
  render_markdown: true # Render assistant responses as markdown
```

### 10. Logging

Configure logging behavior.

```yaml
logging:
  level: INFO # DEBUG, INFO, WARNING, ERROR, CRITICAL
  file: ~/.exobrain/logs/exobrain.log
  rotate: true
  max_size: 10485760 # 10MB
  backup_count: 5
  format: "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
  audit:
    enabled: true
    file: ~/.exobrain/logs/audit.log
```

**Log Levels:**

- `DEBUG` - Detailed information for diagnosing problems
- `INFO` - General informational messages (default)
- `WARNING` - Warning messages
- `ERROR` - Error messages
- `CRITICAL` - Critical error messages

### 11. Performance

Configure performance and caching settings.

```yaml
performance:
  cache:
    enabled: true
    ttl: 3600 # seconds
    max_size: 250 # max cache entries
  concurrency:
    max_concurrent_requests: 5
    max_concurrent_tools: 3
  background_tasks:
    enabled: true
    max_workers: 3
```

## Environment Variables

ExoBrain supports environment variable expansion in configuration values using the `${VAR_NAME}` syntax.

### Common Environment Variables

```bash
# Model Provider API Keys
export OPENAI_API_KEY="sk-..."
export GOOGLE_API_KEY="..."
export ANTHROPIC_API_KEY="..."

# MCP Services
export CONTEXT7_API_KEY="..."

# Custom Providers
export CUSTOM_API_KEY="..."
```

### Setting Environment Variables

**Linux/macOS (bash/zsh):**

```bash
# Add to ~/.bashrc or ~/.zshrc
export OPENAI_API_KEY="sk-..."

# Or create a .env file and load it
echo 'export OPENAI_API_KEY="sk-..."' >> ~/.exobrain/.env
source ~/.exobrain/.env
```

**Windows (PowerShell):**

```powershell
# Add to PowerShell profile
$env:OPENAI_API_KEY = "sk-..."

# Or set permanently
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")
```

## Configuration Management

### Initialize Configuration

```bash
exobrain config init  # Interactive wizard
exobrain config init --wizard  # Force wizard mode
```

### View Configuration

```bash
exobrain config show      # Show current settings
exobrain config list      # List all config locations
exobrain config show-path # Show primary config path
exobrain config get models.default  # Get specific value
```

### Edit Configuration

```bash
exobrain config edit      # Open in default editor
exobrain config edit --editor vim  # Specify editor
```

### Reset Configuration

```bash
exobrain config reset     # Reset to defaults (with confirmation)
exobrain config reset --yes  # Skip confirmation
```

## Example Configurations

### Minimal Configuration

For a minimal setup with only essential settings:

```yaml
models:
  default: openai/gpt-5-mini
  providers:
    openai:
      api_key: ${OPENAI_API_KEY}
```

### Secure Configuration

For maximum security with restricted permissions:

```yaml
models:
  default: openai/gpt-4o

agent:
  constitution_file: builtin-default

tools:
  file_system: true
  shell_execution: false # Disable shell
  code_execution: false # Disable code execution
  web_access: true

permissions:
  file_system:
    enabled: true
    allowed_paths:
      - ~/Documents/allowed_project
    denied_paths:
      - ~/.ssh
      - ~/.aws
      - ~/.config
    max_file_size: 1048576 # 1MB
    allow_edit: false

memory:
  save_tool_history: true
  tool_content_max_length: 500 # Compact storage
```

### Developer Configuration

For software development with full tool access:

```yaml
models:
  default: openai/gpt-5

agent:
  constitution_file: builtin-coding
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
    allowed_directories:
      - ~/repos
      - ~/projects
    allowed_commands:
      - "*" # All commands (use with caution)
    denied_commands:
      - rm -rf /
      - sudo rm *

memory:
  save_tool_history: true
  tool_content_max_length: 2000

logging:
  level: DEBUG # Detailed logs for development
```

### Project-Level Override

`.exobrain/config.yaml` in your project:

```yaml
# Only override what's different for this project
models:
  default: gemini/gemini-2.5-flash # Use faster model for this project

agent:
  constitution_file: .exobrain/constitutions/project-assistant.md
  max_iterations: 200

permissions:
  file_system:
    allowed_paths:
      - . # Only this project directory
```

## Validation and Troubleshooting

### Configuration Validation

ExoBrain validates configuration on load:

```bash
exobrain config show  # Will show validation errors if any
```

### Common Issues

**Issue: "Configuration file not found"**

```bash
# Solution: Initialize configuration
exobrain config init
```

**Issue: "Invalid API key"**

```bash
# Solution: Check environment variable
echo $OPENAI_API_KEY
# Set if not defined
export OPENAI_API_KEY="sk-..."
```

**Issue: "Permission denied"**

```bash
# Solution: Check file_system permissions in config
exobrain config get permissions.file_system.allowed_paths
```

**Issue: "Model not found"**

```bash
# Solution: List available models
exobrain models list
# Check provider configuration
exobrain config get models.providers
```

### Debug Mode

Enable verbose logging for troubleshooting:

```bash
exobrain --verbose chat           # Enable verbose output
exobrain config get logging.level # Check log level
exobrain config edit              # Set level: DEBUG
```
