"""Deterministic, persistent file categorization rules for STEWARD."""

import logging
import os
import re
import threading
from typing import Dict, List, Optional

import yaml


logger = logging.getLogger(__name__)


class RulesEngine:
    """Load, match, and persist deterministic filename-to-category rules.

    The YAML file contains a ``rules`` list. Each rule has a regular-expression
    ``pattern``, a destination category ``target``, and an integer ``priority``.
    Higher-priority rules are evaluated first.
    """

    def __init__(self, rules_path: str = "rules.yaml"):
        self.rules_path = os.path.abspath(os.fspath(rules_path))
        self._lock = threading.RLock()
        self.last_matched_rule: Optional[Dict] = None
        self._rules = self._load_rules()

    def _load_rules(self) -> List[Dict]:
        if not os.path.exists(self.rules_path):
            self._rules = []
            self._save_rules()
            return self._rules

        try:
            with open(self.rules_path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Could not load rules from '%s': %s", self.rules_path, exc)
            return []

        if isinstance(data, dict):
            raw_rules = data.get("rules", [])
        elif isinstance(data, list):
            # Accept an early top-level-list format for forward compatibility.
            raw_rules = data
        else:
            raw_rules = []

        if not isinstance(raw_rules, list):
            logger.warning("Rules file '%s' does not contain a rule list", self.rules_path)
            return []

        valid_rules = []
        for rule in raw_rules:
            if not isinstance(rule, dict):
                continue
            pattern = rule.get("pattern")
            target = rule.get("target")
            priority = rule.get("priority", 100)
            if not isinstance(pattern, str) or not pattern:
                continue
            if not isinstance(target, str) or not target:
                continue
            if isinstance(priority, bool) or not isinstance(priority, int):
                continue
            try:
                re.compile(pattern)
            except re.error as exc:
                logger.warning("Ignoring invalid rule pattern '%s': %s", pattern, exc)
                continue
            valid_rules.append({
                "pattern": pattern,
                "target": target,
                "priority": priority,
            })
        return valid_rules

    def _save_rules(self) -> None:
        parent = os.path.dirname(self.rules_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        temporary_path = self.rules_path + ".tmp"
        with open(temporary_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                {"rules": self._rules},
                handle,
                sort_keys=False,
                allow_unicode=True,
            )
        os.replace(temporary_path, self.rules_path)

    def match_rule(self, filename: str) -> Optional[str]:
        """Return the first matching category, or ``None`` when no rule applies."""
        self.last_matched_rule = None
        if not isinstance(filename, str):
            return None

        rules = sorted(
            self.get_all_rules(),
            key=lambda rule: rule.get("priority", 100),
            reverse=True,
        )
        for rule in rules:
            try:
                matched = re.match(rule["pattern"], filename) is not None
            except (re.error, KeyError, TypeError) as exc:
                logger.warning(
                    "Ignoring invalid rule pattern '%s' while matching '%s': %s",
                    rule.get("pattern"),
                    filename,
                    exc,
                )
                continue
            if matched:
                self.last_matched_rule = dict(rule)
                return rule["target"]
        return None

    def add_rule(self, pattern: str, target: str, priority: int = 100) -> Dict:
        """Add a rule and persist it to YAML."""
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("Rule pattern must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise ValueError("Rule target must be a non-empty string")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("Rule priority must be an integer")
        re.compile(pattern)

        with self._lock:
            rule = {"pattern": pattern, "target": target, "priority": priority}
            self._rules.append(rule)
            self._save_rules()
        return dict(rule)

    def delete_rule(self, pattern: str) -> bool:
        """Delete the first rule with ``pattern`` and persist the change."""
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("Rule pattern must be a non-empty string")

        with self._lock:
            for index, rule in enumerate(self._rules):
                if rule.get("pattern") == pattern:
                    self._rules.pop(index)
                    self._save_rules()
                    return True
        return False

    def get_all_rules(self) -> List[Dict]:
        """Return a copy of the current rules in insertion order."""
        with self._lock:
            return [dict(rule) for rule in self._rules]
