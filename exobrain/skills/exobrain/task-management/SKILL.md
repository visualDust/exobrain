---
name: task-management
description: Manage background tasks for long-running operations. Use when you need to offload time-consuming work like research, data processing, or complex analysis that would block the main conversation.
---

# Task Management Skill

This skill enables Claude Code to create and manage background tasks that run independently of the main conversation. Tasks continue running even after the CLI exits, allowing for true asynchronous execution.

## Overview

The task management system provides a daemon-based architecture for running long-running operations in the background. Tasks can be:

- **Agent tasks**: AI agents that perform research, analysis, or complex reasoning
- **Process tasks**: Shell commands or scripts that run as subprocesses

## When to Use Background Tasks

Use background tasks when:

- The operation will take more than a few seconds
- You want to continue the conversation while work happens in the background
- You need to run multiple operations in parallel
- The user explicitly requests background execution
- You're performing research, data processing, or complex analysis

**Don't use background tasks for:**

- Quick operations (< 5 seconds)
- Operations that need immediate results
- Simple file operations or queries

## Available Tools

### create_task

Create a new background task.

**Parameters:**

- `name` (required): Short name for the task
- `description` (optional): Detailed description of what the task should do
- `task_type` (required): Type of task - "agent" or "process"
- `config` (optional): Task-specific configuration
  - For agent tasks: `{"prompt": "Research Python async patterns", "max_iterations": 100}`
  - For process tasks: `{"command": "make build", "working_directory": "/path/to/project"}`

**Example:**

```json
{
  "name": "create_task",
  "input": {
    "name": "Research Python Async",
    "description": "Research best practices for Python async/await patterns",
    "task_type": "agent",
    "config": {
      "prompt": "Research Python async/await best practices, common pitfalls, and recommended patterns",
      "max_iterations": 50
    }
  }
}
```

### get_task_status

Get the current status and details of a background task.

**Parameters:**

- `task_id` (required): ID of the task to check

**Example:**

```json
{
  "name": "get_task_status",
  "input": {
    "task_id": "task-abc123def456"
  }
}
```

### list_tasks

List all background tasks with optional filtering.

**Parameters:**

- `status` (optional): Filter by status - "pending", "running", "completed", "failed", "cancelled", "interrupted"
- `task_type` (optional): Filter by type - "agent" or "process"
- `limit` (optional): Maximum number of tasks to return

**Example:**

```json
{
  "name": "list_tasks",
  "input": {
    "status": "running",
    "limit": 10
  }
}
```

### get_task_output

Get the output/logs of a background task.

**Parameters:**

- `task_id` (required): ID of the task
- `offset` (optional): Byte offset to start reading from
- `limit` (optional): Maximum number of bytes to read

**Example:**

```json
{
  "name": "get_task_output",
  "input": {
    "task_id": "task-abc123def456"
  }
}
```

### cancel_task

Cancel a running background task.

**Parameters:**

- `task_id` (required): ID of the task to cancel

**Example:**

```json
{
  "name": "cancel_task",
  "input": {
    "task_id": "task-abc123def456"
  }
}
```

## Task Lifecycle

1. **PENDING**: Task created but not yet started
2. **RUNNING**: Task is actively executing
3. **COMPLETED**: Task finished successfully
4. **FAILED**: Task encountered an error
5. **CANCELLED**: Task was cancelled by user or system
6. **INTERRUPTED**: Task was interrupted (e.g., daemon restart)

## Usage Patterns

### Pattern 1: Create and Monitor

```
1. Create task with create_task
2. Inform user that task is running in background
3. Periodically check status with get_task_status
4. When complete, retrieve output with get_task_output
5. Present results to user
```

### Pattern 2: Parallel Execution

```
1. Create multiple tasks for different subtasks
2. Use list_tasks to monitor all tasks
3. Check each task's status periodically
4. Collect results as tasks complete
5. Synthesize final answer from all results
```

### Pattern 3: Long-Running Research

```
1. Create agent task with research prompt
2. Inform user that research is ongoing
3. User can continue conversation
4. Periodically update user on progress
5. When complete, summarize findings
```

## Best Practices

### Task Naming

- Use descriptive names that explain what the task does
- Keep names concise (< 50 characters)
- Examples: "Research Python Async", "Build Docker Image", "Analyze Log Files"

### Task Descriptions

- Provide detailed descriptions for complex tasks
- Include context that might be useful later
- Explain expected outcomes

### Agent Task Configuration

- Set reasonable `max_iterations` (default: 500)
- Provide clear, specific prompts
- Include context and constraints in the prompt

### Process Task Configuration

- Use absolute paths for `working_directory`
- Ensure commands are safe and won't cause harm
- Consider timeout implications for long-running commands

### Monitoring

- Check task status periodically (every 5-10 seconds for active monitoring)
- Don't poll too frequently (< 1 second intervals)
- Inform user of progress updates
- Handle failures gracefully

### Error Handling

- Always check task status before retrieving output
- Handle FAILED status appropriately
- Provide meaningful error messages to user
- Consider retry logic for transient failures

## CLI Commands

Users can also manage tasks via CLI:

```bash
# Start daemon
exobrain task daemon start

# Submit task
exobrain task submit "Research Task" --type agent -d "<what should the agent do?>"

# List tasks
exobrain task list

# Show task details
exobrain task show <task_id>

# Follow task output in real-time
exobrain task follow <task_id>

# Cancel task
exobrain task cancel <task_id>

# Delete task
exobrain task delete <task_id>

# Stop daemon
exobrain task daemon stop
```

## Examples

### Example 1: Research Task

```
User: "Research the latest developments in quantum computing"
```
