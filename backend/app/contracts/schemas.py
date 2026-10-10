"""Data-only development task contracts; no executable evaluators or protected labels."""
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

MAX_BODY_BYTES = 131072
SENSITIVE_KEY = re.compile(r"(?:password|passwd|secret|credential|private.?key|api.?key|authorization|(?:^|_)(?:token|access_token|refresh_token|session_cookie)$)", re.I)
SECRET_VALUE = re.compile(r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|-----BEGIN .*PRIVATE KEY-----|Bearer\s+\S+|https?://[^/\s:@]+:[^/\s@]+@|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)", re.I)
CODE = re.compile(r"(?:\$\(|```(?:python|sh|bash)|^\s*#!|^\s*(?:import\s+\w|from\s+\w+\s+import|def\s+\w+\(|(?:bash|sh|python\d*|curl|wget|rm|sudo|npm|pip|uv|docker)\s+[^\n]+))", re.M)
FORBIDDEN_KEYS = {"evaluator", "evaluator_code", "script", "command", "shell_command", "protected_labels", "final_evaluation", "protected_final"}


def bounded_data(value, max_bytes=MAX_BODY_BYTES):
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > 6000 or depth > 12:
            raise ValueError("Contract JSON exceeds its node or depth limit.")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 120 or SENSITIVE_KEY.search(key) or key.lower() in FORBIDDEN_KEYS:
                    raise ValueError("Credentials, executable fields, and protected labels are not accepted.")
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            if len(item) > 4000 or SECRET_VALUE.search(item) or CODE.search(item):
                raise ValueError("Text is too long or contains credentials or executable commands.")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON numbers must be finite.")
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > max_bytes:
        raise ValueError("Contract JSON exceeds its byte limit.")
    return value


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def text_fields(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            for key in ("name", "description", "review_guidance", "injection_description"):
                if isinstance(value.get(key), str):
                    value[key] = value[key].strip()
        return value


class FieldRule(DataModel):
    pointer: str = Field(min_length=1, max_length=120, pattern=r"^/(?:[^~/]|~[01])*(?:/(?:[^~/]|~[01])*)*$")
    field_type: Literal["string", "integer", "number", "boolean", "object", "array", "null"]
    check_exact: bool = Field(default=False, strict=True)
    exact_value: JsonValue = None

    @model_validator(mode="after")
    def exact_type(self):
        if not self.check_exact:
            if self.exact_value is not None:
                raise ValueError("Enable check_exact to declare an exact value.")
            return self
        if "exact_value" not in self.model_fields_set:
            raise ValueError("Declare exact_value explicitly when check_exact is enabled.")
        value = self.exact_value
        correct = {"string": isinstance(value, str), "integer": type(value) is int,
                   "number": type(value) in {int, float}, "boolean": type(value) is bool,
                   "object": isinstance(value, dict), "array": isinstance(value, list), "null": value is None}
        if not correct[self.field_type]:
            raise ValueError("Exact value must match the declared field type.")
        return self


class Requirement(DataModel):
    description: str = Field(min_length=1, max_length=2000)
    verification: Literal["automatic", "human_review"]
    rule: FieldRule | None = None
    review_guidance: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def method(self):
        if self.verification == "automatic" and (not self.rule or self.review_guidance):
            raise ValueError("Automatic requirements need a field rule, without a human-review rubric.")
        if self.verification == "human_review" and (not self.review_guidance or self.rule):
            raise ValueError("Human-review requirements need review guidance, without an automatic rule.")
        return self


class Task(DataModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    input: JsonValue
    expected_output: dict[str, JsonValue] | list[JsonValue] | None = None
    required_fields: list[FieldRule] = Field(default_factory=list, max_length=50)
    required_facts: list[Requirement] = Field(default_factory=list, max_length=20)
    required_evidence: list[Requirement] = Field(default_factory=list, max_length=20)
    case_kind: Literal["ordinary", "injected_failure"]
    injection_description: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def case(self):
        bounded_data(self.input, 16384)
        if self.expected_output is not None:
            bounded_data(self.expected_output, 16384)
        if (self.case_kind == "injected_failure") != bool(self.injection_description):
            raise ValueError("Only injected-failure cases must describe the deliberately injected failure.")
        pointers = [r.pointer for r in self.required_fields]
        if len(pointers) != len(set(pointers)):
            raise ValueError("Required output field pointers must be unique within a task.")
        return self


class FailureOutcomes(DataModel):
    missing_information: Requirement | None = None
    denied_access: Requirement | None = None
    tool_failure: Requirement | None = None


class ProtectedBehavior(DataModel):
    instructions: Requirement | None = None
    permissions: Requirement | None = None
    freshness: Requirement | None = None
    essential_information: Requirement | None = None


class Limits(DataModel):
    # Saved bounds for one complete contract run across all tasks; enforcement is a later stage.
    max_runtime_seconds: int = Field(strict=True, ge=1, le=3600)
    max_model_calls: int = Field(strict=True, ge=0, le=1000)
    max_tool_calls: int = Field(strict=True, ge=0, le=10000)
    max_tokens: int = Field(strict=True, ge=0, le=1000000)
    max_spend_usd: float = Field(strict=True, ge=0, le=100, allow_inf_nan=False)


class ContractInput(DataModel):
    base_version: int | None = Field(default=None, strict=True, ge=1, le=200)
    configuration_revision: str = Field(pattern=r"^[a-f0-9]{32}$")
    tasks: list[Task] = Field(default_factory=list, max_length=20)
    acceptable_failures: FailureOutcomes = Field(default_factory=FailureOutcomes)
    protected_behavior: ProtectedBehavior = Field(default_factory=ProtectedBehavior)
    limits: Limits | None = None

    @model_validator(mode="before")
    @classmethod
    def bounded(cls, value):
        return bounded_data(value)

    @model_validator(mode="after")
    def unique_names(self):
        names = [t.name.casefold() for t in self.tasks]
        if len(names) != len(set(names)):
            raise ValueError("Task names must be unique.")
        bounded_data(self.model_dump(mode="json"))
        return self


class ConfirmInput(DataModel):
    version: int = Field(strict=True, ge=1, le=200)
    configuration_revision: str = Field(pattern=r"^[a-f0-9]{32}$")


def missing_requirements(contract):
    missing = []
    if not contract["tasks"]:
        missing.append("At least one representative task is required.")
    for index, task in enumerate(contract["tasks"], 1):
        if task["expected_output"] is None and not task["required_fields"]:
            missing.append(f"Task {index}: define expected structured output or required output fields.")
    for category in ("acceptable_failures", "protected_behavior"):
        for key, value in contract[category].items():
            if value is None:
                missing.append(f"Define {category}.{key}.")
    if contract["limits"] is None:
        missing.append("Set all five execution limits explicitly.")
    return missing
