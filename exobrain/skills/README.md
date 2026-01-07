# Skills 开发指南

Skills 是 ExoBrain 的可扩展技能模块系统，允许你创建自定义的功能和工作流。

## 目录结构

```
exobrain/skills/
├── README.md              # 本文档
├── __init__.py           # Skills 加载器
├── builtin/              # 内置 Skills
│   ├── __init__.py
│   ├── note_manager.py   # 笔记管理
│   ├── habit_tracker.py  # 习惯追踪
│   └── task_planner.py   # 任务规划
└── loader.py             # Skills 加载机制
```

用户自定义 Skills 应放在 `~/.exobrain/skills/` 目录下。

## Skill 定义格式

每个 Skill 由一个 YAML 配置文件和可选的 Python 实现文件组成。

### 基本 YAML 格式

```yaml
# ~/.exobrain/skills/my_skill.yaml
name: my_skill
version: 1.0.0
description: 这是一个示例 Skill

# 触发词：当用户消息包含这些关键词时，Skill 会被激活
triggers:
  - 关键词1
  - 关键词2

# Skill 提供的工具
tools:
  - name: tool_name
    description: 工具描述
    parameters:
      param1:
        type: string
        description: 参数描述
        required: true
      param2:
        type: integer
        description: 另一个参数
        required: false
    implementation: module.function_name

# 系统提示和示例
prompts:
  system: |
    你是一个专门处理某项任务的助手。
    你可以使用以下工具：...

  examples:
    - user: 用户输入示例
      assistant: 助手回复示例
      tool_call:
        name: tool_name
        arguments:
          param1: value1

# 配置项
configuration:
  storage_path: ~/.exobrain/data/my_skill
  max_items: 100
```

## Skill 实现

### Python 实现文件

创建 `~/.exobrain/skills/my_skill.py`:

```python
"""My custom skill implementation."""

from typing import Any
import json
from pathlib import Path


class MySkill:
    """My skill implementation."""

    def __init__(self, config: dict[str, Any]):
        """Initialize the skill.

        Args:
            config: Configuration from YAML file
        """
        self.config = config
        self.storage_path = Path(config.get("storage_path", "~/.exobrain/data/my_skill")).expanduser()
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def my_tool(self, param1: str, param2: int = 0) -> dict[str, Any]:
        """Tool implementation.

        Args:
            param1: First parameter
            param2: Second parameter

        Returns:
            Result dictionary
        """
        # Your implementation here
        result = {
            "success": True,
            "message": f"Processed {param1} with {param2}",
            "data": {}
        }
        return result

    def save_data(self, data: dict[str, Any]) -> None:
        """Save data to storage."""
        file_path = self.storage_path / "data.json"
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_data(self) -> dict[str, Any]:
        """Load data from storage."""
        file_path = self.storage_path / "data.json"
        if file_path.exists():
            with open(file_path, "r") as f:
                return json.load(f)
        return {}
```

## 内置 Skills

### 1. Note Manager

管理笔记和文档。

**功能**:

- 创建、编辑、删除笔记
- 搜索笔记
- 分类和标签

### 2. Habit Tracker

追踪日常习惯。

**功能**:

- 记录习惯完成情况
- 统计和分析
- 提醒功能

### 3. Task Planner

任务和项目规划。

**功能**:

- 创建任务
- 设置优先级和截止日期
- 任务分解

## Skills 注册

Skills 在启动时自动加载。加载顺序：

1. 扫描 `~/.exobrain/skills/` 目录
2. 查找 `.yaml` 文件
3. 加载对应的 Python 实现（如果存在）
4. 注册工具到 Agent

## 最佳实践

### 1. 命名规范

- Skill 名称使用小写字母和下划线
- 工具名称清晰描述功能
- 参数名称语义化

### 2. 错误处理

```python
async def my_tool(self, param: str) -> dict[str, Any]:
    try:
        # Your logic
        result = process(param)
        return {"success": True, "data": result}
    except ValueError as e:
        return {"success": False, "error": f"Invalid parameter: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {e}"}
```

### 3. 数据持久化

- 使用 JSON 或 SQLite 存储数据
- 定期备份重要数据
- 提供数据导入导出功能

### 4. 性能考虑

- 避免阻塞操作，使用 async/await
- 大量数据使用分页
- 缓存频繁访问的数据

### 5. 测试

为每个 Skill 创建测试：

```python
# tests/test_my_skill.py
import pytest
from exobrain.skills.my_skill import MySkill


@pytest.mark.asyncio
async def test_my_tool():
    skill = MySkill({"storage_path": "/tmp/test"})
    result = await skill.my_tool("test", 42)
    assert result["success"] is True
```

## Skill 示例

### 计时器 Skill

`~/.exobrain/skills/timer.yaml`:

```yaml
name: timer
version: 1.0.0
description: 设置和管理计时器

triggers:
  - 计时
  - 定时
  - 提醒

tools:
  - name: set_timer
    description: 设置一个计时器
    parameters:
      duration:
        type: integer
        description: 持续时间（秒）
        required: true
      label:
        type: string
        description: 计时器标签
        required: false
    implementation: timer.set_timer

prompts:
  system: |
    你是一个计时器助手。你可以帮助用户设置计时器。
    当用户说"设置一个5分钟的计时器"时，将5分钟转换为300秒。
```

`~/.exobrain/skills/timer.py`:

```python
"""Timer skill implementation."""

import asyncio
from datetime import datetime, timedelta
from typing import Any


class Timer:
    """Timer skill."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.timers: dict[str, datetime] = {}

    async def set_timer(self, duration: int, label: str = "timer") -> dict[str, Any]:
        """Set a timer.

        Args:
            duration: Duration in seconds
            label: Timer label

        Returns:
            Result with timer info
        """
        end_time = datetime.now() + timedelta(seconds=duration)
        self.timers[label] = end_time

        # Schedule the timer (simplified, in production use a proper scheduler)
        asyncio.create_task(self._run_timer(duration, label))

        return {
            "success": True,
            "message": f"Timer '{label}' set for {duration} seconds",
            "end_time": end_time.isoformat()
        }

    async def _run_timer(self, duration: int, label: str) -> None:
        """Run timer in background."""
        await asyncio.sleep(duration)
        print(f"⏰ Timer '{label}' finished!")
        if label in self.timers:
            del self.timers[label]
```

## 调试 Skills

启用 verbose 模式查看 Skill 加载和执行日志：

```bash
uv run exobrain --verbose --config config.yaml chat
```

## 常见问题

### Q: Skill 没有被加载？

A: 检查以下内容：

- YAML 文件格式是否正确
- 文件名和 `name` 字段是否匹配
- Python 实现文件是否在正确的位置
- 查看日志中的错误信息

### Q: 如何禁用某个 Skill？

A: 在配置文件中设置：

```yaml
skills:
  enabled: true
  disabled_skills:
    - skill_name
```

### Q: Skill 之间如何共享数据？

A: 使用共享存储或通过 Agent 的上下文：

```python
# 存储到共享位置
shared_path = Path("~/.exobrain/data/shared").expanduser()

# 或通过返回值传递
return {"success": True, "shared_data": data}
```

## 贡献 Skill

如果你创建了有用的 Skill，欢迎分享：

1. 确保代码质量和文档完整
2. 添加测试用例
3. 提交到社区 Skill 仓库

## 下一步

- 查看 `examples/skills/` 中的更多示例
- 阅读 API 参考文档
- 加入社区讨论
