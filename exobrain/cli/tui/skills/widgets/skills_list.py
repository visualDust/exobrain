"""Skills list widget for TUI."""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

from exobrain.skills.loader import Skill


class SkillItem(Static):
    """A single skill item in the list."""

    DEFAULT_CSS = """
    SkillItem {
        height: 3;
        padding: 0 1;
        border: none;
        background: $surface;
    }

    SkillItem:hover {
        background: $boost;
    }

    SkillItem.selected {
        background: $accent;
        color: $text;
    }

    SkillItem.disabled {
        color: $text-disabled;
    }
    """

    def __init__(self, skill: Skill, enabled: bool, selected: bool = False):
        """Initialize skill item.

        Args:
            skill: The skill object
            enabled: Whether the skill is enabled
            selected: Whether the item is currently selected
        """
        super().__init__()
        self.skill = skill
        self.enabled = enabled
        self.selected = selected

    def render(self) -> str:
        """Render the skill item."""
        # Status indicator
        status = "✓" if self.enabled else "✗"
        status_color = "green" if self.enabled else "red"

        # Selection indicator
        selector = "▶ " if self.selected else "  "

        # Skill name (truncate if too long)
        name = self.skill.name
        if len(name) > 30:
            name = name[:27] + "..."

        return f"{selector}[{status_color}]{status}[/] {name}"

    def on_click(self) -> None:
        """Handle click event."""
        self.post_message(SkillsList.SkillSelected(self.skill.name))


class SkillsList(VerticalScroll):
    """List of skills with toggle switches."""

    DEFAULT_CSS = """
    SkillsList {
        width: 40;
        border: solid $accent;
        background: $surface;
    }

    SkillsList > SkillItem {
        width: 100%;
    }
    """

    # Disable default j/k bindings from VerticalScroll
    BINDINGS = []

    selected_skill: reactive[str | None] = reactive(None)

    class SkillSelected(Message):
        """Message sent when a skill is selected."""

        def __init__(self, skill_name: str):
            """Initialize the message.

            Args:
                skill_name: Name of the selected skill
            """
            super().__init__()
            self.skill_name = skill_name

    class SkillToggled(Message):
        """Message sent when a skill is toggled."""

        def __init__(self, skill_name: str, enabled: bool):
            """Initialize the message.

            Args:
                skill_name: Name of the skill
                enabled: New enabled state
            """
            super().__init__()
            self.skill_name = skill_name
            self.enabled = enabled

    def __init__(self, skills: dict[str, Skill], disabled_skills: set[str]):
        """Initialize skills list.

        Args:
            skills: Dictionary of all skills
            disabled_skills: Set of disabled skill names
        """
        super().__init__()
        self.skills = skills
        self.disabled_skills = disabled_skills
        self.skill_items: dict[str, SkillItem] = {}

    def compose(self) -> ComposeResult:
        """Compose the skills list."""
        # Sort skills by name
        sorted_skills = sorted(self.skills.values(), key=lambda s: s.name.lower())

        for skill in sorted_skills:
            enabled = skill.name not in self.disabled_skills
            item = SkillItem(skill, enabled, selected=False)
            self.skill_items[skill.name] = item
            yield item

    def select_skill(self, skill_name: str) -> None:
        """Select a skill (called from parent/external).

        Args:
            skill_name: Name of the skill to select
        """
        self._update_selection(skill_name)

    def _update_selection(self, skill_name: str) -> None:
        """Update the selection state (internal).

        Args:
            skill_name: Name of the skill to select
        """
        # Update selected state for all items
        for name, item in self.skill_items.items():
            item.selected = name == skill_name
            item.refresh()

        self.selected_skill = skill_name

    def toggle_selected_skill(self) -> None:
        """Toggle the currently selected skill's enabled state."""
        if not self.selected_skill:
            return

        skill_name = self.selected_skill
        item = self.skill_items.get(skill_name)
        if not item:
            return

        # Toggle enabled state
        new_state = not item.enabled
        item.enabled = new_state

        # Update disabled_skills set
        if new_state:
            # Enabling the skill
            self.disabled_skills.discard(skill_name)
        else:
            # Disabling the skill
            self.disabled_skills.add(skill_name)

        # Refresh the item
        item.refresh()

        # Notify parent
        self.post_message(self.SkillToggled(skill_name, new_state))
