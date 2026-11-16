"""Which plugins this instance offers (config/plugins.yaml, docs/02 "Plugin architecture").

    enabled: [namespaces, quotas, tiers, directory]
    overrides:                 # keyed by instance, then environment
      nonprod:
        dev:
          disabled: [namespaces]

`enabled` names the plugins whose routes the app mounts: a plugin that is not in the list has no route, no tag
and no line in the OpenAPI document. An override stops the writes of an enabled plugin in one environment of one
instance: the write pipeline answers 422 `plugin-disabled` there, and the reads stay.

The file is optional. Without it every built-in plugin is enabled and nothing is overridden, which is what cmapi did
before the file was read. With it, each mistake stops startup (core/config.py collects them): a name that is not a
built-in plugin, a core router, an environment that the instance does not serve, a key that the file does not define,
and an override that would change nothing (the plugin is not enabled, or it has no write).
Only the block of this instance is checked, because the file is the same on every instance and no instance knows the
environments of another.

Plugins from other packages (the `cmapi.plugins` entry-point group of docs/02) are not discovered yet.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any, Mapping

# Each built-in plugin and where its router is, in the entry-point form `module:attribute`.
BUILT_IN: dict[str, str] = {
    "namespaces": "cmapi.plugins.namespaces.router:router",
    "tiers": "cmapi.plugins.tiers:router",
    "directory": "cmapi.plugins.directory:router",
    "quotas": "cmapi.plugins.quotas:router",
}
# The built-in plugins with a write, which is what an override stops. tests/service/test_plugins_switch.py holds this to the routers.
WRITERS: frozenset[str] = frozenset({"namespaces"})
# The routers of cmapi.routers. They are the service itself, so plugins.yaml cannot name them.
CORE: frozenset[str] = frozenset({"core", "requests", "admin"})


class PluginSwitch:
    """The enabled plugins of one instance, and the environments where an override stops a plugin's writes."""

    def __init__(self, raw: Mapping[str, Any] | None, instance: str, allowed_environments: set[str]):
        self.configured = raw is not None
        problems: list[str] = []
        raw = raw if raw is not None else {"enabled": list(BUILT_IN)}
        if not isinstance(raw, Mapping):
            raise ValueError("the file must be a mapping with the key `enabled`")
        for key in sorted(set(raw) - {"enabled", "overrides"}, key=repr):
            problems.append(f"unknown key {key!r}: the file has `enabled` and `overrides`")
        known_before = len(problems)
        self.enabled: tuple[str, ...] = tuple(self._names(raw.get("enabled"), "enabled", problems))
        enabled_is_valid = len(problems) == known_before
        self._disabled: dict[str, frozenset[str]] = {}
        overrides = raw.get("overrides")
        if overrides is None:
            overrides = {}
        if not isinstance(overrides, Mapping):
            problems.append("overrides: must be a mapping of instance, then environment")
            overrides = {}
        for key in overrides:
            if not isinstance(key, str):
                problems.append(f"overrides.{key}: the name of an instance must be a text")
        mine = overrides.get(instance)
        if mine is None:
            mine = {}
        if not isinstance(mine, Mapping):
            problems.append(f"overrides.{instance}: must be a mapping of environment to `disabled`")
            mine = {}
        for env, block in mine.items():
            where = f"overrides.{instance}.{env}"
            if not isinstance(env, str):
                problems.append(f"{where}: the name of an environment must be a text")
                continue
            if env not in allowed_environments:
                problems.append(f"{where}: {env} is not in allowedEnvironments {sorted(allowed_environments)}")
                continue
            if not isinstance(block, Mapping) or set(block) != {"disabled"}:
                problems.append(f"{where}: must have the one key `disabled`")
                continue
            names = self._names(block["disabled"], f"{where}.disabled", problems)
            for name in names:
                if enabled_is_valid and name in BUILT_IN and name not in self.enabled:
                    problems.append(f"{where}.disabled: {name} is not in `enabled`, so the override changes nothing")
                elif name in BUILT_IN and name not in WRITERS:
                    problems.append(f"{where}.disabled: {name} has no write, so the override changes nothing")
            self._disabled[env] = frozenset(names)
        if problems:
            raise ValueError("; ".join(problems))

    @staticmethod
    def _names(value: Any, where: str, problems: list[str]) -> list[str]:
        """The plugin names of one list, each a built-in plugin and each named one time."""
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            problems.append(f"{where}: must be a list of plugin names")
            return []
        for name in dict.fromkeys(value):
            if value.count(name) > 1:
                problems.append(f"{where}: {name} is named {value.count(name)} times")
            if name in CORE:
                problems.append(f"{where}: {name} is a part of the core and cannot be switched")
            elif name not in BUILT_IN:
                problems.append(f"{where}: unknown plugin {name!r} (the plugins of this build are {sorted(BUILT_IN)})")
        return list(dict.fromkeys(value))

    def is_enabled(self, plugin: str) -> bool:
        return plugin in self.enabled

    def offers(self, plugin: str, environment: str) -> bool:
        """Whether the plugin takes writes in the environment: it is enabled, and no override disables it there."""
        return plugin in self.enabled and plugin not in self._disabled.get(environment, ())

    def disabled_environments(self, plugin: str) -> list[str]:
        return sorted(env for env, names in self._disabled.items() if plugin in names)

    def routers(self) -> list[Any]:
        """The router of each enabled plugin, in the order of BUILT_IN, so the order of `enabled` never changes the routes."""
        out = []
        for name, target in BUILT_IN.items():
            if name in self.enabled:
                module, _, attribute = target.partition(":")
                out.append(getattr(import_module(module), attribute))
        return out
