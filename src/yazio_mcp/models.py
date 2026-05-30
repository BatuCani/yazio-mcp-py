"""Pydantic models that normalize Yazio's raw responses.

Two jobs:
  1. SAFETY — drop sensitive fields Yazio includes in profile/summary payloads
     (user_token, email, uuid, stripe/siwa ids). They are never needed to answer
     "how many calories did I have", and shouldn't flow into an LLM context.
  2. CLARITY — flatten Yazio's dotted keys ("energy.energy", "nutrient.protein")
     and verbose blobs into a small, readable shape an agent can summarize.

Every model uses ``extra="ignore"`` so unknown/new Yazio fields are silently
dropped (rather than crashing) — and so anything NOT explicitly modeled,
including sensitive fields, never leaks through.

Field names/types were captured from real responses on a live account.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _round(value: Any) -> float | None:
    return round(float(value), 1) if isinstance(value, (int, float)) else None


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    def trimmed(self) -> dict[str, Any]:
        """Dict with empty/None fields dropped — clean payload for an LLM."""
        return self.model_dump(exclude_none=True)


class Macros(_Base):
    """Energy + macronutrients, from Yazio's dotted keys."""

    energy_kcal: float | None = Field(default=None, alias="energy.energy")
    protein_g: float | None = Field(default=None, alias="nutrient.protein")
    fat_g: float | None = Field(default=None, alias="nutrient.fat")
    carb_g: float | None = Field(default=None, alias="nutrient.carb")


class Goals(_Base):
    """Daily targets. Sensitive: none."""

    energy_kcal: float | None = Field(default=None, alias="energy.energy")
    protein_g: float | None = Field(default=None, alias="nutrient.protein")
    fat_g: float | None = Field(default=None, alias="nutrient.fat")
    carb_g: float | None = Field(default=None, alias="nutrient.carb")
    water_ml: float | None = Field(default=None, alias="water")
    steps: float | None = Field(default=None, alias="activity.step")
    weight_goal_kg: float | None = Field(default=None, alias="bodyvalue.weight")


class UserProfile(_Base):
    """Profile WITHOUT user_token / email / uuid / stripe & siwa ids.

    Those fields exist in the raw response but are intentionally not declared,
    so ``extra="ignore"`` strips them.
    """

    first_name: str | None = None
    sex: str | None = None
    country: str | None = None
    goal: str | None = None
    weight_change_per_week: float | None = None
    body_height_cm: float | None = Field(default=None, alias="body_height")
    date_of_birth: str | None = None
    start_weight_kg: float | None = Field(default=None, alias="start_weight")
    is_premium: bool | None = None
    registration_date: str | None = None


class Meal(_Base):
    name: str
    energy_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carb_g: float | None = None


class DailySummary(_Base):
    """Flattened day overview: totals, goals, and per-meal breakdown."""

    date: str
    total_kcal: float
    water_ml: float | None = None
    steps: float | None = None
    activity_kcal: float | None = None
    fasting_template: str | None = None
    goals: Goals | None = None
    meals: list[Meal] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, date: str, raw: dict[str, Any]) -> DailySummary:
        raw_meals = raw.get("meals", {}) or {}
        meals: list[Meal] = []
        total = 0.0
        for name, m in raw_meals.items():
            n = (m or {}).get("nutrients", {}) or {}
            macros = Macros.model_validate(n)
            total += macros.energy_kcal or 0.0
            meals.append(
                Meal(
                    name=name,
                    energy_kcal=_round(macros.energy_kcal),
                    protein_g=_round(macros.protein_g),
                    fat_g=_round(macros.fat_g),
                    carb_g=_round(macros.carb_g),
                )
            )
        goals = Goals.model_validate(raw["goals"]) if raw.get("goals") else None
        return cls(
            date=date,
            total_kcal=round(total, 1),
            water_ml=_round(raw.get("water_intake")),
            steps=_round(raw.get("steps")),
            activity_kcal=_round(raw.get("activity_energy")),
            fasting_template=raw.get("active_fasting_countdown_template_key"),
            goals=goals,
            meals=meals,
        )


class ConsumedItem(_Base):
    """A diary entry that references a catalog product (by ``product_id``).

    Keeps ``id`` (needed to delete the entry). ``name`` is filled in after the
    fact by resolving ``product_id`` against the product catalog, so the agent
    sees WHAT was eaten, not just an opaque id.
    """

    id: str
    date: str | None = None
    daytime: str | None = None
    product_id: str | None = None
    name: str | None = None
    amount: float | None = None
    serving: str | None = None
    serving_quantity: float | None = None


class SimpleProduct(_Base):
    """A free-text / AI-generated diary entry that carries its own name and
    nutrients inline (no product_id to resolve). E.g. a photo-logged meal."""

    id: str
    date: str | None = None
    daytime: str | None = None
    name: str | None = None
    is_ai_generated: bool | None = None
    energy_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    carb_g: float | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> SimpleProduct:
        macros = Macros.model_validate(raw.get("nutrients", {}) or {})
        return cls(
            id=raw["id"],
            date=raw.get("date"),
            daytime=raw.get("daytime"),
            name=raw.get("name"),
            is_ai_generated=raw.get("is_ai_generated"),
            energy_kcal=_round(macros.energy_kcal),
            protein_g=_round(macros.protein_g),
            fat_g=_round(macros.fat_g),
            carb_g=_round(macros.carb_g),
        )


class WeightEntry(_Base):
    date: str | None = None
    weight_kg: float | None = Field(default=None, alias="value")


class ProductDetail(_Base):
    """Product info trimmed to what matters for nutrition."""

    name: str | None = None
    category: str | None = None
    producer: str | None = None
    base_unit: str | None = None
    nutrients: dict[str, Any] | None = None
