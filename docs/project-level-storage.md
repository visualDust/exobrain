# Project-Level Storage Structure

ExoBrain supports project-level storage through the `.exobrain/` directory in your project root. This allows you to have project-specific configurations, conversations, skills, and more.

## Directory Structure

```
.exobrain/
├── config.yaml              # Project-level configuration (highest priority)
├── constitutions/           # Project-level personality definitions
│   └── *.md                # Constitution files (markdown format)
├── skills/                  # Project-specific skills
│   └── */SKILL.md          # Skill definitions
├── conversations/           # Project conversation history
│   ├── sessions.json       # Session index file
│   └── sessions/           # Individual session directories
│       └── {session_id}/
│           ├── metadata.json    # Session metadata
│           └── messages.jsonl   # Conversation messages
└── logs/                    # Project-level logs
    └── exobrain.log        # Application logs
```

You can initialize this structure manually or via CLI commands `exobrain init`. There is a global configuration and storage located in the user's home directory (e.g., `~/.exobrain/`). The project-level `.exobrain/` directory allows overriding and extending these global settings on a per-project basis.

## Component Details

### Configuration (`config.yaml`)

The project-level configuration file has the **highest priority** in the configuration hierarchy.

**Loading Priority** (lowest to highest):

1. Default config (builtin) - Hard-coded defaults in the application
2. User global config (`~/.config/exobrain/config.yaml` or `~/.exobrain/config.yaml`)
3. **Project-level config (`./.exobrain/config.yaml`)** ← Highest priority

**Loading Logic:**

- Configurations are loaded sequentially and **deep merged**
- Each layer only needs to specify overrides (partial configuration)
- Nested dictionaries are merged recursively (not replaced entirely)
- Primitive values (strings, numbers, booleans) are replaced
- Environment variables are expanded after merging (e.g., `${OPENAI_API_KEY}`)
- The final merged configuration is validated against the Pydantic schema

**Example:**

If your user config has:

```yaml
models:
  default: "openai/gpt-4o"
  providers:
    openai:
      api_key: "${OPENAI_API_KEY}"
      models: ["gpt-4o", "gpt-4o-mini"]
```

And your project config has:

```yaml
models:
  default: "openai/gpt-4o-mini"
  providers:
    openai:
      models: ["gpt-4o-mini"] # Override only the models list
```

The final merged result will be:

```yaml
models:
  default: "openai/gpt-4o-mini" # Overridden by project
  providers:
    openai:
      api_key: "${OPENAI_API_KEY}" # Inherited from user config
      models: ["gpt-4o-mini"] # Overridden by project (list replaced)
```

### Constitutions (`constitutions/`)

Constitution files define the AI's personality and behavior guidelines using markdown format.

**Loading Priority** (lowest to highest):

1. Package built-in constitutions (`exobrain/constitutions/*.md`)
2. User global constitutions (`~/.config/exobrain/constitutions/*.md`)
3. **Project-level constitutions (`./.exobrain/constitutions/*.md`)**
4. Project constitutions directory (`./constitutions/*.md`)
5. Project root (`./CONSTITUTION.md` or `./{name}.md`) ← Highest priority

**Loading Logic:**

- When a constitution is referenced by name (e.g., `"my-constitution"`), all locations are searched
- The **highest priority match** is used (last found wins)
- If multiple locations have the same constitution file, only the highest priority one is loaded
- Constitution content is read as plain text (markdown) and passed to the AI model
- The `agent.constitution_file` config setting specifies which constitution to use
- If the path is relative or just a name, the search priority is applied
- If the path is absolute, that specific file is used directly

**Usage:**

- List available constitutions: `exobrain constitution list`
- View a constitution: `exobrain constitution show <name>`
- Switch constitution: `exobrain constitution use <name>`
- Create new: `exobrain constitution create <name>`

### Skills (`skills/`)

Skills are reusable agent capabilities that extend Claude's functionality. Each skill packages instructions, metadata, and optional resources (scripts, templates) that Claude uses automatically when relevant.

**Loading Priority** (lowest to highest):

1. Builtin skills (submodules):
   - Anthropic skills - `exobrain/skills/anthropic/skills/`
   - Obsidian skills - `exobrain/skills/obsidian/`
2. Configured skills directory (from `config.skills.skills_dir`)
3. User global skills (`~/.exobrain/skills`)
4. **Project-level skills (`./.exobrain/skills`)** ← Highest priority

**Loading Logic:**

- All configured skill paths are scanned recursively for `SKILL.md` files
- Skills are loaded in priority order (lowest to highest)
- Skills with the same `name` field: **higher priority overwrites lower priority**
- Skills use a **progressive disclosure** model with three loading levels:
  - **Level 1 (Metadata)**: Always loaded at startup - only the YAML frontmatter
  - **Level 2 (Instructions)**: Loaded when skill is triggered - the SKILL.md body
  - **Level 3 (Resources)**: Loaded as needed - additional files and scripts
- All loaded skills are available to the agent during runtime
- Skills can be selectively enabled/disabled via configuration

**Skill Structure:**

Skills can be organized in two ways:

1. **Single file** (simple skills):

   ```
   my-skill.md         # Contains SKILL.md frontmatter and instructions
   ```

2. **Directory structure** (complex skills with resources):
   ```
   my-skill/
   ├── SKILL.md         # Main instructions (required)
   ├── FORMS.md         # Additional instructions (optional)
   ├── REFERENCE.md     # Detailed documentation (optional)
   └── scripts/         # Utility scripts (optional)
       └── helper.py
   ```

**Skill File Format:** (see also [Claude Platform Docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview))

Every skill requires a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: my-skill
description: What this skill does and when to use it
license: MIT # Optional
---

# My Skill

## Instructions

Step-by-step guidance for Claude to follow...

## Examples

Concrete examples of using this skill...

For more details, see [REFERENCE.md](REFERENCE.md).
```

**Required YAML fields:**

- `name` (max 64 chars, lowercase letters/numbers/hyphens only)
- `description` (max 1024 chars, should include when to use the skill)

**Progressive Loading Example:**

```
pdf-skill/
├── SKILL.md           # Level 2: Main instructions
├── FORMS.md           # Level 3: Form-filling guide (loaded if referenced)
├── REFERENCE.md       # Level 3: API reference (loaded if needed)
└── scripts/
    └── fill_form.py   # Level 3: Executed via bash (code not in context)
```

- **Level 1**: Claude knows the skill exists and when to use it
- **Level 2**: When triggered, Claude reads SKILL.md instructions
- **Level 3**: Claude reads FORMS.md or runs fill_form.py only if the instructions reference them

**Automatic Discovery:**
Skills are automatically discovered and loaded when the application starts. No manual registration required.

### Conversations (`conversations/`)

Project-level conversation storage keeps chat history separate per project.

**Storage Priority:**

- **Project storage**: `./.exobrain/conversations/` (when `--project` flag is used)
- **Global storage**: `~/.exobrain/data/conversations/` (default)

**Loading Logic:**

- The storage location is determined at chat session start based on CLI flags
- If `--project` flag is used, conversations are stored in `./.exobrain/conversations/`
- If `--global` flag is used, conversations are stored in `~/.exobrain/data/conversations/`
- If neither flag is provided:
  - The system checks for an existing current session in both locations
  - If a project `.exobrain/` directory exists, project storage is preferred
  - Otherwise, global storage is used
- When loading a conversation by ID, both locations are searched (project first, then global)
- Messages are loaded from `messages.jsonl` (one JSON object per line)
- Token budget can limit how many messages are loaded (most recent first)

**Session Structure:**

```
conversations/
├── sessions.json           # Index of all sessions
└── sessions/
    └── 20260108_143022/   # Session ID (timestamp-based)
        ├── metadata.json   # Session info (title, model, timestamps, token count)
        └── messages.jsonl  # Message history (JSONL format, one message per line)
```

**Usage:**

- Use project storage: `exobrain chat --project` or `exobrain ask --project "question"`
- Use global storage: `exobrain chat --global` or `exobrain chat -g`
- List sessions: `exobrain history list`
- View session: `exobrain history show <session_id>`
- Delete session: `exobrain history delete <session_id>`

### Logs (`logs/`)

Project-level logs are automatically used when the `.exobrain/logs/` directory exists.

**Loading Priority:**

1. Project-level logs (`./.exobrain/logs/exobrain.log`) - if directory exists
2. Global logs (from config, typically `~/.exobrain/logs/exobrain.log`)

**Loading Logic:**

- At application startup, the system checks if `.exobrain/logs/` exists in the current directory
- If it exists, logs are written to `.exobrain/logs/exobrain.log`
- Otherwise, logs are written to the path specified in the configuration
- Log configuration (level, format, rotation) is still controlled by the config file
- Only the output path is automatically switched for project-level logging

Logs include:

- Application events and lifecycle
- Model API interactions
- Tool execution and results
- Configuration loading details
- Errors and warnings

## Creating a Project-Level Setup

### Manual Setup

```bash
# Create the .exobrain directory structure
mkdir -p .exobrain/{constitutions,skills,conversations,logs}

# Create a project-specific configuration
cat > .exobrain/config.yaml << EOF
models:
  default: "openai/gpt-4o-mini"

agent:
  system_prompt: "You are a helpful AI assistant for this specific project."
  constitution_file: "project-assistant"
EOF

# Create a project-specific constitution
cat > .exobrain/constitutions/project-assistant.md << EOF
# Project Assistant Constitution

You are an AI assistant specialized for this project...
EOF
```

### Using CLI Commands

```bash
# Initialize project configuration
exobrain config init

# Create project-specific constitution
exobrain constitution create project-assistant

# Start a project-scoped chat
exobrain chat --project
```

## Hierarchical Loading Summary

The hierarchical loading system ensures that more specific configurations override general ones:

1. **Configuration**: Default → User Global → **Project** (deep merge)
2. **Constitutions**: Package → User Global → Project Level → Project Dir → **Project Root** (last match wins)
3. **Skills**: Builtin (Anthropic, Obsidian) → Configured → User Global → **Project** (same name = override)
4. **Conversations**: Determined by CLI flag or automatic detection
5. **Logs**: Automatic detection (project dir exists → use project logs)

This design allows you to:

- Have sensible defaults that work everywhere
- Customize your personal preferences globally
- Override specific settings per project
- Share project configurations with your team

## Benefits of Project-Level Storage

1. **Isolation**: Each project has its own conversation history and settings
2. **Team Collaboration**: Share project-specific configurations via version control
3. **Context Preservation**: Conversations stay relevant to the project context
4. **Customization**: Project-specific AI personalities and skills
5. **Portability**: Move projects between machines with consistent AI behavior

## Best Practices

1. **Version Control**:

   - **DO commit**: `.exobrain/config.yaml`, `.exobrain/constitutions/`, `.exobrain/skills/`
   - **DON'T commit**: `.exobrain/conversations/`, `.exobrain/logs/` (add to `.gitignore`)

2. **Configuration**:

   - Keep project configs minimal (only override what's necessary)
   - Use environment variables for sensitive data (e.g., `${OPENAI_API_KEY}`)
   - Leverage deep merging to avoid duplicating entire config sections

3. **Constitutions**:

   - Create project-specific personalities for different contexts
   - Document the purpose and behavior guidelines clearly
   - Consider using project root `CONSTITUTION.md` for the primary project personality

4. **Skills**:

   - Create reusable skills for common project tasks
   - Share useful skills across projects via global skills directory
   - Use descriptive names to avoid conflicts

5. **Conversations**:
   - Use `--project` flag for project-related discussions
   - Use `--global` flag for general/personal conversations
   - Consider setting a default via config for consistent behavior

## Example .gitignore

```gitignore
# ExoBrain project-level data (user-specific)
.exobrain/conversations/
.exobrain/logs/

# Keep configuration and definitions (team-shared)
!.exobrain/config.yaml
!.exobrain/constitutions/
!.exobrain/skills/
```

## Troubleshooting

**Configuration not taking effect?**

- Check which config has highest priority: `exobrain config show`
- Verify your project config syntax with a YAML linter
- Look for error messages in logs about config validation

**Constitution not loading?**

- List available constitutions: `exobrain constitution list`
- Check the active constitution: `exobrain constitution show`
- Verify the file exists in the expected location

**Skills not available?**

- Ensure `config.skills.enabled: true`
- Check that `SKILL.md` files have valid YAML frontmatter
- Look for skill loading errors in the logs (use `--verbose` flag)

**Conversations in wrong location?**

- Use `--project` or `--global` flag explicitly
- Check current session location: `exobrain history list`
- Verify the `.exobrain/` directory exists for project storage
