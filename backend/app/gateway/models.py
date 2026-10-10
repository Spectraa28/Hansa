from typing import Literal, get_args


LiteLLMModel = Literal[
    "nova-micro", "nova-lite", "nova-pro", "nova-2-lite",
    "claude-haiku", "claude-sonnet-4.6", "claude-opus-4.6",
]
LITELLM_MODELS = get_args(LiteLLMModel)
