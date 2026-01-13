"""Skill detail widget for TUI."""

from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Markdown, Static

from exobrain.skills.loader import Skill


class SkillDetail(VerticalScroll):
    """Displays detailed information about a selected skill."""

    DEFAULT_CSS = """
    SkillDetail {
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }

    SkillDetail > .skill-header {
        background: $boost;
        padding: 1 2;
        margin-bottom: 1;
    }

    SkillDetail > .skill-meta {
        color: $text-muted;
        margin-bottom: 1;
    }

    SkillDetail > Markdown {
        margin-top: 1;
    }
    """

    current_skill: reactive[Skill | None] = reactive(None)

    def __init__(self):
        """Initialize skill detail widget."""
        super().__init__()
        self._header = Static(classes="skill-header")
        self._meta = Static(classes="skill-meta")
        self._markdown = Markdown()

    def compose(self):
        """Compose the widget."""
        yield self._header
        yield self._meta
        yield self._markdown

    def watch_current_skill(self, skill: Skill | None) -> None:
        """Update display when current skill changes.

        Args:
            skill: The skill to display
        """
        if skill is None:
            self._header.update("No skill selected")
            self._meta.update("")
            self._markdown.update("")
            return

        # Header with skill name
        header_text = f"[bold]{skill.name}[/bold]"
        self._header.update(header_text)

        # Metadata
        meta_lines = [f"[dim]Description:[/dim] {skill.description}"]

        if skill.license:
            meta_lines.append(f"[dim]License:[/dim] {skill.license}")

        if skill.source_path:
            meta_lines.append(f"[dim]Source:[/dim] {skill.source_path}")

        self._meta.update("\n".join(meta_lines))

        # Instructions as markdown
        if skill.instructions:
            self._markdown.update(skill.instructions)
        else:
            self._markdown.update("*No instructions provided*")

    def set_skill(self, skill: Skill | None) -> None:
        """Set the currently displayed skill.

        Args:
            skill: The skill to display
        """
        self.current_skill = skill
