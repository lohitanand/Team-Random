"""Playbook lookup: the ONLY source of customer and team actions (CLAUDE.md §2.4, §7.6)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.app.schemas.alerts import PlaybookAction
from backend.app.schemas.evidence import Packet
from backend.app.schemas.taxonomy import FRICTION_TYPES

PLAYBOOK_PATH = Path(__file__).with_name("playbooks.yaml")


class Playbook:
    def __init__(self, data: dict[str, Any]) -> None:
        missing = set(FRICTION_TYPES) - set(data["frictions"])
        if missing:
            raise ValueError(f"playbook missing friction types: {sorted(missing)}")
        self.templates: dict[str, str] = data["templates"]
        self.customer: dict[str, list[PlaybookAction]] = {}
        self.team: dict[str, list[PlaybookAction]] = {}
        for friction, spec in data["frictions"].items():
            self.customer[friction] = [PlaybookAction(**a) for a in spec.get("customer_actions", [])]
            self.team[friction] = [PlaybookAction(**a) for a in spec["team_actions"]]
            for action in self.customer[friction] + self.team[friction]:
                if action.template_id not in self.templates:
                    raise ValueError(f"unknown template {action.template_id} for {action.id}")

    @property
    def action_ids(self) -> set[str]:
        return {a.id for actions in (*self.customer.values(), *self.team.values()) for a in actions}

    def action(self, action_id: str) -> PlaybookAction | None:
        for actions in (*self.customer.values(), *self.team.values()):
            for a in actions:
                if a.id == action_id:
                    return a
        return None

    @staticmethod
    def _matches(action: PlaybookAction, packet: Packet) -> bool:
        when = action.when
        if "packet_type" in when and when["packet_type"] != packet.packet_type:
            return False
        if "rule_any" in when and not set(when["rule_any"]) & set(packet.rule_flags):
            return False
        if "theme_any" in when and not set(when["theme_any"]) & set(packet.text_themes):
            return False
        return True

    def team_action(self, friction: str, packet: Packet) -> PlaybookAction:
        return next(a for a in self.team[friction] if self._matches(a, packet))

    def customer_action(self, friction: str, packet: Packet, moment: str) -> PlaybookAction | None:
        for action in self.customer[friction]:
            if action.moment == moment and self._matches(action, packet):
                return action
        return None

    def template(self, template_id: str) -> str:
        return self.templates[template_id]


@lru_cache
def get_playbook(path: Path = PLAYBOOK_PATH) -> Playbook:
    return Playbook(yaml.safe_load(path.read_text(encoding="utf-8")))


def default_moment(packet: Packet) -> str:
    """Recovery moment implied by the packet: post-purchase sessions, else after the session."""
    if packet.packet_type == "session" and packet.session_kind == "post_purchase":
        return "post_purchase"
    return "post_session"
