from pathlib import Path
from shutil import copyfileobj
from uuid import uuid4
import base64
import hashlib
import hmac
import os
import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from backend.routes.utils import dataframe_records
from src.analytics.food_history import (
    build_daily_nutrition_summary,
    calculate_calorie_adherence,
    get_nutrition_history,
    save_daily_nutrition_summary,
)
from src.ai.food_parser import analyze_food_text, parse_food_text
from src.nutrition import (
    add_food_shortcut,
    add_meal_template_items,
    create_food_entry,
    delete_food_log_entry,
    delete_food_shortcut,
    load_food_shortcuts,
    load_frequent_foods,
    load_meal_templates,
    load_nutrition_log,
    log_frequent_food,
    log_meal_template,
    log_food_shortcut,
    save_nutrition_log,
    update_food_shortcut,
    update_meal_template_name,
)
from src.nutrition_targets import load_nutrition_targets
from src.paths import PROJECT_ROOT, raw_data_path
import pandas as pd


router = APIRouter(tags=["nutrition"])
LABEL_UPLOAD_DIR = raw_data_path("nutrition_labels")
ACCESS_COOKIE = "performance_os_access"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def _sign_session(timestamp: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8").replace("+", "-").replace("/", "_").replace("=", "")


def _require_authenticated_request(request: Request) -> None:
    """Require the same access cookie used by the frontend gate."""
    if not os.getenv("APP_PASSWORD"):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="APP_PASSWORD is not configured")
    session_secret = os.getenv("SESSION_SECRET")
    if not session_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="SESSION_SECRET is not configured")

    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    timestamp, separator, signature = token.partition(".")
    if not separator:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    try:
        timestamp_ms = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from exc
    if int(time.time() * 1000) - timestamp_ms > SESSION_MAX_AGE_SECONDS * 1000:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    if not hmac.compare_digest(signature, _sign_session(timestamp, session_secret)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


@router.get("/status")
def status() -> dict:
    """Return placeholder route status."""
    return {"status": "placeholder", "module": "nutrition"}


class NutritionEntry(BaseModel):
    date: str
    meal_type: str
    food_name: str = Field(min_length=1)
    calories: float = Field(ge=0)
    protein: float = Field(ge=0)
    carbs: float = Field(ge=0)
    fat: float = Field(ge=0)
    serving_size_grams: float | None = Field(default=None, gt=0)
    grams_consumed: float | None = Field(default=None, gt=0)
    serving_multiplier: float | None = Field(default=None, ge=0)
    calories_per_serving: float | None = Field(default=None, ge=0)
    protein_per_serving: float | None = Field(default=None, ge=0)
    carbs_per_serving: float | None = Field(default=None, ge=0)
    fat_per_serving: float | None = Field(default=None, ge=0)
    fiber: float | None = Field(default=None, ge=0)
    sodium: float | None = Field(default=None, ge=0)
    potassium: float | None = Field(default=None, ge=0)
    source_label_file: str = ""


class FoodParseRequest(BaseModel):
    text: str = Field(min_length=1)


class FoodAnalyzeTextRequest(BaseModel):
    date: str
    text: str = Field(max_length=4000)


class FoodAnalyzeItem(BaseModel):
    name: str = Field(min_length=1)
    original_text: str = ""
    quantity: float | None = Field(default=None, ge=0)
    unit: str = ""
    serving_description: str = ""
    calories: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    fiber_g: float | None = Field(default=None, ge=0)
    sugar_g: float | None = Field(default=None, ge=0)
    sodium_mg: float | None = Field(default=None, ge=0)
    confidence: str = "medium"
    source: str = "openai_estimate"
    source_id: str | None = None
    source_url: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    needs_review: bool = True


class FoodLogBulkRequest(BaseModel):
    date: str
    meal_type: str = "Snack"
    items: list[FoodAnalyzeItem] = Field(min_length=1)


class FoodShortcutPayload(BaseModel):
    shortcut_name: str = Field(min_length=1)
    calories: float = Field(ge=0)
    protein: float = Field(ge=0)
    carbs: float = Field(ge=0)
    fat: float = Field(ge=0)
    fiber: float | None = None
    sodium: float | None = None
    potassium: float | None = None
    serving_size_grams: float | None = Field(default=None, gt=0)
    default_grams_consumed: float | None = Field(default=None, gt=0)
    calories_per_serving: float | None = Field(default=None, ge=0)
    protein_per_serving: float | None = Field(default=None, ge=0)
    carbs_per_serving: float | None = Field(default=None, ge=0)
    fat_per_serving: float | None = Field(default=None, ge=0)
    notes: str = ""
    source: str = "ai_parse"


class ShortcutLogPayload(BaseModel):
    date: str
    meal_type: str = "Snack"


class MealTemplateFoodPayload(BaseModel):
    food_name: str = Field(min_length=1)
    calories: float = Field(ge=0)
    protein: float = Field(ge=0)
    carbs: float = Field(ge=0)
    fat: float = Field(ge=0)
    notes: str = ""
    source: str = "ai_parse"


class MealTemplatePayload(BaseModel):
    template_name: str = Field(min_length=1)
    default_meal_type: str = "Breakfast"
    foods: list[MealTemplateFoodPayload]


class MealTemplateRenamePayload(BaseModel):
    template_name: str = Field(min_length=1)


def rebuild_daily_summary() -> pd.DataFrame:
    """Rebuild persisted daily summary from detailed food logs."""
    summary_df = build_daily_nutrition_summary(load_nutrition_log(), load_nutrition_targets())
    save_daily_nutrition_summary(summary_df)
    return summary_df


def _looks_non_food(text: str) -> bool:
    cleaned = str(text or "").strip().lower()
    if not cleaned:
        return True
    malicious_markers = ["<script", "drop table", "ignore previous instructions", "system prompt", "api key"]
    if any(marker in cleaned for marker in malicious_markers):
        return True
    return len([char for char in cleaned if char.isalpha()]) < 2


@router.get("/api/nutrition/logs")
def get_nutrition_logs() -> dict:
    """Return saved local nutrition logs."""
    return {"items": dataframe_records(load_nutrition_log())}


@router.post("/api/nutrition/logs")
def add_nutrition_log(entry: NutritionEntry) -> dict:
    """Add a manual food entry to local CSV storage."""
    entries_df = load_nutrition_log()
    food_entry = create_food_entry(**entry.model_dump())
    entries_df = pd.concat([entries_df, pd.DataFrame([food_entry])], ignore_index=True)
    save_nutrition_log(entries_df)
    rebuild_daily_summary()
    return {"item": food_entry, "items": dataframe_records(load_nutrition_log())}


@router.delete("/api/nutrition/logs/{food_log_id}")
def remove_nutrition_log(food_log_id: str, _: None = Depends(_require_authenticated_request)) -> dict:
    """Delete one detailed food log entry by ID without touching templates or targets."""
    try:
        deleted_entry = delete_food_log_entry(food_log_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rebuild_daily_summary()
    return {
        "deleted": deleted_entry,
        "items": dataframe_records(load_nutrition_log()),
    }


@router.post("/api/nutrition/label-upload")
def upload_nutrition_label(file: UploadFile = File(...)) -> dict:
    """Store a nutrition label PDF/image locally for later OCR extraction."""
    allowed_suffixes = {".pdf", ".png", ".jpg", ".jpeg"}
    original_name = Path(file.filename or "nutrition-label").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="Upload must be a PDF, PNG, JPG, or JPEG file.")

    LABEL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_stem = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in Path(original_name).stem).strip("-") or "nutrition-label"
    stored_name = f"{safe_stem}-{uuid4().hex[:10]}{suffix}"
    destination = LABEL_UPLOAD_DIR / stored_name
    with destination.open("wb") as output_file:
        copyfileobj(file.file, output_file)

    return {
        "uploaded_filename": stored_name,
        "path": _display_path(destination),
        "extraction_status": "not_implemented",
        "message": "Nutrition label uploaded. OCR/AI extraction is a future step; manual fields remain editable.",
    }


@router.get("/api/nutrition/history")
def get_daily_nutrition_history(days: int = 30) -> dict:
    """Return day-level nutrition summaries and adherence analytics."""
    rebuild_daily_summary()
    history_df = get_nutrition_history(days)
    return {
        "items": dataframe_records(history_df),
        "adherence": calculate_calorie_adherence(history_df, days=7),
    }


@router.post("/api/nutrition/ai/parse")
def parse_food(payload: FoodParseRequest) -> dict:
    """Parse natural-language food text into editable food entries."""
    parsed = parse_food_text(payload.text)
    return {
        "foods": parsed.get("foods", []),
        "total": parsed.get("total", {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}),
        "source": parsed.get("source", "unknown"),
        "cached": bool(parsed.get("cached", False)),
        "success": bool(parsed.get("success", False)),
        "error_code": parsed.get("error_code"),
        "message": parsed.get("message", ""),
        "debug": parsed.get("debug", {}),
    }


@router.post("/api/food/analyze-text")
def analyze_food_from_text(payload: FoodAnalyzeTextRequest) -> dict:
    """Analyze free-form food text into editable draft rows without saving."""
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Food text is required.")
    if _looks_non_food(text):
        raise HTTPException(status_code=400, detail="Enter a food list to analyze.")
    result = analyze_food_text(text)
    if not result.get("items") and not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message") or "Food parsing failed.")
    return {
        "items": result.get("items", []),
        "totals": result.get("totals", {}),
        "warnings": result.get("warnings", []),
        "message": result.get("message", ""),
        "success": bool(result.get("success")),
        "error_code": result.get("error_code"),
        "debug": result.get("debug", {}),
    }


@router.post("/api/food/log-bulk")
def log_food_bulk(payload: FoodLogBulkRequest) -> dict:
    """Persist user-reviewed analyzed food rows into the regular nutrition log."""
    entries_df = load_nutrition_log()
    entries = []
    for item in payload.items:
        entry = create_food_entry(
            date=payload.date,
            meal_type=payload.meal_type,
            food_name=item.name,
            calories=item.calories,
            protein=item.protein_g,
            carbs=item.carbs_g,
            fat=item.fat_g,
            fiber=item.fiber_g,
            sodium=item.sodium_mg,
            quantity=item.quantity,
            unit=item.unit,
            serving_description=item.serving_description,
            sugar=item.sugar_g,
            source=item.source,
            source_id=item.source_id,
            source_url=item.source_url,
            confidence=item.confidence,
            assumptions=item.assumptions,
            original_text=item.original_text,
            needs_review=False,
            created_via="text_ai",
        )
        entries.append(entry)
    entries_df = pd.concat([entries_df, pd.DataFrame(entries)], ignore_index=True)
    save_nutrition_log(entries_df)
    rebuild_daily_summary()
    return {"items": dataframe_records(load_nutrition_log()), "saved": len(entries)}


@router.get("/api/nutrition/shortcuts")
def get_food_shortcuts() -> dict:
    """Return reusable food shortcuts plus existing frequent foods/templates."""
    return {
        "items": dataframe_records(load_food_shortcuts()),
        "frequent_foods": dataframe_records(load_frequent_foods()),
        "meal_templates": dataframe_records(load_meal_templates()),
    }


@router.post("/api/nutrition/shortcuts")
def create_food_shortcut(payload: FoodShortcutPayload) -> dict:
    """Create a reusable shortcut from AI parsed or manually entered macros."""
    shortcut = add_food_shortcut(**payload.model_dump())
    return {"item": shortcut, "items": dataframe_records(load_food_shortcuts())}


@router.put("/api/nutrition/shortcuts/{shortcut_id}")
def update_shortcut(shortcut_id: str, payload: FoodShortcutPayload) -> dict:
    """Update a reusable shortcut."""
    try:
        shortcut = update_food_shortcut(shortcut_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"item": shortcut, "items": dataframe_records(load_food_shortcuts())}


@router.delete("/api/nutrition/shortcuts/{shortcut_id}")
def remove_shortcut(shortcut_id: str) -> dict:
    """Delete a reusable shortcut."""
    delete_food_shortcut(shortcut_id)
    return {"items": dataframe_records(load_food_shortcuts())}


@router.post("/api/nutrition/shortcuts/{shortcut_id}/log")
def log_shortcut(shortcut_id: str, payload: ShortcutLogPayload) -> dict:
    """Log a saved shortcut to the detailed nutrition log."""
    try:
        entry = log_food_shortcut(shortcut_id, date=payload.date, meal_type=payload.meal_type)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rebuild_daily_summary()
    return {"item": entry, "items": dataframe_records(load_nutrition_log())}


@router.post("/api/nutrition/meal-templates")
def create_meal_template(payload: MealTemplatePayload) -> dict:
    """Create a meal template from one or more parsed foods."""
    add_meal_template_items(
        template_name=payload.template_name,
        default_meal_type=payload.default_meal_type,
        foods=[food.model_dump() for food in payload.foods],
    )
    return {"items": dataframe_records(load_meal_templates())}


@router.put("/api/nutrition/meal-templates/{template_name}")
def rename_meal_template(template_name: str, payload: MealTemplateRenamePayload) -> dict:
    """Rename a saved meal template without changing its foods/macros."""
    try:
        items = update_meal_template_name(template_name, payload.template_name)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return {"items": dataframe_records(items)}


@router.post("/api/nutrition/meal-templates/{template_name}/log")
def log_template(template_name: str, payload: ShortcutLogPayload) -> dict:
    """Log all rows from a saved meal template."""
    try:
        result = log_meal_template(template_name, date=payload.date, meal_type=payload.meal_type)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rebuild_daily_summary()
    return {"item": result, "items": dataframe_records(load_nutrition_log())}


@router.post("/api/nutrition/frequent-foods/{food_name}/log")
def log_frequent(food_name: str, payload: ShortcutLogPayload) -> dict:
    """Log an existing frequent food without calling AI."""
    try:
        entry = log_frequent_food(food_name, date=payload.date, meal_type=payload.meal_type)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    rebuild_daily_summary()
    return {"item": entry, "items": dataframe_records(load_nutrition_log())}
