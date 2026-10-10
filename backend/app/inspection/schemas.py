from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .scanner import MODEL, VERSION, entrypoint, safe_path, SECRET
from ..gateway.models import LiteLLMModel


class ConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=32, max_length=32, pattern=r"^[a-f0-9]{32}$")
    commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    python_version: str = Field(min_length=1, max_length=80)
    dependency_manifests: list[str] = Field(max_length=30)
    entrypoint: str = Field(min_length=1, max_length=180)
    model_provider: Literal["openai", "anthropic", "google", "aws_bedrock", "litellm"]
    model_id: str = Field(min_length=1, max_length=120)
    litellm_model: LiteLLMModel | None = None
    approved_tools: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("python_version")
    @classmethod
    def version(cls, value):
        if not VERSION.fullmatch(value):
            raise ValueError("Enter a Python version or version constraint, without credentials.")
        return value

    @field_validator("entrypoint")
    @classmethod
    def command(cls, value):
        if not entrypoint(value):
            raise ValueError("Use a module:function, python relative_file.py, or python -m module entrypoint.")
        return value

    @field_validator("model_id")
    @classmethod
    def model(cls, value):
        if SECRET.search(value) or not MODEL.fullmatch(value):
            raise ValueError("Use a supported model identifier, never an API key.")
        return value

    @field_validator("dependency_manifests", "approved_tools")
    @classmethod
    def identifiers(cls, values):
        if len(values) != len(set(values)) or any(not safe_path(v) for v in values):
            raise ValueError("Use unique safe identifiers, without credentials.")
        return values
