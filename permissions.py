"""Typed runtime permissions shared by Agents, DAG nodes and Task Bench."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


class PermissionClass(str, Enum):
    READ = "read"
    WRITE = "write"
    PROCESS = "process"
    NETWORK = "network"
    MUTATION = "mutation"
    SECRET = "secret"


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


READ_TOOLS = {"read_file", "search_files", "glob_search", "ls"}
WRITE_TOOLS = {"write_file", "patch_file", "multi_edit", "apply_patch"}
PROCESS_TOOLS = {"run_command", "exec_command", "write_stdin"}
PYTHON_RUNTIME_TOOLS = {"python_node"}
NETWORK_TOOLS = {"browser", "fetch_url", "fetch_urls", "web_search"}
PURE_TOOLS = {
    "activate_capability", "check_command_status", "evaluate_session", "finish",
    "list_harness_templates", "list_sessions", "search_capabilities", "stop_command",
    "submit_result", "update_plan",
}
MUTATION_TOOLS = {
    "copy_identity", "create_agent_system", "create_harness", "create_identity",
    "create_knowledge", "create_skill", "create_tool", "design_harness", "evolve_capabilities",
    "manage_harness", "modify_harness", "modify_identity", "run_evolution_cycle",
    "run_harness_test",
}
MUTATION_ARTIFACTS = {
    "copy_identity": {"identity"},
    "create_agent_system": {"agent", "identity", "harness"},
    "create_harness": {"harness"},
    "create_identity": {"identity"},
    "create_knowledge": {"knowledge", "identity"},
    "create_skill": {"skill", "identity"},
    "create_tool": {"skill", "identity"},
    "design_harness": {"harness"},
    "evolve_capabilities": {"skill", "knowledge", "identity"},
    "manage_harness": {"harness"},
    "modify_harness": {"harness"},
    "modify_identity": {"identity"},
    "run_evolution_cycle": {"identity", "harness"},
    "run_harness_test": {"harness"},
}
PATH_ARGUMENTS = {
    "read_file": ("file_path",), "write_file": ("file_path",),
    "patch_file": ("file_path",), "multi_edit": ("file_path",),
    "search_files": ("path",), "glob_search": ("path",), "ls": ("path",),
    "run_command": ("cwd",), "exec_command": ("workdir",),
    "create_harness": ("workspace",),
}
SENSITIVE_FILE_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    ".npmrc", ".pypirc", ".netrc", ".git-credentials", "auth.json",
    "id_rsa", "id_ed25519", "credentials", "credentials.json",
}
SENSITIVE_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}
SENSITIVE_PARENT_NAMES = {".ssh", ".aws", ".azure", ".docker", ".gnupg"}


def is_sensitive_path(path: Path) -> bool:
    lower_name = path.name.lower()
    parent_names = {part.lower() for part in path.parts[:-1]}
    return (
        lower_name in SENSITIVE_FILE_NAMES
        or lower_name.startswith(".env.")
        or path.suffix.lower() in SENSITIVE_SUFFIXES
        or bool(parent_names & SENSITIVE_PARENT_NAMES)
    )

_NETWORK_COMMAND_RE = re.compile(
    r"(?:^|[;&|\s])(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|ssh|scp|sftp|ftp|nc|ncat|telnet)\b",
    re.IGNORECASE,
)
_PACKAGE_INSTALL_RE = re.compile(
    r"(?:^|[;&|\s])(?:pip(?:3)?|python\s+-m\s+pip|npm|pnpm|yarn|bun|cargo|go)\s+(?:install|add|get)\b|"
    r"(?:^|[;&|\s])(?:apt(?:-get)?|dnf|yum|pacman|brew|choco|winget)\s+(?:install|add)\b",
    re.IGNORECASE,
)
_DESTRUCTIVE_COMMAND_RE = re.compile(
    r"\b(?:rm\s+-[^\r\n]*r|rmdir\s+(?:/s|-[^\r\n]*r)|Remove-Item\b[^\r\n]*(?:-Recurse|-Force)|"
    r"del\s+(?:/s|/q)|git\s+(?:reset\s+--hard|clean\s+-[^\r\n]*f|checkout\s+--|restore\b)|"
    r"git\s+(?:branch|tag)\s+-[dD]|DROP\s+(?:DATABASE|TABLE)|TRUNCATE\s+TABLE)\b",
    re.IGNORECASE,
)
_CRITICAL_COMMAND_RE = re.compile(
    r"\b(?:format(?:\.com)?|diskpart|mkfs(?:\.[a-z0-9]+)?|fdisk|parted|shutdown|reboot|halt|poweroff|"
    r"bcdedit|reg\s+(?:delete|add)|net\s+user|useradd|userdel|chmod\s+-R\s+777|chown\s+-R|"
    r"git\s+push\b[^\r\n]*(?:--force|-f\b))\b|\bdd\s+if=|:\(\)\s*\{",
    re.IGNORECASE,
)
_SHELL_INDIRECTION_RE = re.compile(
    r"\b(?:powershell|pwsh)\b[^\r\n]*(?:-enc(?:odedcommand)?\b|-executionpolicy\s+bypass)|"
    r"\b(?:cmd(?:\.exe)?\s+/c|sh\s+-c|bash\s+-c|eval\s+)\b",
    re.IGNORECASE,
)
_CREDENTIAL_COMMAND_RE = re.compile(
    r"(?:\.env(?:\.|\b)|id_rsa|id_ed25519|credentials(?:\.json)?|Get-ChildItem\s+Env:|"
    r"\b(?:env|printenv)\b|\$env:[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_][A-Za-z0-9_]*%)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RiskFinding:
    code: str
    level: RiskLevel
    summary: str


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel = RiskLevel.LOW
    findings: tuple[RiskFinding, ...] = ()

    def public(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "summary": "; ".join(item.summary for item in self.findings),
            "findings": [
                {"code": item.code, "level": item.level.value, "summary": item.summary}
                for item in self.findings
            ],
        }


def _risk(*findings: RiskFinding) -> RiskAssessment:
    order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
    level = max((item.level for item in findings), key=lambda value: order[value], default=RiskLevel.LOW)
    return RiskAssessment(level, tuple(findings))


def assess_tool_risk(
    name: str,
    arguments: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> RiskAssessment:
    """Classify user-impacting intent independently from model instructions.

    This is deliberately conservative.  A finding does not itself execute or
    block anything; :class:`RuntimePolicy` maps it to allow/ask/deny.
    """

    arguments = arguments or {}
    short = short_tool_name(name)
    findings: list[RiskFinding] = []
    if short in PYTHON_RUNTIME_TOOLS:
        findings.append(RiskFinding(
            "python.in_process",
            RiskLevel.CRITICAL,
            "Python node executes arbitrary Harness code inside the EgoAgent backend process",
        ))
    elif short in PROCESS_TOOLS:
        command = str(arguments.get("command", ""))
        if _NETWORK_COMMAND_RE.search(command):
            findings.append(RiskFinding("command.network", RiskLevel.HIGH, "Command can access the network"))
        if _PACKAGE_INSTALL_RE.search(command):
            findings.append(RiskFinding("command.install", RiskLevel.HIGH, "Command installs or changes dependencies"))
        if _DESTRUCTIVE_COMMAND_RE.search(command):
            findings.append(RiskFinding("command.destructive", RiskLevel.HIGH, "Command can delete or irreversibly replace data"))
        if _CRITICAL_COMMAND_RE.search(command):
            findings.append(RiskFinding("command.system", RiskLevel.CRITICAL, "Command can alter the system, disk, users, registry, or remote history"))
        if _SHELL_INDIRECTION_RE.search(command):
            findings.append(RiskFinding("command.indirect", RiskLevel.HIGH, "Command uses an encoded or nested shell that is difficult to review"))
        if _CREDENTIAL_COMMAND_RE.search(command):
            findings.append(RiskFinding("command.credentials", RiskLevel.CRITICAL, "Command may read credentials or environment secrets"))
        if not findings:
            findings.append(RiskFinding("command.execute", RiskLevel.MEDIUM, "Command executes with the selected sandbox boundary"))
    elif short in WRITE_TOOLS:
        findings.append(RiskFinding("workspace.write", RiskLevel.MEDIUM, "Tool changes a workspace file"))
    elif short in NETWORK_TOOLS:
        findings.append(RiskFinding("tool.network", RiskLevel.HIGH, "Tool sends a request outside the workspace"))
    elif short in MUTATION_TOOLS:
        findings.append(RiskFinding("agent.mutation", RiskLevel.HIGH, "Tool changes a reusable Agent, Identity, Skill, Knowledge, or Harness"))
    elif short not in READ_TOOLS and short not in PURE_TOOLS:
        declared = (metadata or {}).get("permissions")
        if not declared:
            findings.append(RiskFinding("tool.undeclared", RiskLevel.HIGH, "Executable tool has no declared permission metadata"))
    return _risk(*findings)


def short_tool_name(name: str) -> str:
    return str(name or "").split(":")[-1]


def classify_tool(
    name: str,
    metadata: Optional[Mapping[str, Any]] = None,
    arguments: Optional[Mapping[str, Any]] = None,
) -> set[PermissionClass]:
    result: set[PermissionClass] = set()
    declared = (metadata or {}).get("permissions")
    if isinstance(declared, str):
        declared = [declared]
    if isinstance(declared, list) and declared:
        for value in declared:
            try:
                result.add(PermissionClass(str(value).lower()))
            except ValueError:
                continue
        # Declared metadata may add classes, but it cannot hide dynamic command
        # intent such as network access or credential reads.
    short = short_tool_name(name)
    if short in READ_TOOLS:
        result.add(PermissionClass.READ)
    if short in WRITE_TOOLS:
        result.add(PermissionClass.WRITE)
    if short in PROCESS_TOOLS:
        result.add(PermissionClass.PROCESS)
    if short in PYTHON_RUNTIME_TOOLS:
        result.add(PermissionClass.PROCESS)
    if short in NETWORK_TOOLS:
        result.add(PermissionClass.NETWORK)
    if short in MUTATION_TOOLS:
        result.add(PermissionClass.MUTATION)
    if short in PROCESS_TOOLS:
        command = str((arguments or {}).get("command", ""))
        if _NETWORK_COMMAND_RE.search(command):
            result.add(PermissionClass.NETWORK)
        if _CREDENTIAL_COMMAND_RE.search(command):
            result.add(PermissionClass.SECRET)
    return result or {PermissionClass.READ}


@dataclass(frozen=True)
class PermissionRule:
    decision: PermissionDecision
    permission_class: Optional[PermissionClass] = None
    tool: str = "*"
    arguments: Mapping[str, str] = field(default_factory=dict)
    modes: tuple[str, ...] = ()
    workspace: str = "*"
    reason: str = ""

    def matches(self, *, mode: str, workspace: Path, tool: str, permission_class: PermissionClass, arguments: Mapping[str, Any]) -> bool:
        if self.permission_class is not None and self.permission_class != permission_class:
            return False
        if self.modes and mode not in self.modes:
            return False
        if not fnmatch.fnmatchcase(str(workspace), self.workspace):
            return False
        if not fnmatch.fnmatchcase(short_tool_name(tool), self.tool) and not fnmatch.fnmatchcase(tool, self.tool):
            return False
        for key, pattern in self.arguments.items():
            if not fnmatch.fnmatchcase(str(arguments.get(key, "")), str(pattern)):
                return False
        return True


@dataclass(frozen=True)
class PolicyDecision:
    decision: PermissionDecision
    permission_classes: tuple[PermissionClass, ...]
    reason: str
    matched_rule: Optional[int] = None
    risk: RiskAssessment = field(default_factory=RiskAssessment)

    @property
    def allowed(self) -> bool:
        return self.decision == PermissionDecision.ALLOW


@dataclass
class RuntimePolicy:
    workspace: Path
    mode: str = "agent"
    defaults: dict[PermissionClass, PermissionDecision] = field(default_factory=dict)
    rules: list[PermissionRule] = field(default_factory=list)
    allow_sensitive_files: bool = False
    allow_global_mutation: bool = True
    mutation_targets: tuple[str, ...] = ()
    workspace_only: bool = True
    # Low-level/benchmark policies keep their explicit historical semantics.
    # User-facing runs opt into risk controls through ``for_interactive_run``.
    dangerous_action_decision: PermissionDecision = PermissionDecision.ALLOW
    critical_action_decision: PermissionDecision = PermissionDecision.ALLOW
    unknown_tool_decision: PermissionDecision = PermissionDecision.ALLOW
    require_dangerous_approval: bool = False
    sandbox: dict[str, Any] = field(default_factory=dict)
    profile: str = "balanced"
    minimums: dict[PermissionClass, PermissionDecision] = field(default_factory=dict)

    def __post_init__(self):
        self.workspace = Path(self.workspace).resolve()
        for permission_class in PermissionClass:
            self.defaults.setdefault(permission_class, PermissionDecision.ALLOW)

    @classmethod
    def for_mode(cls, workspace: Path, mode: str = "agent") -> "RuntimePolicy":
        normalized = str(mode or "agent").lower()
        defaults = {permission_class: PermissionDecision.ALLOW for permission_class in PermissionClass}
        if normalized in {"ask", "plan"}:
            defaults[PermissionClass.WRITE] = PermissionDecision.DENY
            defaults[PermissionClass.MUTATION] = PermissionDecision.DENY
        if normalized == "chat":
            defaults[PermissionClass.WRITE] = PermissionDecision.DENY
            defaults[PermissionClass.PROCESS] = PermissionDecision.DENY
            defaults[PermissionClass.MUTATION] = PermissionDecision.DENY
        if normalized in {"evaluate", "task"}:
            defaults[PermissionClass.MUTATION] = PermissionDecision.DENY
            defaults[PermissionClass.NETWORK] = PermissionDecision.DENY
        return cls(
            workspace=workspace,
            mode=normalized,
            defaults=defaults,
            allow_sensitive_files=normalized not in {"evaluate", "task"},
            allow_global_mutation=normalized not in {"evaluate", "task", "ask", "plan", "chat", "evolve"},
        )

    @classmethod
    def for_interactive_run(
        cls,
        workspace: Path,
        mode: str,
        *,
        graph_config: Optional[Mapping[str, Any]] = None,
        security_settings: Optional[Mapping[str, Any]] = None,
        allow_global_mutation: Optional[bool] = None,
        mutation_targets: Iterable[str] = (),
    ) -> "RuntimePolicy":
        """Compose Harness restrictions with the user's workspace policy.

        Harness rules may narrow the user profile but cannot silently widen it.
        This prevents a downloaded Harness from changing a user's security
        posture just by declaring permissive defaults in its JSON.
        """

        policy = cls.from_config(workspace, mode, graph_config)
        mode_minimums = cls.for_mode(workspace, mode).defaults
        settings = dict(security_settings or {})
        profile = str(settings.get("profile", "balanced")).lower()
        profile_defaults: dict[str, dict[PermissionClass, PermissionDecision]] = {
            "strict": {
                PermissionClass.READ: PermissionDecision.ALLOW,
                PermissionClass.WRITE: PermissionDecision.ASK,
                PermissionClass.PROCESS: PermissionDecision.ASK,
                PermissionClass.NETWORK: PermissionDecision.DENY,
                PermissionClass.MUTATION: PermissionDecision.ASK,
                PermissionClass.SECRET: PermissionDecision.DENY,
            },
            "balanced": {
                PermissionClass.READ: PermissionDecision.ALLOW,
                PermissionClass.WRITE: PermissionDecision.ALLOW,
                PermissionClass.PROCESS: PermissionDecision.ALLOW,
                PermissionClass.NETWORK: PermissionDecision.ASK,
                PermissionClass.MUTATION: PermissionDecision.ASK,
                PermissionClass.SECRET: PermissionDecision.DENY,
            },
            "trusted": {
                PermissionClass.READ: PermissionDecision.ALLOW,
                PermissionClass.WRITE: PermissionDecision.ALLOW,
                PermissionClass.PROCESS: PermissionDecision.ALLOW,
                PermissionClass.NETWORK: PermissionDecision.ALLOW,
                PermissionClass.MUTATION: PermissionDecision.ALLOW,
                PermissionClass.SECRET: PermissionDecision.ASK,
            },
            "unrestricted": {permission_class: PermissionDecision.ALLOW for permission_class in PermissionClass},
        }
        if profile not in profile_defaults:
            profile = "balanced"
        rank = {PermissionDecision.ALLOW: 0, PermissionDecision.ASK: 1, PermissionDecision.DENY: 2}
        for permission_class, minimum in profile_defaults[profile].items():
            current = policy.defaults.get(permission_class, PermissionDecision.ALLOW)
            policy.defaults[permission_class] = max((current, minimum), key=lambda value: rank[value])
            policy.minimums[permission_class] = max(
                (mode_minimums.get(permission_class, PermissionDecision.ALLOW), minimum),
                key=lambda value: rank[value],
            )

        explicit_network = settings.get("network_decision")
        explicit_secret = settings.get("secret_decision")
        for permission_class, raw in (
            (PermissionClass.NETWORK, explicit_network),
            (PermissionClass.SECRET, explicit_secret),
        ):
            if raw is None:
                continue
            try:
                requested = PermissionDecision(str(raw).lower())
            except ValueError:
                continue
            current = policy.defaults[permission_class]
            policy.defaults[permission_class] = max((current, requested), key=lambda value: rank[value])
            current_minimum = policy.minimums.get(permission_class, PermissionDecision.ALLOW)
            policy.minimums[permission_class] = max((current_minimum, requested), key=lambda value: rank[value])

        policy.profile = profile
        policy.allow_sensitive_files = bool(settings.get("allow_sensitive_files", False))
        policy.workspace_only = bool(settings.get("workspace_only", True)) or profile != "unrestricted"
        policy.require_dangerous_approval = bool(settings.get("require_dangerous_approval", True))
        for attribute, default in (
            ("dangerous_action_decision", "ask"),
            ("critical_action_decision", "ask"),
            ("unknown_tool_decision", "ask"),
        ):
            try:
                setattr(policy, attribute, PermissionDecision(str(settings.get(attribute, default)).lower()))
            except ValueError:
                setattr(policy, attribute, PermissionDecision.ASK)
        sandbox = settings.get("sandbox", {})
        policy.sandbox = dict(sandbox) if isinstance(sandbox, Mapping) else {}
        if allow_global_mutation is not None:
            policy.allow_global_mutation = bool(allow_global_mutation)
        targets = {str(value).lower() for value in mutation_targets if str(value).strip()}
        if targets:
            policy.mutation_targets = tuple(sorted(targets))
        return policy

    @classmethod
    def for_task(
        cls,
        workspace: Path,
        *,
        network: str = "disabled",
        evolution_allowed: bool = False,
        evolution_targets: Iterable[str] = (),
    ) -> "RuntimePolicy":
        policy = cls.for_mode(workspace, "evaluate")
        policy.defaults[PermissionClass.NETWORK] = (
            PermissionDecision.DENY if str(network).lower() == "disabled" else PermissionDecision.ALLOW
        )
        targets = {str(value).lower() for value in evolution_targets}
        policy.mutation_targets = tuple(sorted(targets))
        policy.allow_global_mutation = bool(evolution_allowed and targets)
        if policy.allow_global_mutation:
            policy.defaults[PermissionClass.MUTATION] = PermissionDecision.ALLOW
        return policy

    @classmethod
    def from_config(cls, workspace: Path, mode: str, config: Optional[Mapping[str, Any]]) -> "RuntimePolicy":
        policy = cls.for_mode(workspace, mode)
        if not isinstance(config, Mapping):
            return policy
        raw_defaults = config.get("defaults", {})
        if isinstance(raw_defaults, Mapping):
            for key, value in raw_defaults.items():
                try:
                    policy.defaults[PermissionClass(str(key).lower())] = PermissionDecision(str(value).lower())
                except ValueError:
                    continue
        if "allow_sensitive_files" in config:
            policy.allow_sensitive_files = bool(config.get("allow_sensitive_files"))
        if "allow_global_mutation" in config:
            policy.allow_global_mutation = bool(config.get("allow_global_mutation"))
        raw_targets = config.get("mutation_targets", ())
        if isinstance(raw_targets, str):
            raw_targets = [raw_targets]
        if isinstance(raw_targets, (list, tuple, set)):
            policy.mutation_targets = tuple(sorted({str(value).lower() for value in raw_targets if str(value).strip()}))
        for raw in config.get("rules", []) if isinstance(config.get("rules", []), list) else []:
            if not isinstance(raw, Mapping):
                continue
            try:
                decision = PermissionDecision(str(raw.get("decision", "deny")).lower())
                permission_class = (
                    PermissionClass(str(raw["permission_class"]).lower())
                    if raw.get("permission_class") else None
                )
            except ValueError:
                continue
            modes = raw.get("modes", [])
            if isinstance(modes, str):
                modes = [modes]
            arguments = raw.get("arguments", {})
            policy.rules.append(PermissionRule(
                decision=decision,
                permission_class=permission_class,
                tool=str(raw.get("tool", "*")),
                arguments={str(key): str(value) for key, value in arguments.items()} if isinstance(arguments, Mapping) else {},
                modes=tuple(str(value).lower() for value in modes),
                workspace=str(raw.get("workspace", "*")),
                reason=str(raw.get("reason", "")),
            ))
        return policy

    def evaluate_tool(
        self,
        tool: str,
        arguments: Optional[Mapping[str, Any]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
        *,
        schema_only: bool = False,
    ) -> PolicyDecision:
        arguments = arguments or {}
        classes = tuple(sorted(classify_tool(tool, metadata, arguments), key=lambda value: value.value))
        path_error = self._path_error(tool, arguments, classes, schema_only=schema_only)
        if path_error:
            return PolicyDecision(PermissionDecision.DENY, classes, path_error, risk=assess_tool_risk(tool, arguments, metadata))
        decisions = []
        reasons = []
        matched_index = None
        for permission_class in classes:
            decision = self.defaults[permission_class]
            reason = f"{self.mode} mode defaults {permission_class.value} to {decision.value}"
            for index, rule in enumerate(self.rules):
                if rule.matches(
                    mode=self.mode,
                    workspace=self.workspace,
                    tool=tool,
                    permission_class=permission_class,
                    arguments=arguments,
                ):
                    decision = rule.decision
                    reason = rule.reason or f"matched permission rule {index}"
                    matched_index = index
            decisions.append(decision)
            reasons.append(reason)
        final = (
            PermissionDecision.DENY if PermissionDecision.DENY in decisions
            else PermissionDecision.ASK if PermissionDecision.ASK in decisions
            else PermissionDecision.ALLOW
        )
        minimums = [self.minimums.get(permission_class, PermissionDecision.ALLOW) for permission_class in classes]
        if PermissionDecision.DENY in minimums:
            final = PermissionDecision.DENY
            reasons.append("workspace security profile enforces deny")
        elif PermissionDecision.ASK in minimums and final == PermissionDecision.ALLOW:
            final = PermissionDecision.ASK
            reasons.append("workspace security profile requires approval")
        risk = assess_tool_risk(tool, arguments, metadata)
        if short_tool_name(tool) in PROCESS_TOOLS and str(self.sandbox.get("mode", "workspace")) != "container":
            if risk.level in {RiskLevel.LOW, RiskLevel.MEDIUM}:
                risk = _risk(
                    *risk.findings,
                    RiskFinding(
                        "command.host_execution",
                        RiskLevel.HIGH,
                        "Host command is not protected by an OS/container sandbox",
                    ),
                )
        risk_decision: Optional[PermissionDecision] = None
        if risk.level == RiskLevel.CRITICAL:
            risk_decision = self.critical_action_decision
        elif risk.level == RiskLevel.HIGH and self.require_dangerous_approval:
            risk_decision = self.dangerous_action_decision
        if any(item.code == "tool.undeclared" for item in risk.findings):
            risk_decision = self.unknown_tool_decision
        if risk_decision is not None:
            rank = {PermissionDecision.ALLOW: 0, PermissionDecision.ASK: 1, PermissionDecision.DENY: 2}
            if rank[risk_decision] > rank[final]:
                final = risk_decision
                reasons.append(
                    f"{risk.level.value} risk requires {risk_decision.value}: "
                    + ", ".join(item.summary for item in risk.findings)
                )
        return PolicyDecision(final, classes, "; ".join(reasons), matched_index, risk)

    def evaluate_class(self, permission_class: PermissionClass, *, tool: str, arguments: Optional[Mapping[str, Any]] = None) -> PolicyDecision:
        metadata = {"permissions": [permission_class.value]}
        return self.evaluate_tool(tool, arguments, metadata)

    def require_class(self, permission_class: PermissionClass, *, tool: str, arguments: Optional[Mapping[str, Any]] = None) -> None:
        decision = self.evaluate_class(permission_class, tool=tool, arguments=arguments)
        if not decision.allowed:
            raise PermissionError(decision.reason)

    def _path_error(
        self,
        tool: str,
        arguments: Mapping[str, Any],
        classes: tuple[PermissionClass, ...],
        *,
        schema_only: bool = False,
    ) -> Optional[str]:
        short = short_tool_name(tool)
        if not self.workspace_only:
            path_keys: tuple[str, ...] = ()
        else:
            path_keys = PATH_ARGUMENTS.get(short, ())
        for key in path_keys:
            raw = arguments.get(key)
            if raw in (None, ""):
                continue
            try:
                candidate = Path(str(raw))
                resolved = candidate.resolve() if candidate.is_absolute() else (self.workspace / candidate).resolve()
                resolved.relative_to(self.workspace)
            except (OSError, RuntimeError, ValueError):
                return f"{short}.{key} escapes run workspace {self.workspace}"
            if PermissionClass.READ in classes and not self.allow_sensitive_files:
                if is_sensitive_path(resolved):
                    return f"reading sensitive file '{resolved.name}' is denied in {self.mode} mode"
        if PermissionClass.MUTATION in classes and not self.allow_global_mutation:
            return f"global Identity/Harness mutation is denied in {self.mode} mode"
        if PermissionClass.MUTATION in classes and self.mutation_targets:
            allowed_targets = set(self.mutation_targets)
            artifact_classes = MUTATION_ARTIFACTS.get(short, set())
            if artifact_classes & allowed_targets:
                return None
            requested = {
                str(arguments.get(key) or "").lower()
                for key in ("target", "name", "identity", "identity_name", "target_identity", "harness", "harness_name", "target_harness")
                if arguments.get(key) not in (None, "")
            }
            if schema_only and not requested:
                return None
            if not requested or not any(
                candidate == allowed or candidate.endswith(f"/{allowed}")
                for candidate in requested for allowed in allowed_targets
            ):
                return f"mutation target is outside the explicit {self.mode} scope: {', '.join(self.mutation_targets)}"
        return None

    def public(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "workspace": str(self.workspace),
            "defaults": {key.value: value.value for key, value in self.defaults.items()},
            "allow_sensitive_files": self.allow_sensitive_files,
            "allow_global_mutation": self.allow_global_mutation,
            "mutation_targets": list(self.mutation_targets),
            "workspace_only": self.workspace_only,
            "profile": self.profile,
            "require_dangerous_approval": self.require_dangerous_approval,
            "dangerous_action_decision": self.dangerous_action_decision.value,
            "critical_action_decision": self.critical_action_decision.value,
            "unknown_tool_decision": self.unknown_tool_decision.value,
            "sandbox": dict(self.sandbox),
            "minimums": {key.value: value.value for key, value in self.minimums.items()},
            "rules": [
                {
                    "decision": rule.decision.value,
                    "permission_class": rule.permission_class.value if rule.permission_class else None,
                    "tool": rule.tool,
                    "arguments": dict(rule.arguments),
                    "modes": list(rule.modes),
                    "workspace": rule.workspace,
                    "reason": rule.reason,
                }
                for rule in self.rules
            ],
        }
