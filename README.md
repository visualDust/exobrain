# ExoBrain

A toy AI assistant with tool calling capabilities and file system access, running in your terminal with or without TUI.

![ExoBrain Demo with GPT5 API](screenshot.gif)

![PyPI - Version](https://img.shields.io/pypi/v/exobrain)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

- 💻 **TUI Interface** - Terminal UI based on [Textual](https://github.com/Textualize/textual)
- 🤖 **Multi-Model Support** - [OpenAI](https://openai.com/api/), [Gemini](https://aistudio.google.com/), local models (hosted via [vLLM](https://github.com/vllm-project/vllm) etc)
- 🛠️ **Tools and Skills System** - File operations, web search, shell execution. Integrated [Anthropic Skills](https://github.com/anthropics/skills.git) and allow user self defined skills.
- 🔌 **MCP Support** - Model Context Protocol integration (currently integrated [Context7](https://context7.com/))
- 🔒 **Permission Control** - Fine-grained permission requests and access control
- 💬 **Session Management** - Project-level and global session storage
- 🎯 **Background Tasks** - Create, track, and manage background tasks.
- 📜 **Constitutional AI** - Customizable behavioral guidelines

For OpenAI apis, currently up to GPT-5 is supported, while GPT-5.2 is not (due to planning is not currently supported yet), but will be added in future updates.
The purpose of this project is to experiment with building a modular AI assistant that can integrate multiple models, and tools, with full control and transparency. Only use it for fun, not for production.

## Quick Start

### Installation

Install from pip:

```bash
pip install exobrain
```

Install from source (development):

```bash
git clone https://github.com/visualdust/exobrain.git
cd exobrain

git submodule update --init --recursive

# Install with uv
uv sync

# Or with pip
pip install -e .
```

### Setup

Run the configuration wizard:

```bash
exobrain config init
```

The wizard will guide you through:

- Selecting AI model providers (OpenAI, Gemini, or local models)
- Configuring API keys
- Setting up basic features and permissions

### Quick Start

```bash
exobrain chat # Start interactive chat
exobrain chat --model openai/gpt-5 # Use specific model
exobrain chat --continue # Resume last session
exobrain chat --help # see other chat options

# Manage sessions
exobrain sessions list
exobrain sessions show <session-id>
exobrain sessions --help # see other session commands

# Manage skills
exobrain skills # manage skills in tui
exobrain skills --help # see other skill commands

# Background tasks
exobrain tasks submit "read file ./data/report.pdf and summarize" # Submit a background task
exobrain tasks list # List background tasks and status
exobrain tasks show <task-id> # Show task details
exobrain tasks --help # see other task commands

# Manage constitution
exobrain constitution list # List all constitutions
exobrain constitution use <name> # Switch constitution
exobrain constitution --help # see other constitution commands

# Make current folder a project folder
exobrain init
```

---

## Documentation

Docs are comming soon!

---

## Permission System

ExoBrain requests permission for sensitive operations:

- **Once** - Grant for this operation only
- **Session** - Grant for this chat session
- **Always** - Add to config permanently

Example:

```
╭─────────────── Permission Request ───────────────╮
│ ⚠️  Permission Required                          │
│                                                  │
│   Tool      shell_execute                        │
│   Action    Execute shell command                │
│   Resource  git status                           │
│   Reason    Command not in allowed list          │
│                                                  │
│  Grant permission for this action?               │
│                                                  │
│    [y] Yes, once       [n] No                    │
│    [s] Yes, session    [a] Yes, always           │
╰──────────────────────────────────────────────────╯
```

---

## License

MIT License - see [LICENSE](LICENSE) file for details
Note that this project integrates third-party skills that may have their own licenses. See the [skills directory](exobrain/skills) for details.
