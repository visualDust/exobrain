"""Skills management TUI application."""

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import Footer, Header, Static

from exobrain.cli.tui.skills.widgets import SkillDetail, SkillsList
from exobrain.config import get_user_config_path, load_config

if TYPE_CHECKING:
    from exobrain.config import Config
    from exobrain.skills.loader import SkillLoader


class SkillsApp(App):
    """TUI application for managing skills."""

    CSS = """
    Screen {
        layout: vertical;
    }

    Header {
        dock: top;
    }

    Footer {
        dock: bottom;
    }

    #main-container {
        height: 1fr;
    }

    #content {
        layout: horizontal;
        height: 1fr;
    }

    #help-text {
        dock: bottom;
        height: 3;
        background: $boost;
        color: $text-muted;
        padding: 1 2;
    }

    SkillsList {
        width: 40;
    }

    SkillDetail {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("w", "move_up", "Up", show=False),
        Binding("s", "move_down", "Down", show=False),
        Binding("j", "page_down", "Page Down", show=False),
        Binding("k", "page_up", "Page Up", show=False),
        Binding("space", "toggle_skill", "Toggle", show=True),
        Binding("ctrl+s", "save_config", "Save", show=True),
        Binding("r", "reload", "Reload", show=True),
    ]

    def __init__(
        self,
        config: "Config",
        skill_loader: "SkillLoader",
        config_scope: str = "user",
    ):
        """Initialize the skills management app.

        Args:
            config: Application configuration
            skill_loader: Loaded skills
            config_scope: Configuration scope ("user" or "project")
        """
        super().__init__()
        self.title = "ExoBrain - Skills Management"
        self.config = config
        self.skill_loader = skill_loader
        self.config_scope = config_scope

        # Get all skills (including disabled ones)
        self.all_skills = skill_loader.get_all_skills()
        self.disabled_skills = skill_loader.get_disabled_skills()

    def compose(self) -> ComposeResult:
        """Compose the application UI."""
        yield Header()

        with Container(id="main-container"):
            # Help text
            help_text = (
                "[bold]Keys:[/bold] w/s: Navigate | j/k: Page Up/Down | "
                "Space: Toggle | Ctrl+s: Save | r: Reload | q: Quit"
            )
            yield Static(help_text, id="help-text")

            # Main content area
            with Horizontal(id="content"):
                yield SkillsList(self.all_skills, self.disabled_skills)
                yield SkillDetail()

        yield Footer()

    def on_mount(self) -> None:
        """Handle mount event."""
        # Select first skill if available
        skills_list = self.query_one(SkillsList)
        if self.all_skills:
            first_skill_name = next(iter(sorted(self.all_skills.keys())))
            skills_list.select_skill(first_skill_name)
            self._update_detail(first_skill_name)

    def on_skills_list_skill_selected(self, message: SkillsList.SkillSelected) -> None:
        """Handle skill selection.

        Args:
            message: The skill selected message
        """
        # Update the list selection (for mouse clicks)
        skills_list = self.query_one(SkillsList)
        skills_list.select_skill(message.skill_name)
        # Update detail panel
        self._update_detail(message.skill_name)

    def on_skills_list_skill_toggled(self, message: SkillsList.SkillToggled) -> None:
        """Handle skill toggle.

        Args:
            message: The skill toggled message
        """
        # Update config
        if message.enabled:
            self.notify(f"Enabled: {message.skill_name}", severity="information")
        else:
            self.notify(f"Disabled: {message.skill_name}", severity="warning")

    def _update_detail(self, skill_name: str) -> None:
        """Update the detail panel with selected skill.

        Args:
            skill_name: Name of the skill to display
        """
        skill = self.all_skills.get(skill_name)
        detail = self.query_one(SkillDetail)
        detail.set_skill(skill)

    def action_move_up(self) -> None:
        """Move selection up."""
        skills_list = self.query_one(SkillsList)

        if not skills_list.selected_skill:
            # Select first item
            if self.all_skills:
                first_skill = next(iter(sorted(self.all_skills.keys())))
                skills_list.select_skill(first_skill)
                self._update_detail(first_skill)
            return

        skill_names = list(sorted(self.all_skills.keys()))
        current_index = skill_names.index(skills_list.selected_skill)

        if current_index > 0:
            new_skill = skill_names[current_index - 1]
            skills_list.select_skill(new_skill)
            self._update_detail(new_skill)
            # Scroll into view
            if new_skill in skills_list.skill_items:
                skills_list.scroll_to_widget(skills_list.skill_items[new_skill])

    def action_move_down(self) -> None:
        """Move selection down."""
        skills_list = self.query_one(SkillsList)

        if not skills_list.selected_skill:
            # Select first item
            if self.all_skills:
                first_skill = next(iter(sorted(self.all_skills.keys())))
                skills_list.select_skill(first_skill)
                self._update_detail(first_skill)
            return

        skill_names = list(sorted(self.all_skills.keys()))
        current_index = skill_names.index(skills_list.selected_skill)

        if current_index < len(skill_names) - 1:
            new_skill = skill_names[current_index + 1]
            skills_list.select_skill(new_skill)
            self._update_detail(new_skill)
            # Scroll into view
            if new_skill in skills_list.skill_items:
                skills_list.scroll_to_widget(skills_list.skill_items[new_skill])

    def action_page_up(self) -> None:
        """Scroll detail panel up."""
        detail = self.query_one(SkillDetail)
        detail.action_page_up()

    def action_page_down(self) -> None:
        """Scroll detail panel down."""
        detail = self.query_one(SkillDetail)
        detail.action_page_down()

    def action_toggle_skill(self) -> None:
        """Toggle the currently selected skill."""
        skills_list = self.query_one(SkillsList)
        skills_list.toggle_selected_skill()

    def action_save_config(self) -> None:
        """Save the current disabled skills configuration."""
        try:
            # Determine config file path based on scope
            if self.config_scope == "project":
                config_path = Path.cwd() / ".exobrain" / "config.yaml"
                # Ensure directory exists
                config_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                config_path = get_user_config_path()
                # Ensure directory exists
                config_path.parent.mkdir(parents=True, exist_ok=True)

            # Load existing config or create new one
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = yaml.safe_load(f) or {}
            else:
                config_data = {}

            # Update disabled_skills
            if "skills" not in config_data:
                config_data["skills"] = {}

            skills_list = self.query_one(SkillsList)
            config_data["skills"]["disabled_skills"] = sorted(list(skills_list.disabled_skills))

            # Write config
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

            enabled_count = len(self.all_skills) - len(skills_list.disabled_skills)
            total_count = len(self.all_skills)

            self.notify(
                f"Saved to {config_path.name} " f"({enabled_count}/{total_count} skills enabled)",
                severity="information",
                timeout=3,
            )
        except Exception as e:
            self.notify(f"Error saving config: {e}", severity="error", timeout=5)

    def action_reload(self) -> None:
        """Reload configuration and skills."""
        try:
            # Reload config
            self.config, _ = load_config()

            # Get updated disabled skills
            from exobrain.skills.loader import load_default_skills

            self.skill_loader = load_default_skills(self.config)
            self.all_skills = self.skill_loader.get_all_skills()
            self.disabled_skills = self.skill_loader.get_disabled_skills()

            # Reload UI
            # Note: In a real implementation, you'd need to rebuild the widgets
            # For now, just notify
            self.notify(
                f"Reloaded: {len(self.all_skills)} skills found",
                severity="information",
            )
        except Exception as e:
            self.notify(f"Error reloading: {e}", severity="error")
