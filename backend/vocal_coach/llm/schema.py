"""CoachingOutput: the validated shape of a coaching response, and its wire schema."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CoachingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    what_improved: list[str]
    what_is_lacking: list[str]
    next_steps: list[str]
    marked_up_example: str


# Sent verbatim to providers as the structured-output / response-format schema.
# Kept as a plain dict literal (not generated from CoachingOutput) so the wire
# format is explicit; test_schema_matches_model asserts the two cannot drift.
COACHING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "what_improved": {"type": "array", "items": {"type": "string"}},
        "what_is_lacking": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "marked_up_example": {"type": "string"},
    },
    "required": ["what_improved", "what_is_lacking", "next_steps", "marked_up_example"],
    "additionalProperties": False,
}
