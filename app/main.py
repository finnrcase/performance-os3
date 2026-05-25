from datetime import date, datetime
from pathlib import Path
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analytics.recovery_engine import calculate_recovery_score as calculate_advanced_recovery_score
from src.ai.food_parser import parse_food_text
from src.body_metrics import add_body_metric_entry, load_body_metrics
from src.config import integration_status, load_settings, mask_secret, save_settings
from src.goals import (
    ACTIVITY_LEVELS,
    AGGRESSIVENESS_LEVELS,
    GOAL_TYPES,
    calculate_goal_feasibility,
    load_user_goals,
    save_user_goals,
)
from src.micronutrients import generate_micronutrient_suggestions
from src.nutrition import (
    add_frequent_food,
    add_meal_template,
    calculate_nutrition_analytics,
    calculate_daily_totals,
    create_food_entry,
    get_most_common_foods,
    get_recent_foods,
    load_frequent_foods,
    load_meal_templates,
    load_nutrition_log,
    log_meal_template,
    log_frequent_food,
    save_nutrition_log,
)
from src.nutrition_targets import (
    analyze_weight_trend,
    calculate_macro_targets,
    load_nutrition_targets,
    save_nutrition_targets,
)
from src.optimization.performance_engine import generate_performance_recommendations
from src.recommendations import generate_daily_recommendation
from src.recovery import (
    add_recovery_entry,
    load_recovery_log,
)
from src.integrations.hevy_client import HevyIntegrationError, import_hevy_workouts
from src.integrations.strava_client import (
    StravaIntegrationError,
    calculate_running_analytics,
    import_recent_runs,
)
from src.training import (
    add_training_entry,
    calculate_training_volume,
    load_training_log,
)
from src.workout_nutrition import (
    calculate_workout_nutrition_windows,
    create_workout_marker,
    generate_workout_fueling_recommendations,
    load_workout_markers,
)


PAGES = [
    "Dashboard",
    "Goals & Targets",
    "Food",
    "Data & History",
    "Weight & Recovery",
    "Training",
    "Integrations / Settings",
]

MEAL_TYPES = ["Breakfast", "Lunch", "Dinner", "Snack"]
WORKOUT_TYPES = ["Strength", "Run", "Cardio", "Rest"]


st.set_page_config(
    page_title="Performance OS",
    layout="wide",
)


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #080c10;
            --panel: #10161d;
            --panel-soft: #151d26;
            --line: #253241;
            --text: #e8eef5;
            --muted: #8fa0b3;
            --accent: #33d6a6;
            --accent-blue: #6ea8ff;
            --warning: #f4b860;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, rgba(51, 214, 166, 0.10), transparent 34rem),
                radial-gradient(circle at top right, rgba(110, 168, 255, 0.10), transparent 30rem),
                var(--bg);
            color: var(--text);
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0b1016 0%, #0d131a 100%);
            border-right: 1px solid var(--line);
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label {
            color: var(--text);
        }

        [data-testid="stSidebar"] [role="radiogroup"] label {
            border-radius: 8px;
            padding: 0.35rem 0.25rem;
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1320px;
        }

        h1, h2, h3 {
            letter-spacing: 0;
        }

        div[data-testid="stMetric"] {
            background: rgba(16, 22, 29, 0.82);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1rem;
        }

        div[data-testid="stMetricLabel"] {
            color: var(--muted);
        }

        div[data-testid="stForm"] {
            background: rgba(16, 22, 29, 0.72);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1rem;
        }

        .section-kicker {
            color: var(--accent);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.15rem;
        }

        .metric-card {
            background: linear-gradient(180deg, rgba(21, 29, 38, 0.96), rgba(13, 18, 25, 0.96));
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1rem;
            min-height: 132px;
            box-shadow: 0 18px 40px rgba(0, 0, 0, 0.24);
        }

        .metric-label {
            color: var(--muted);
            font-size: 0.82rem;
            margin-bottom: 0.5rem;
        }

        .metric-value {
            color: var(--text);
            font-size: 1.85rem;
            font-weight: 750;
            line-height: 1.05;
        }

        .metric-note {
            color: var(--muted);
            font-size: 0.82rem;
            margin-top: 0.65rem;
        }

        .soft-panel {
            background: rgba(16, 22, 29, 0.72);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1rem;
        }

        .hero-panel {
            background: linear-gradient(135deg, rgba(21, 29, 38, 0.94), rgba(9, 14, 20, 0.94));
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1.25rem;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 0.35rem;
        }

        .stTabs [data-baseweb="tab"] {
            background: rgba(16, 22, 29, 0.72);
            border-radius: 8px;
            border: 1px solid var(--line);
            padding: 0.5rem 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, caption: str | None = None, kicker: str | None = None) -> None:
    if kicker:
        st.markdown(f"<div class='section-kicker'>{kicker}</div>", unsafe_allow_html=True)
    st.subheader(title)
    if caption:
        st.caption(caption)


def metric_card(label: str, value: str, note: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def styled_container():
    return st.container(border=True)


def blank_figure(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=title,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=280,
        margin=dict(l=20, r=20, t=52, b=30),
        annotations=[
            dict(
                text="Log data to populate this chart",
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(color="#8fa0b3"),
            )
        ],
    )
    return fig


def style_plotly(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e8eef5"),
        height=height,
        margin=dict(l=20, r=20, t=48, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(gridcolor="rgba(143, 160, 179, 0.12)")
    fig.update_yaxes(gridcolor="rgba(143, 160, 179, 0.12)")
    return fig


def render_app_header() -> None:
    st.markdown(
        """
        <div class="hero-panel">
            <div class="section-kicker">Performance Analytics</div>
            <h1 style="margin:0;">Performance OS</h1>
            <p style="color:#8fa0b3; margin:0.45rem 0 0;">
                Recovery, nutrition, and training optimization dashboard
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def get_latest_recovery_score(recovery_df: pd.DataFrame) -> float | None:
    if recovery_df.empty:
        return None
    analytics_df = calculate_advanced_recovery_score(
        recovery_df=recovery_df,
        training_df=load_training_log(),
        nutrition_df=load_nutrition_log(),
    )
    if analytics_df.empty:
        return None
    return float(analytics_df.sort_values("date").iloc[-1]["recovery_score"])


def get_bodyweight_trend(metrics_df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    if metrics_df.empty:
        return "No data", pd.DataFrame()

    chart_df = metrics_df.copy()
    chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
    chart_df["bodyweight"] = pd.to_numeric(chart_df["bodyweight"], errors="coerce")
    chart_df = chart_df.dropna(subset=["date", "bodyweight"]).sort_values("date")

    if chart_df.empty:
        return "No data", chart_df

    if len(chart_df) == 1:
        return f"{chart_df.iloc[-1]['bodyweight']:.1f}", chart_df

    delta = chart_df.iloc[-1]["bodyweight"] - chart_df.iloc[0]["bodyweight"]
    sign = "+" if delta >= 0 else ""
    return f"{chart_df.iloc[-1]['bodyweight']:.1f} ({sign}{delta:.1f})", chart_df


def get_active_goals_and_targets() -> tuple[dict, dict]:
    """Load goals and calculate targets, falling back to saved targets if needed."""
    goals = load_user_goals()
    calculated_targets = calculate_macro_targets(goals)
    saved_targets = load_nutrition_targets()
    targets = {**calculated_targets, **saved_targets} if saved_targets else calculated_targets
    return goals, targets


def render_dashboard() -> None:
    nutrition_df = load_nutrition_log()
    body_metrics_df = load_body_metrics()
    recovery_df = load_recovery_log()
    training_df = load_training_log()

    today = date.today().isoformat()
    totals = calculate_daily_totals(nutrition_df, today)
    recovery_score = get_latest_recovery_score(recovery_df)
    bodyweight_label, bodyweight_df = get_bodyweight_trend(body_metrics_df)
    volume_df = calculate_training_volume(training_df)
    user_goals, nutrition_targets = get_active_goals_and_targets()
    weight_feedback = analyze_weight_trend(body_metrics_df, user_goals)
    latest_workout = (
        training_df.sort_values("date").iloc[-1].to_dict()
        if not training_df.empty
        else None
    )
    performance_plan = generate_performance_recommendations(
        recovery_df=recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
        body_metrics_df=body_metrics_df,
    )

    section_header(
        "Command Center",
        "A quick read on today's intake, current recovery, and longer-term bodyweight trend.",
        "Dashboard",
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        metric_card(
            "Recovery Score",
            "No data" if recovery_score is None else f"{recovery_score:.1f}",
            "Latest check-in readiness",
        )
    with col2:
        metric_card("Calories", f"{totals['calories']:.0f}", "Logged today")
    with col3:
        metric_card("Protein", f"{totals['protein']:.1f}g", "Logged today")
    with col4:
        metric_card("Bodyweight", bodyweight_label, "Latest and total logged change")

    goal_col1, goal_col2, goal_col3, goal_col4, goal_col5 = st.columns(5)
    with goal_col1:
        metric_card("Goal Type", user_goals["goal_type"], user_goals["aggressiveness"])
    with goal_col2:
        metric_card("Target Calories", f"{nutrition_targets['target_calories']:.0f}", "Daily target")
    with goal_col3:
        metric_card("Target Protein", f"{nutrition_targets['protein_grams']:.0f}g", "Daily target")
    with goal_col4:
        trend_value = (
            "No trend"
            if weight_feedback["weekly_change_pct"] is None
            else f"{weight_feedback['weekly_change_pct']:+.2f}%/wk"
        )
        metric_card("Weight Trend", trend_value, weight_feedback["status"])
    with goal_col5:
        metric_card("Adjustment", weight_feedback["suggested_adjustment"], "Goal feedback")

    st.write("")
    workout_col, rec_col = st.columns(2)
    with workout_col:
        with styled_container():
            section_header("Latest Workout Summary", kicker="Training")
            if latest_workout:
                st.write(
                    f"{latest_workout['date']} | {latest_workout['workout_type']} | "
                    f"{latest_workout['exercise'] or 'No exercise name'}"
                )
                st.caption(
                    f"Duration: {latest_workout['duration_minutes']:.0f} min | "
                    f"Sets: {latest_workout['sets']} | Reps: {latest_workout['reps']}"
                )
            else:
                st.info("No workouts logged yet.")
    with rec_col:
        with styled_container():
            section_header("Quick Recommendation", kicker="Optimize")
            st.write(performance_plan["recommendation_summary"])
            st.caption(performance_plan["reasoning_explanation"])

    left, right = st.columns((1.25, 1))
    with left:
        with styled_container():
            section_header("Bodyweight Trend", "Latest body metrics entries", "Trend")
            if bodyweight_df.empty:
                st.plotly_chart(blank_figure("Bodyweight"), width="stretch")
            else:
                fig = px.line(
                    bodyweight_df,
                    x="date",
                    y="bodyweight",
                    markers=True,
                    title="Bodyweight Over Time",
                )
                fig.update_traces(line_color="#33d6a6", marker_color="#33d6a6")
                st.plotly_chart(style_plotly(fig), width="stretch")

    with right:
        with styled_container():
            section_header("Training Volume", "Strength volume by date", "Load")
            if volume_df.empty:
                st.plotly_chart(blank_figure("Strength Volume"), width="stretch")
            else:
                volume_chart = volume_df.copy()
                volume_chart["date"] = pd.to_datetime(volume_chart["date"], errors="coerce")
                fig = px.bar(
                    volume_chart,
                    x="date",
                    y="volume",
                    title="Strength Volume",
                    color_discrete_sequence=["#6ea8ff"],
                )
                st.plotly_chart(style_plotly(fig), width="stretch")


def render_nutrition_log() -> None:
    section_header(
        "Nutrition Log",
        "Reusable local logging with recent foods, favorites, meal templates, and macro analytics.",
        "Fuel",
    )

    entries_df = load_nutrition_log()
    frequent_foods_df = load_frequent_foods()
    meal_templates_df = load_meal_templates()

    ai_tab, manual_tab, quick_tab, templates_tab, today_tab, workout_tab, analytics_tab = st.tabs(
        ["AI Assist", "Log Food", "Recent & Favorites", "Meal Templates", "Today", "Workout", "Analytics"]
    )

    with ai_tab:
        section_header(
            "AI-Assisted Food Logging",
            "Convert natural language into editable macro estimates before saving.",
        )
        food_text = st.text_area(
            "Food description",
            placeholder="3 eggs, protein shake, chipotle bowl",
            key="ai_food_text",
        )
        col1, col2 = st.columns((0.35, 0.65))
        with col1:
            parse_clicked = st.button("Parse Food Text")
        with col2:
            st.caption("Uses `OPENAI_API_KEY` when available and caches repeated food text locally.")

        if parse_clicked:
            parsed_food = parse_food_text(food_text)
            st.session_state["parsed_food_entry"] = parsed_food
            if parsed_food["source"] == "fallback":
                st.warning(parsed_food["message"])
            elif parsed_food["cached"]:
                st.info(parsed_food["message"])
            else:
                st.success(parsed_food["message"])

        parsed_food = st.session_state.get("parsed_food_entry")
        if parsed_food:
            with st.form("ai_food_confirmation_form"):
                st.markdown("**Confirm Parsed Food**")
                col_a, col_b = st.columns(2)
                with col_a:
                    ai_entry_date = st.date_input("Date", value=date.today(), key="ai_entry_date")
                    ai_meal_type = st.selectbox("Meal type", MEAL_TYPES, key="ai_meal_type")
                    ai_food_name = st.text_input(
                        "Food name",
                        value=parsed_food["food_name"],
                        key="ai_food_name",
                    )
                with col_b:
                    ai_calories = st.number_input(
                        "Calories",
                        min_value=0.0,
                        value=float(parsed_food["calories"]),
                        step=10.0,
                        key="ai_calories",
                    )
                    ai_protein = st.number_input(
                        "Protein (g)",
                        min_value=0.0,
                        value=float(parsed_food["protein"]),
                        step=1.0,
                        key="ai_protein",
                    )
                    ai_carbs = st.number_input(
                        "Carbs (g)",
                        min_value=0.0,
                        value=float(parsed_food["carbs"]),
                        step=1.0,
                        key="ai_carbs",
                    )
                    ai_fat = st.number_input(
                        "Fat (g)",
                        min_value=0.0,
                        value=float(parsed_food["fat"]),
                        step=1.0,
                        key="ai_fat",
                    )
                save_ai_entry = st.form_submit_button("Save Confirmed Food")

            if save_ai_entry:
                if not ai_food_name.strip():
                    st.warning("Enter a food name before saving.")
                else:
                    entry = create_food_entry(
                        food_name=ai_food_name,
                        calories=ai_calories,
                        protein=ai_protein,
                        carbs=ai_carbs,
                        fat=ai_fat,
                        meal_type=ai_meal_type,
                        date=ai_entry_date.isoformat(),
                    )
                    entries_df = pd.concat(
                        [entries_df, pd.DataFrame([entry])],
                        ignore_index=True,
                    )
                    save_nutrition_log(entries_df)
                    st.session_state.pop("parsed_food_entry", None)
                    st.success("Confirmed AI-assisted food entry saved.")

    with manual_tab:
        with st.form("nutrition_entry_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                entry_date = st.date_input("Date", value=date.today())
                meal_type = st.selectbox("Meal type", MEAL_TYPES)
                food_name = st.text_input("Food name")
            with col2:
                calories = st.number_input("Calories", min_value=0.0, step=10.0)
                protein = st.number_input("Protein (g)", min_value=0.0, step=1.0)
                carbs = st.number_input("Carbs (g)", min_value=0.0, step=1.0)
                fat = st.number_input("Fat (g)", min_value=0.0, step=1.0)
                save_template = st.checkbox("Save as Meal Template")
                template_name = st.text_input(
                    "Template name",
                    disabled=not save_template,
                    placeholder="Post-workout meal",
                )

            submitted = st.form_submit_button("Save food entry")

        if submitted:
            if not food_name.strip():
                st.warning("Enter a food name before saving.")
            else:
                entry = create_food_entry(
                    food_name=food_name,
                    calories=calories,
                    protein=protein,
                    carbs=carbs,
                    fat=fat,
                    meal_type=meal_type,
                    date=entry_date.isoformat(),
                )
                entries_df = pd.concat(
                    [entries_df, pd.DataFrame([entry])],
                    ignore_index=True,
                )
                save_nutrition_log(entries_df)
                st.success("Food entry saved.")
                if save_template:
                    if not template_name.strip():
                        st.warning("Food saved, but template was skipped because no template name was entered.")
                    else:
                        meal_templates_df = add_meal_template(
                            template_name=template_name,
                            food_name=food_name,
                            calories=calories,
                            protein=protein,
                            carbs=carbs,
                            fat=fat,
                            default_meal_type=meal_type,
                        )
                        st.success("Meal template saved.")

    with quick_tab:
        recent_foods_df = get_recent_foods(entries_df)
        favorite_foods_df = frequent_foods_df[frequent_foods_df["is_favorite"]].copy()
        add_col, log_col = st.columns(2)
        with add_col:
            section_header("Add Reusable Food", "Save foods for one-click logging.")
            with st.form("frequent_food_form", clear_on_submit=True):
                frequent_food_name = st.text_input("Frequent food name")
                default_meal_type = st.selectbox(
                    "Default meal type",
                    MEAL_TYPES,
                    key="frequent_default_meal_type",
                )
                frequent_calories = st.number_input(
                    "Default calories",
                    min_value=0.0,
                    step=10.0,
                )
                frequent_protein = st.number_input(
                    "Default protein (g)",
                    min_value=0.0,
                    step=1.0,
                )
                frequent_carbs = st.number_input(
                    "Default carbs (g)",
                    min_value=0.0,
                    step=1.0,
                )
                frequent_fat = st.number_input(
                    "Default fat (g)",
                    min_value=0.0,
                    step=1.0,
                )
                is_favorite = st.checkbox("Mark as favorite")
                frequent_submitted = st.form_submit_button("Save frequent food")

            if frequent_submitted:
                if not frequent_food_name.strip():
                    st.warning("Enter a frequent food name before saving.")
                else:
                    frequent_foods_df = add_frequent_food(
                        food_name=frequent_food_name,
                        calories=frequent_calories,
                        protein=frequent_protein,
                        carbs=frequent_carbs,
                        fat=frequent_fat,
                        default_meal_type=default_meal_type,
                        is_favorite=is_favorite,
                    )
                    favorite_foods_df = frequent_foods_df[frequent_foods_df["is_favorite"]].copy()
                    st.success("Frequent food saved.")

        with log_col:
            with styled_container():
                section_header("One-Click Food Logging", "Log recent, frequent, or favorite foods.")
                quick_sources = ["Favorite Foods", "Frequent Foods", "Recent Foods"]
                quick_source = st.selectbox("Source", quick_sources)

                if quick_source == "Favorite Foods":
                    options_df = favorite_foods_df
                elif quick_source == "Frequent Foods":
                    options_df = frequent_foods_df
                else:
                    options_df = recent_foods_df

                if options_df.empty:
                    st.info(f"No {quick_source.lower()} available yet.")
                else:
                    name_column = "food_name"
                    selected_food_name = st.selectbox("Food", options_df[name_column].tolist())
                    selected_food = options_df[options_df[name_column] == selected_food_name].iloc[0]
                    default_meal = selected_food.get("default_meal_type", selected_food.get("meal_type", "Snack"))
                    default_index = MEAL_TYPES.index(default_meal) if default_meal in MEAL_TYPES else 0
                    override_meal_type = st.selectbox(
                        "Meal type",
                        MEAL_TYPES,
                        index=default_index,
                        key="quick_log_meal_type",
                    )
                    st.caption(
                        f"{selected_food['calories']:.0f} cal | "
                        f"{selected_food['protein']:.1f}g protein | "
                        f"{selected_food['carbs']:.1f}g carbs | "
                        f"{selected_food['fat']:.1f}g fat"
                    )
                    if st.button("Log selected food for today", key="quick_log_food"):
                        if quick_source in ["Favorite Foods", "Frequent Foods"]:
                            log_frequent_food(
                                food_name=selected_food_name,
                                date=date.today().isoformat(),
                                meal_type=override_meal_type,
                            )
                        else:
                            entry = create_food_entry(
                                food_name=selected_food["food_name"],
                                calories=selected_food["calories"],
                                protein=selected_food["protein"],
                                carbs=selected_food["carbs"],
                                fat=selected_food["fat"],
                                meal_type=override_meal_type,
                                date=date.today().isoformat(),
                            )
                            entries_df = pd.concat(
                                [entries_df, pd.DataFrame([entry])],
                                ignore_index=True,
                            )
                            save_nutrition_log(entries_df)
                        entries_df = load_nutrition_log()
                        st.success(f"Logged {selected_food_name}.")

        st.write("")
        section_header("Saved Foods")
        if frequent_foods_df.empty:
            st.info("No frequent foods saved yet.")
        else:
            st.dataframe(frequent_foods_df, width="stretch", hide_index=True)

    with templates_tab:
        create_col, log_col = st.columns(2)
        with create_col:
            section_header("Save as Meal Template", "Create a reusable full-meal macro preset.")
            with st.form("meal_template_form", clear_on_submit=True):
                template_name = st.text_input("Meal template name")
                template_food_name = st.text_input("Template food/meal name")
                template_meal_type = st.selectbox(
                    "Default meal type",
                    MEAL_TYPES,
                    key="template_default_meal_type",
                )
                template_calories = st.number_input("Template calories", min_value=0.0, step=10.0)
                template_protein = st.number_input("Template protein (g)", min_value=0.0, step=1.0)
                template_carbs = st.number_input("Template carbs (g)", min_value=0.0, step=1.0)
                template_fat = st.number_input("Template fat (g)", min_value=0.0, step=1.0)
                template_submitted = st.form_submit_button("Save as Meal Template")

            if template_submitted:
                if not template_name.strip() or not template_food_name.strip():
                    st.warning("Enter both a template name and meal name before saving.")
                else:
                    meal_templates_df = add_meal_template(
                        template_name=template_name,
                        food_name=template_food_name,
                        calories=template_calories,
                        protein=template_protein,
                        carbs=template_carbs,
                        fat=template_fat,
                        default_meal_type=template_meal_type,
                    )
                    st.success("Meal template saved.")

        with log_col:
            with styled_container():
                section_header("Log Meal Template", "One-click meal logging.")
                if meal_templates_df.empty:
                    st.info("No meal templates saved yet.")
                else:
                    selected_template = st.selectbox(
                        "Template",
                        meal_templates_df["template_name"].tolist(),
                    )
                    template = meal_templates_df[
                        meal_templates_df["template_name"] == selected_template
                    ].iloc[0]
                    default_meal = template["default_meal_type"]
                    default_index = MEAL_TYPES.index(default_meal) if default_meal in MEAL_TYPES else 0
                    template_log_meal_type = st.selectbox(
                        "Meal type",
                        MEAL_TYPES,
                        index=default_index,
                        key="template_log_meal_type",
                    )
                    st.caption(
                        f"{template['food_name']} | {template['calories']:.0f} cal | "
                        f"{template['protein']:.1f}g protein"
                    )
                    if st.button("Log Meal Template"):
                        log_meal_template(
                            selected_template,
                            date.today().isoformat(),
                            meal_type=template_log_meal_type,
                        )
                        entries_df = load_nutrition_log()
                        st.success(f"Logged {selected_template}.")

        st.write("")
        if meal_templates_df.empty:
            st.info("No meal templates saved yet.")
        else:
            st.dataframe(meal_templates_df, width="stretch", hide_index=True)

    with today_tab:
        today = date.today().isoformat()
        todays_entries = entries_df[entries_df["date"].astype(str) == today].copy()
        totals = calculate_daily_totals(entries_df, today)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            metric_card("Calories", f"{totals['calories']:.0f}", "Today")
        with col2:
            metric_card("Protein", f"{totals['protein']:.1f}g", "Today")
        with col3:
            metric_card("Carbs", f"{totals['carbs']:.1f}g", "Today")
        with col4:
            metric_card("Fat", f"{totals['fat']:.1f}g", "Today")

        st.write("")
        if todays_entries.empty:
            st.info("No foods logged for today yet.")
        else:
            st.dataframe(
                todays_entries[
                    ["meal_type", "food_name", "calories", "protein", "carbs", "fat"]
                ],
                width="stretch",
                hide_index=True,
            )

    with workout_tab:
        section_header(
            "Workout Marker",
            "Add one marker on a workout day to split same-day foods into pre- and post-workout windows.",
        )
        with st.form("workout_marker_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                marker_date = st.date_input("Workout date", value=date.today(), key="workout_marker_date")
                marker_time = st.time_input(
                    "Workout time",
                    value=datetime.now().replace(second=0, microsecond=0).time(),
                    key="workout_marker_time",
                )
            with col2:
                marker_workout_type = st.selectbox("Workout type", WORKOUT_TYPES, key="workout_marker_type")
                marker_notes = st.text_area("Notes (optional)", key="workout_marker_notes")
            marker_submitted = st.form_submit_button("Add Workout Marker")

        if marker_submitted:
            create_workout_marker(
                date=marker_date.isoformat(),
                workout_time=marker_time,
                workout_type=marker_workout_type,
                notes=marker_notes,
            )
            st.success("Workout marker added.")

        markers_df = load_workout_markers()
        training_df = load_training_log()
        windows_df = calculate_workout_nutrition_windows(entries_df, training_df, markers_df)
        recommendations = generate_workout_fueling_recommendations(windows_df, load_recovery_log())

        if markers_df.empty:
            st.info("No workout markers yet. Add a marker to split food into pre- and post-workout windows.")
        else:
            latest_window = windows_df.sort_values(["date", "workout_time"]).iloc[-1] if not windows_df.empty else None
            if latest_window is not None:
                metric_cols = st.columns(4)
                with metric_cols[0]:
                    metric_card("Pre Carbs", f"{latest_window['pre_workout_carbs']:.0f}g", "Before marker")
                with metric_cols[1]:
                    metric_card("Post Protein", f"{latest_window['post_workout_protein']:.0f}g", "After marker")
                with metric_cols[2]:
                    metric_card("Same-Day Calories", f"{latest_window['total_same_day_calories']:.0f}", "Daily total unchanged")
                with metric_cols[3]:
                    metric_card(
                        "Training Link",
                        latest_window["estimated_workout_quality"],
                        latest_window["linked_training_session"] or "No same-day training row",
                    )
                if latest_window["unknown_timing_calories"] > 0:
                    st.caption(
                        f"{latest_window['unknown_timing_calories']:.0f} calories have unknown timing because those food rows do not have a same-day timestamp."
                    )

            st.write("")
            st.dataframe(
                windows_df[
                    [
                        "date",
                        "workout_time",
                        "workout_type",
                        "pre_workout_carbs",
                        "pre_workout_protein",
                        "pre_workout_fat",
                        "post_workout_carbs",
                        "post_workout_protein",
                        "post_workout_fat",
                        "total_same_day_calories",
                        "linked_training_session",
                        "estimated_workout_quality",
                    ]
                ].sort_values(["date", "workout_time"], ascending=False),
                width="stretch",
                hide_index=True,
            )

        with styled_container():
            section_header("Fueling Notes")
            st.write(f"**Deload status:** {recommendations['deload_status']}")
            st.write(recommendations["pre_workout_carb_suggestion"])
            st.write(recommendations["post_workout_recovery_suggestion"])

    with analytics_tab:
        target_col1, target_col2 = st.columns(2)
        with target_col1:
            target_calories = st.number_input(
                "Analytics target calories",
                min_value=0,
                value=2850,
                step=50,
            )
        with target_col2:
            target_protein = st.number_input(
                "Analytics target protein (g)",
                min_value=0,
                value=160,
                step=5,
            )

        analytics_df = calculate_nutrition_analytics(
            entries_df,
            target_calories=target_calories,
            target_protein=target_protein,
        )
        common_foods_df = get_most_common_foods(entries_df)

        if analytics_df.empty:
            st.info("Log nutrition data to populate analytics.")
        else:
            latest = analytics_df.iloc[-1]
            col1, col2, col3 = st.columns(3)
            with col1:
                metric_card("7-Day Calories", f"{latest['rolling_calories']:.0f}", "Rolling average")
            with col2:
                metric_card("Protein Consistency", f"{latest['protein_consistency']:.0f}%", "Days at target")
            with col3:
                metric_card("Calorie Adherence", f"{latest['calorie_adherence']:.0f}%", "Today vs target")

            chart_df = analytics_df.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
            row1_col1, row1_col2 = st.columns(2)
            with row1_col1:
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=chart_df["date"],
                        y=chart_df["calories"],
                        mode="lines+markers",
                        name="Calories",
                        line=dict(color="#33d6a6"),
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=chart_df["date"],
                        y=chart_df["rolling_calories"],
                        mode="lines",
                        name="Rolling avg",
                        line=dict(color="#6ea8ff"),
                    )
                )
                fig.update_layout(title="Calories Over Time")
                st.plotly_chart(style_plotly(fig), width="stretch")

            with row1_col2:
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=chart_df["date"],
                        y=chart_df["protein"],
                        mode="lines+markers",
                        name="Protein",
                        line=dict(color="#f4b860"),
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=chart_df["date"],
                        y=chart_df["rolling_protein"],
                        mode="lines",
                        name="Rolling avg",
                        line=dict(color="#6ea8ff"),
                    )
                )
                fig.update_layout(title="Protein Over Time")
                st.plotly_chart(style_plotly(fig), width="stretch")

            row2_col1, row2_col2 = st.columns(2)
            with row2_col1:
                latest_macro = analytics_df.iloc[-1]
                fig = px.pie(
                    names=["Carbs", "Protein", "Fat"],
                    values=[
                        latest_macro["carbs_pct"],
                        latest_macro["protein_pct"],
                        latest_macro["fat_pct"],
                    ],
                    title="Macro Split",
                    color_discrete_sequence=["#6ea8ff", "#33d6a6", "#f4b860"],
                )
                st.plotly_chart(style_plotly(fig), width="stretch")

            with row2_col2:
                fig = go.Figure()
                fig.add_trace(
                    go.Scatter(
                        x=chart_df["date"],
                        y=chart_df["calorie_adherence"],
                        mode="lines+markers",
                        name="Calorie adherence",
                        line=dict(color="#33d6a6"),
                    )
                )
                fig.add_trace(
                    go.Scatter(
                        x=chart_df["date"],
                        y=chart_df["protein_adherence"],
                        mode="lines+markers",
                        name="Protein adherence",
                        line=dict(color="#f4b860"),
                    )
                )
                fig.update_layout(title="Macro Adherence Trends", yaxis_title="% of target")
                st.plotly_chart(style_plotly(fig), width="stretch")

        section_header("Most Common Foods")
        if common_foods_df.empty:
            st.info("No common foods yet.")
        else:
            st.dataframe(common_foods_df, width="stretch", hide_index=True)


def render_body_metrics() -> None:
    section_header("Body Metrics", "Track bodyweight and simple composition markers.", "Trend")

    metrics_df = load_body_metrics()
    form_col, chart_col = st.columns((0.9, 1.1))

    with form_col:
        with st.form("body_metrics_form", clear_on_submit=True):
            metric_date = st.date_input("Date", value=date.today(), key="body_metric_date")
            bodyweight = st.number_input("Bodyweight", min_value=0.0, step=0.1)
            waist = st.number_input("Waist (optional)", min_value=0.0, step=0.1)
            estimated_body_fat = st.number_input(
                "Estimated body fat % (optional)",
                min_value=0.0,
                max_value=100.0,
                step=0.1,
            )
            notes = st.text_area("Notes (optional)")
            submitted = st.form_submit_button("Save body metric entry")

        if submitted:
            if bodyweight <= 0:
                st.warning("Enter a bodyweight greater than zero before saving.")
            else:
                metrics_df = add_body_metric_entry(
                    date=metric_date.isoformat(),
                    bodyweight=bodyweight,
                    waist=None if waist == 0 else waist,
                    estimated_body_fat=None if estimated_body_fat == 0 else estimated_body_fat,
                    notes=notes,
                )
                st.success("Body metric entry saved.")

    with chart_col:
        with styled_container():
            _, chart_df = get_bodyweight_trend(metrics_df)
            if chart_df.empty:
                st.plotly_chart(blank_figure("Bodyweight Trend"), width="stretch")
            else:
                fig = px.line(
                    chart_df,
                    x="date",
                    y="bodyweight",
                    markers=True,
                    title="Bodyweight Trend",
                )
                fig.update_traces(line_color="#33d6a6", marker_color="#33d6a6")
                st.plotly_chart(style_plotly(fig), width="stretch")

    section_header("History")
    if metrics_df.empty:
        st.info("No body metrics logged yet.")
    else:
        st.dataframe(
            metrics_df.sort_values("date", ascending=False),
            width="stretch",
            hide_index=True,
        )


def render_bodyweight_entry_panel() -> pd.DataFrame:
    metrics_df = load_body_metrics()
    with st.form("bodyweight_entry_form", clear_on_submit=True):
        metric_date = st.date_input("Date", value=date.today(), key="weight_recovery_body_date")
        bodyweight = st.number_input("Bodyweight", min_value=0.0, step=0.1, key="weight_recovery_bodyweight")
        waist = st.number_input("Waist (optional)", min_value=0.0, step=0.1, key="weight_recovery_waist")
        estimated_body_fat = st.number_input(
            "Estimated body fat % (optional)",
            min_value=0.0,
            max_value=100.0,
            step=0.1,
            key="weight_recovery_body_fat",
        )
        notes = st.text_area("Notes (optional)", key="weight_recovery_body_notes")
        submitted = st.form_submit_button("Save bodyweight entry")

    if submitted:
        if bodyweight <= 0:
            st.warning("Enter a bodyweight greater than zero before saving.")
        else:
            metrics_df = add_body_metric_entry(
                date=metric_date.isoformat(),
                bodyweight=bodyweight,
                waist=None if waist == 0 else waist,
                estimated_body_fat=None if estimated_body_fat == 0 else estimated_body_fat,
                notes=notes,
            )
            st.success("Bodyweight entry saved.")
    return metrics_df


def render_recovery_entry_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    recovery_df = load_recovery_log()
    training_df = load_training_log()
    nutrition_df = load_nutrition_log()
    with st.form("weight_recovery_check_in_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            recovery_date = st.date_input("Date", value=date.today(), key="weight_recovery_date")
            sleep_hours = st.number_input("Sleep hours", min_value=0.0, max_value=24.0, step=0.25, key="weight_recovery_sleep")
            sleep_quality = st.slider("Sleep quality", 1, 10, 5, key="weight_recovery_sleep_quality")
            fatigue = st.slider("Fatigue", 1, 10, 5, key="weight_recovery_fatigue")
            soreness = st.slider("Soreness", 1, 10, 5, key="weight_recovery_soreness")
        with col2:
            stress = st.slider("Stress", 1, 10, 5, key="weight_recovery_stress")
            motivation = st.slider("Motivation", 1, 10, 5, key="weight_recovery_motivation")
            resting_hr = st.number_input("Resting HR (optional)", min_value=0.0, step=1.0, key="weight_recovery_resting_hr")
            hrv = st.number_input("HRV (optional)", min_value=0.0, step=1.0, key="weight_recovery_hrv")
            notes = st.text_area("Notes (optional)", key="weight_recovery_recovery_notes")
        submitted = st.form_submit_button("Save recovery check-in")

    if submitted:
        recovery_df = add_recovery_entry(
            date=recovery_date.isoformat(),
            sleep_hours=sleep_hours,
            sleep_quality=sleep_quality,
            fatigue=fatigue,
            soreness=soreness,
            stress=stress,
            motivation=motivation,
            resting_hr=None if resting_hr == 0 else resting_hr,
            hrv=None if hrv == 0 else hrv,
            notes=notes,
        )
        st.success("Recovery check-in saved.")

    analytics_df = calculate_advanced_recovery_score(
        recovery_df=recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
    )
    return recovery_df, analytics_df


def render_fueling_deload_signals_panel() -> None:
    markers_df = load_workout_markers()
    nutrition_df = load_nutrition_log()
    training_df = load_training_log()
    recovery_df = load_recovery_log()
    windows_df = calculate_workout_nutrition_windows(nutrition_df, training_df, markers_df)
    recommendations = generate_workout_fueling_recommendations(windows_df, recovery_df)

    with styled_container():
        section_header(
            "Fueling & Deload Signals",
            "Uses Food workout markers to connect pre/post-workout nutrition with training and recovery.",
        )
        if markers_df.empty:
            st.info("No workout marker data yet. Add a Workout marker in the Food tab to unlock fueling windows.")
            return

        col1, col2, col3 = st.columns(3)
        with col1:
            metric_card("Deload Status", recommendations["deload_status"], recommendations["recovery_signal"])
        with col2:
            metric_card("Pre-Workout Carbs", "Review", recommendations["pre_workout_carb_suggestion"])
        with col3:
            metric_card("Post-Workout Recovery", "Review", recommendations["post_workout_recovery_suggestion"])

        st.caption(recommendations["recent_improvement_signal"])
        if not windows_df.empty:
            latest = windows_df.sort_values(["date", "workout_time"]).iloc[-1]
            st.caption(
                f"Latest marker: {latest['date']} {latest['workout_time']} | "
                f"{latest['workout_type']} | {latest['estimated_workout_quality']}"
            )


def render_training_log() -> None:
    section_header("Training Log", "Log sessions and monitor strength volume.", "Load")

    training_df = load_training_log()
    strava_tab, import_tab, entry_tab, running_tab, volume_tab = st.tabs(
        ["Strava Import", "Hevy Import", "Log Training", "Running Dashboard", "Volume"]
    )

    with strava_tab:
        with styled_container():
            section_header(
                "Strava Run Import",
                "Placeholder for future OAuth-based run and cardio syncing.",
                "Integration",
            )
            st.write("Strava will import runs, cardio sessions, distance, pace, and estimated running load.")
            st.info("Configure Strava client credentials in Integrations / Settings. Full OAuth syncing is not enabled yet.")

    with import_tab:
        with styled_container():
            section_header(
                "Hevy Lifting Import",
                "Placeholder for future lifting workout syncing.",
                "Integration",
            )
            st.write("Hevy will import lifting workouts, exercises, sets, reps, weights, and RPE.")
            st.info("Save your Hevy API key in Integrations / Settings. Full syncing is intentionally deferred.")

    with entry_tab:
        with st.form("training_log_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                training_date = st.date_input("Date", value=date.today(), key="training_date")
                workout_type = st.selectbox("Workout type", WORKOUT_TYPES)
                muscle_group = st.text_input("Muscle group")
                exercise = st.text_input("Exercise")
                duration_minutes = st.number_input("Duration minutes", min_value=0.0, step=5.0)
            with col2:
                sets = st.number_input("Sets", min_value=0, step=1)
                reps = st.number_input("Reps", min_value=0, step=1)
                weight = st.number_input("Weight", min_value=0.0, step=5.0)
                rpe = st.number_input("RPE", min_value=0.0, max_value=10.0, step=0.5)
                notes = st.text_area("Notes")
            submitted = st.form_submit_button("Save training entry")

        if submitted:
            training_df = add_training_entry(
                date=training_date.isoformat(),
                workout_type=workout_type,
                muscle_group=muscle_group,
                exercise=exercise,
                sets=sets,
                reps=reps,
                weight=weight,
                rpe=rpe,
                duration_minutes=duration_minutes,
                notes=notes,
            )
            st.success("Training entry saved.")

        if training_df.empty:
            st.info("No training entries logged yet.")
        else:
            st.dataframe(
                training_df.sort_values("date", ascending=False).head(20),
                width="stretch",
                hide_index=True,
            )

    with volume_tab:
        volume_df = calculate_training_volume(training_df)
        if volume_df.empty:
            st.info("No strength training volume logged yet.")
        else:
            chart_df = volume_df.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
            fig = px.bar(
                chart_df,
                x="date",
                y="volume",
                title="Strength Volume by Date",
                color_discrete_sequence=["#6ea8ff"],
            )
            st.plotly_chart(style_plotly(fig), width="stretch")
            st.dataframe(volume_df, width="stretch", hide_index=True)

    with running_tab:
        running_df = calculate_running_analytics(training_df)
        if running_df.empty:
            st.info("No imported or logged runs available yet.")
        else:
            latest = running_df.iloc[-1]
            col1, col2, col3 = st.columns(3)
            with col1:
                metric_card("Weekly Mileage", f"{latest['weekly_mileage']:.1f}", "Rolling 7-day miles")
            with col2:
                metric_card("Latest Pace", f"{latest['pace_min_per_mile']:.2f}", "min / mile")
            with col3:
                metric_card("Run Load", f"{latest['estimated_run_load']:.1f}", "Estimated latest run load")

            chart_df = running_df.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
            row1_col1, row1_col2 = st.columns(2)
            with row1_col1:
                fig = px.line(
                    chart_df,
                    x="date",
                    y="weekly_mileage",
                    markers=True,
                    title="Weekly Mileage",
                    color_discrete_sequence=["#33d6a6"],
                )
                st.plotly_chart(style_plotly(fig), width="stretch")

            with row1_col2:
                fig = px.line(
                    chart_df,
                    x="date",
                    y="pace_min_per_mile",
                    markers=True,
                    title="Mile Pace Trend",
                    color_discrete_sequence=["#f4b860"],
                )
                fig.update_yaxes(autorange="reversed")
                st.plotly_chart(style_plotly(fig), width="stretch")

            row2_col1, row2_col2 = st.columns(2)
            with row2_col1:
                fig = px.bar(
                    chart_df,
                    x="date",
                    y="distance_miles",
                    title="Distance Trend",
                    color_discrete_sequence=["#6ea8ff"],
                )
                st.plotly_chart(style_plotly(fig), width="stretch")

            with row2_col2:
                fig = px.line(
                    chart_df,
                    x="date",
                    y="estimated_run_load",
                    markers=True,
                    title="Estimated Running Load",
                    color_discrete_sequence=["#ff6b6b"],
                )
                st.plotly_chart(style_plotly(fig), width="stretch")

            st.dataframe(running_df.sort_values("date", ascending=False), width="stretch", hide_index=True)


def render_recovery_check_in() -> None:
    section_header(
        "Recovery Check-In",
        "Capture readiness signals and track fatigue, sleep debt, training stress, and fueling impact.",
        "Readiness",
    )

    recovery_df = load_recovery_log()
    training_df = load_training_log()
    nutrition_df = load_nutrition_log()
    analytics_df = calculate_advanced_recovery_score(
        recovery_df=recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
    )
    form_col, score_col = st.columns((1, 1))

    with form_col:
        with st.form("recovery_check_in_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                recovery_date = st.date_input("Date", value=date.today(), key="recovery_date")
                sleep_hours = st.number_input("Sleep hours", min_value=0.0, max_value=24.0, step=0.25)
                sleep_quality = st.slider("Sleep quality", 1, 10, 5)
                fatigue = st.slider("Fatigue", 1, 10, 5)
                soreness = st.slider("Soreness", 1, 10, 5)
            with col2:
                stress = st.slider("Stress", 1, 10, 5)
                motivation = st.slider("Motivation", 1, 10, 5)
                resting_hr = st.number_input("Resting HR (optional)", min_value=0.0, step=1.0)
                hrv = st.number_input("HRV (optional)", min_value=0.0, step=1.0)
                notes = st.text_area("Notes (optional)")
            submitted = st.form_submit_button("Save recovery check-in")

        if submitted:
            recovery_df = add_recovery_entry(
                date=recovery_date.isoformat(),
                sleep_hours=sleep_hours,
                sleep_quality=sleep_quality,
                fatigue=fatigue,
                soreness=soreness,
                stress=stress,
                motivation=motivation,
                resting_hr=None if resting_hr == 0 else resting_hr,
                hrv=None if hrv == 0 else hrv,
                notes=notes,
            )
            analytics_df = calculate_advanced_recovery_score(
                recovery_df=recovery_df,
                training_df=training_df,
                nutrition_df=nutrition_df,
            )
            st.success("Recovery check-in saved.")

    with score_col:
        if analytics_df.empty:
            metric_card("Latest Recovery Score", "No data", "Log recovery data to start scoring.")
            st.info("No recovery check-ins logged yet.")
        else:
            latest = analytics_df.sort_values("date").iloc[-1]
            metric_card(
                "Latest Recovery Score",
                f"{latest['recovery_score']:.1f}",
                f"{latest['classification']} | deterministic fatigue model",
            )
            st.write("")
            with styled_container():
                section_header("Why It Changed")
                st.write(latest["explanation"])

    if analytics_df.empty:
        return

    st.write("")
    col1, col2 = st.columns(2)
    trend_df = analytics_df.copy()
    trend_df["date"] = pd.to_datetime(trend_df["date"], errors="coerce")

    with col1:
        with styled_container():
            fig = px.line(
                trend_df,
                x="date",
                y="recovery_score",
                color="classification",
                markers=True,
                title="Recovery Trend",
                color_discrete_map={
                    "Optimal": "#33d6a6",
                    "Moderate": "#6ea8ff",
                    "Fatigued": "#f4b860",
                    "High Risk": "#ff6b6b",
                },
            )
            st.plotly_chart(style_plotly(fig), width="stretch")

    with col2:
        with styled_container():
            fig = px.line(
                trend_df,
                x="date",
                y="fatigue_load",
                markers=True,
                title="Fatigue and Soreness Load",
                color_discrete_sequence=["#f4b860"],
            )
            st.plotly_chart(style_plotly(fig), width="stretch")

    col3, col4 = st.columns(2)
    with col3:
        with styled_container():
            fig = px.line(
                trend_df,
                x="date",
                y="sleep_debt",
                markers=True,
                title="Rolling Sleep Debt",
                color_discrete_sequence=["#6ea8ff"],
            )
            st.plotly_chart(style_plotly(fig), width="stretch")

    with col4:
        with styled_container():
            fig = px.bar(
                trend_df,
                x="date",
                y="training_stress",
                title="Training Stress Trend",
                color_discrete_sequence=["#ff6b6b"],
            )
            st.plotly_chart(style_plotly(fig), width="stretch")

    section_header("Recent Recovery Analytics")
    st.dataframe(
        analytics_df.sort_values("date", ascending=False).head(14),
        width="stretch",
        hide_index=True,
    )


def render_recommendations() -> None:
    section_header(
        "Recommendations",
        "Adaptive deterministic guidance from recovery, training, nutrition, and bodyweight trends.",
        "Decision Support",
    )

    with st.form("recommendation_settings_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            goal = st.selectbox("Goal", ["lean bulk", "maintenance", "fat loss"])
        with col2:
            target_calories = st.number_input("Target calories", min_value=0, value=2850, step=50)
        with col3:
            target_protein = st.number_input("Target protein (g)", min_value=0, value=160, step=5)
        submitted = st.form_submit_button("Generate recommendations")

    nutrition_df = load_nutrition_log()
    body_metrics_df = load_body_metrics()
    recovery_df = load_recovery_log()
    training_df = load_training_log()

    recommendation = generate_daily_recommendation(
        nutrition_df=nutrition_df,
        body_metrics_df=body_metrics_df,
        recovery_df=recovery_df,
        training_df=training_df,
        target_calories=target_calories,
        target_protein=target_protein,
        goal=goal,
    )
    performance_plan = generate_performance_recommendations(
        recovery_df=recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
        body_metrics_df=body_metrics_df,
        target_calories=target_calories,
        target_protein=target_protein,
        goal=goal,
    )

    if submitted:
        st.success("Recommendations updated.")

    metric_col1, metric_col2 = st.columns((1.4, 0.6))
    with metric_col1:
        metric_card(
            "Optimization Summary",
            performance_plan["recommendation_summary"],
            performance_plan["reasoning_explanation"],
        )
    with metric_col2:
        metric_card(
            "Confidence",
            performance_plan["confidence_level"],
            "Based on available recovery, nutrition, bodyweight, and training trend coverage",
        )

    st.write("")
    if performance_plan["recommendations"]:
        st.dataframe(
            pd.DataFrame(performance_plan["recommendations"]),
            width="stretch",
            hide_index=True,
        )

    st.write("")
    col1, col2 = st.columns(2)
    with col1:
        metric_card("Recovery Status", recommendation["recovery_status"], recommendation["short_summary"])
        st.write("")
        with styled_container():
            section_header("Nutrition")
            st.write(recommendation["calorie_recommendation"])
            st.write(recommendation["protein_recommendation"])
    with col2:
        with styled_container():
            section_header("Training")
            st.write(recommendation["training_recommendation"])
        st.write("")
        with styled_container():
            section_header("Logic")
            st.markdown(
                """
                - Compare today's calories and protein to targets.
                - Use latest recovery score for training intensity.
                - Use recent bodyweight trend for lean bulk calorie adjustments.
                - Include recent strength volume for load context.
                """
            )


def render_goals_targets() -> None:
    section_header(
        "Goals & Targets",
        "Set conservative calorie and macro targets from bodyweight goals, timeline, and training demands.",
        "Planning",
    )
    st.caption(
        "Fitness-oriented planning only. This is not medical advice, and targets should be adjusted based on performance, recovery, and real bodyweight trends."
    )

    goals = load_user_goals()
    body_metrics_df = load_body_metrics()
    nutrition_df = load_nutrition_log()
    recovery_df = load_recovery_log()
    training_df = load_training_log()

    with st.form("goals_targets_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            current_bodyweight = st.number_input(
                "Current bodyweight",
                min_value=50.0,
                max_value=500.0,
                value=float(goals["current_bodyweight"]),
                step=0.5,
            )
            goal_type = st.selectbox(
                "Goal type",
                GOAL_TYPES,
                index=GOAL_TYPES.index(goals["goal_type"]) if goals["goal_type"] in GOAL_TYPES else 0,
            )
            training_frequency = st.number_input(
                "Training frequency per week",
                min_value=0,
                max_value=14,
                value=int(goals["training_frequency_per_week"]),
                step=1,
            )
        with col2:
            goal_bodyweight = st.number_input(
                "Goal bodyweight",
                min_value=50.0,
                max_value=500.0,
                value=float(goals["goal_bodyweight"]),
                step=0.5,
            )
            activity_level = st.selectbox(
                "Activity level",
                ACTIVITY_LEVELS,
                index=ACTIVITY_LEVELS.index(goals["activity_level"]) if goals["activity_level"] in ACTIVITY_LEVELS else 1,
            )
            cardio_frequency = st.number_input(
                "Cardio frequency per week",
                min_value=0,
                max_value=14,
                value=int(goals["cardio_frequency_per_week"]),
                step=1,
            )
        with col3:
            timeline_weeks = st.number_input(
                "Timeline in weeks",
                min_value=1,
                max_value=104,
                value=int(goals["timeline_weeks"]),
                step=1,
            )
            aggressiveness = st.selectbox(
                "Preferred aggressiveness",
                AGGRESSIVENESS_LEVELS,
                index=(
                    AGGRESSIVENESS_LEVELS.index(goals["aggressiveness"])
                    if goals["aggressiveness"] in AGGRESSIVENESS_LEVELS
                    else 0
                ),
            )
            estimated_body_fat = st.number_input(
                "Estimated body fat % optional",
                min_value=0.0,
                max_value=60.0,
                value=float(goals["estimated_body_fat"] or 0.0),
                step=0.5,
            )

        submitted = st.form_submit_button("Save Goals & Calculate Targets")

    pending_goals = {
        "current_bodyweight": current_bodyweight,
        "goal_bodyweight": goal_bodyweight,
        "timeline_weeks": timeline_weeks,
        "goal_type": goal_type,
        "training_frequency_per_week": training_frequency,
        "cardio_frequency_per_week": cardio_frequency,
        "estimated_body_fat": None if estimated_body_fat <= 0 else estimated_body_fat,
        "activity_level": activity_level,
        "aggressiveness": aggressiveness,
    }
    targets = calculate_macro_targets(pending_goals)

    if submitted:
        goals = save_user_goals(pending_goals)
        targets = save_nutrition_targets(calculate_macro_targets(goals))
        st.success("Goals and nutrition targets saved locally.")
    else:
        goals = pending_goals

    feasibility = calculate_goal_feasibility(goals)
    weight_feedback = analyze_weight_trend(body_metrics_df, goals)

    st.write("")
    target_cols = st.columns(4)
    with target_cols[0]:
        metric_card("Target Calories", f"{targets['target_calories']:.0f}", f"Maintenance estimate: {targets['maintenance_calories']:.0f}")
    with target_cols[1]:
        metric_card("Protein", f"{targets['protein_grams']:.0f}g", f"{targets['protein_per_lb']:.2f} g/lb bodyweight")
    with target_cols[2]:
        metric_card("Carbs", f"{targets['carb_grams']:.0f}g", "Remaining calories after protein and fats")
    with target_cols[3]:
        metric_card("Fat", f"{targets['fat_grams']:.0f}g", "Minimum 20% of calories from fat")

    st.write("")
    col1, col2 = st.columns(2)
    with col1:
        with styled_container():
            section_header("Timeline Feasibility", kicker="Goal Pace")
            st.write(f"**Status:** {feasibility['status']}")
            st.write(f"**Expected weekly change from goal timeline:** {feasibility['weekly_change']:+.2f} lb/week")
            st.write(f"**Target engine weekly change:** {targets['expected_weekly_weight_change']:+.2f} lb/week")
            st.caption(feasibility["warning"])
            if goals["goal_type"] == "Lean Bulk":
                st.info(
                    "Lean bulk mode is optimized for slow muscle gain while minimizing fat gain. Conservative pacing targets roughly 0.25% bodyweight gain per week; moderate to aggressive pacing stays near 0.25% to 0.5%."
                )
            st.write(targets["target_description"])

    with col2:
        with styled_container():
            section_header("Weight Trend Feedback", kicker="Adjustment")
            trend_label = (
                "No trend yet"
                if weight_feedback["weekly_change_pct"] is None
                else f"{weight_feedback['weekly_change_pct']:+.2f}% bodyweight/week"
            )
            metric_card("Current Weight Trend", trend_label, f"Window used: {weight_feedback['window_used']}")
            st.write("")
            metric_card("Suggested Calorie Adjustment", weight_feedback["suggested_adjustment"], weight_feedback["reason"])

    st.write("")
    with styled_container():
        section_header("Micronutrient Suggestions", "Food-first performance support, not deficiency diagnosis.", "Food Quality")
        suggestions = generate_micronutrient_suggestions(
            nutrition_log_df=nutrition_df,
            recovery_df=recovery_df,
            training_df=training_df,
            user_goals=goals,
        )
        suggestion_cols = st.columns(3)
        for index, suggestion in enumerate(suggestions):
            with suggestion_cols[index % 3]:
                st.markdown(f"**{suggestion['nutrient']}**")
                st.caption(suggestion["focus"])
                st.write(suggestion["food_first_options"])
                st.caption(suggestion["why_it_matters"])
                if suggestion["note"]:
                    st.warning(suggestion["note"])
                st.divider()

        st.caption(
            "General references used for this rule set: NIH Office of Dietary Supplements fact sheets, Academy of Nutrition and Dietetics / ACSM sports nutrition guidance, and ISSN protein/body composition guidance."
        )


def render_data_history() -> None:
    section_header("Data & History", "Review local CSV-backed logs, charts, and tables.", "History")
    nutrition_df = load_nutrition_log()
    body_metrics_df = load_body_metrics()
    training_df = load_training_log()
    recovery_df = load_recovery_log()

    nutrition_tab, weight_tab, workout_tab, recovery_tab = st.tabs(
        ["Nutrition", "Bodyweight", "Workouts", "Recovery"]
    )

    with nutrition_tab:
        analytics_df = calculate_nutrition_analytics(nutrition_df)
        if analytics_df.empty:
            st.info("No nutrition history yet.")
        else:
            chart_df = analytics_df.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
            fig = px.line(chart_df, x="date", y=["calories", "protein"], markers=True, title="Nutrition History")
            st.plotly_chart(style_plotly(fig), width="stretch")
            st.dataframe(nutrition_df.sort_values("date", ascending=False), width="stretch", hide_index=True)

    with weight_tab:
        _, chart_df = get_bodyweight_trend(body_metrics_df)
        if chart_df.empty:
            st.info("No bodyweight history yet.")
        else:
            fig = px.line(chart_df, x="date", y="bodyweight", markers=True, title="Bodyweight History")
            st.plotly_chart(style_plotly(fig), width="stretch")
            st.dataframe(body_metrics_df.sort_values("date", ascending=False), width="stretch", hide_index=True)

    with workout_tab:
        volume_df = calculate_training_volume(training_df)
        if training_df.empty:
            st.info("No workout history yet.")
        else:
            if not volume_df.empty:
                fig = px.bar(volume_df, x="date", y="volume", title="Strength Volume History")
                st.plotly_chart(style_plotly(fig), width="stretch")
            st.dataframe(training_df.sort_values("date", ascending=False), width="stretch", hide_index=True)

    with recovery_tab:
        analytics_df = calculate_advanced_recovery_score(
            recovery_df=recovery_df,
            training_df=training_df,
            nutrition_df=nutrition_df,
        )
        if analytics_df.empty:
            st.info("No recovery history yet.")
        else:
            chart_df = analytics_df.copy()
            chart_df["date"] = pd.to_datetime(chart_df["date"], errors="coerce")
            fig = px.line(chart_df, x="date", y="recovery_score", color="classification", markers=True, title="Recovery History")
            st.plotly_chart(style_plotly(fig), width="stretch")
            st.dataframe(analytics_df.sort_values("date", ascending=False), width="stretch", hide_index=True)


def render_weight_recovery() -> None:
    section_header("Weight & Recovery", "Log bodyweight, sleep, fatigue, soreness, stress, and motivation.", "Recovery")
    weight_tab, recovery_tab, health_tab = st.tabs(["Bodyweight", "Recovery Check-In", "Fitbit / Google Health"])
    with weight_tab:
        col1, col2 = st.columns((0.9, 1.1))
        with col1:
            metrics_df = render_bodyweight_entry_panel()
        with col2:
            with styled_container():
                _, chart_df = get_bodyweight_trend(metrics_df)
                if chart_df.empty:
                    st.plotly_chart(blank_figure("Bodyweight Trend"), width="stretch")
                else:
                    fig = px.line(chart_df, x="date", y="bodyweight", markers=True, title="Bodyweight Trend")
                    fig.update_traces(line_color="#33d6a6", marker_color="#33d6a6")
                    st.plotly_chart(style_plotly(fig), width="stretch")
    with recovery_tab:
        col1, col2 = st.columns((1, 1))
        with col1:
            _, analytics_df = render_recovery_entry_panel()
        with col2:
            if analytics_df.empty:
                metric_card("Latest Recovery Score", "No data", "Log recovery data to start scoring.")
            else:
                latest = analytics_df.sort_values("date").iloc[-1]
                metric_card(
                    "Latest Recovery Score",
                    f"{latest['recovery_score']:.1f}",
                    f"{latest['classification']} | {latest['explanation']}",
                )
                trend_df = analytics_df.copy()
                trend_df["date"] = pd.to_datetime(trend_df["date"], errors="coerce")
                fig = px.line(trend_df, x="date", y="recovery_score", markers=True, title="Recovery Trend")
                st.plotly_chart(style_plotly(fig), width="stretch")
    with health_tab:
        st.info("Fitbit and Google Health will import sleep, HRV, resting HR, and recovery metrics after OAuth setup is added.")
        st.write("For now, use the Recovery Entry tab for manual logging.")

    st.write("")
    render_fueling_deload_signals_panel()


def render_integration_status(label: str, status: str, detail: str) -> None:
    with styled_container():
        st.markdown(f"**{label}**")
        st.caption(detail)
        st.write(f"Status: `{status}`")


def render_integrations_settings() -> None:
    section_header("Integrations / Settings", "Store local connection info for future integrations.", "Settings")
    settings = load_settings()
    integrations = settings["integrations"]

    status_col1, status_col2, status_col3 = st.columns(3)
    with status_col1:
        render_integration_status("Hevy", integration_status("hevy_api_key", settings), "Will import lifting workouts.")
        render_integration_status("OpenAI", integration_status("openai_api_key", settings), "Will power optional natural language food parsing.")
    with status_col2:
        render_integration_status("Strava", integration_status("strava_client_id", settings), "Will import runs and cardio after OAuth setup.")
        render_integration_status("Apple Health", integration_status("apple_health_export_file", settings), "Local export upload first, API later.")
    with status_col3:
        render_integration_status("Fitbit / Google Health", integration_status("fitbit_client_id", settings), "Will import sleep, HRV, resting HR, and recovery metrics.")

    st.write("")
    with st.form("integration_settings_form"):
        st.markdown("**API Keys & Client Settings**")
        hevy_api_key = st.text_input("Hevy API key", value=integrations["hevy_api_key"], type="password")
        strava_client_id = st.text_input("Strava client ID", value=integrations["strava_client_id"])
        strava_client_secret = st.text_input("Strava client secret", value=integrations["strava_client_secret"], type="password")
        fitbit_client_id = st.text_input("Fitbit client ID", value=integrations["fitbit_client_id"])
        fitbit_client_secret = st.text_input("Fitbit client secret", value=integrations["fitbit_client_secret"], type="password")
        openai_api_key = st.text_input("OpenAI API key", value=integrations["openai_api_key"], type="password")
        apple_health_export_file = st.text_input(
            "Apple Health export file path",
            value=integrations["apple_health_export_file"],
            placeholder="Placeholder: local export upload support comes later",
        )
        submitted = st.form_submit_button("Save Settings")

    if submitted:
        settings["integrations"].update(
            {
                "hevy_api_key": hevy_api_key,
                "strava_client_id": strava_client_id,
                "strava_client_secret": strava_client_secret,
                "fitbit_client_id": fitbit_client_id,
                "fitbit_client_secret": fitbit_client_secret,
                "openai_api_key": openai_api_key,
                "apple_health_export_file": apple_health_export_file,
            }
        )
        save_settings(settings)
        st.success("Settings saved locally.")
        integrations = settings["integrations"]

    st.markdown("**Saved Values**")
    st.dataframe(
        pd.DataFrame(
            [
                {"Setting": "Hevy API key", "Value": mask_secret(integrations["hevy_api_key"]), "Status": integration_status("hevy_api_key", settings)},
                {"Setting": "Strava client ID", "Value": mask_secret(integrations["strava_client_id"]), "Status": integration_status("strava_client_id", settings)},
                {"Setting": "Strava client secret", "Value": mask_secret(integrations["strava_client_secret"]), "Status": integration_status("strava_client_secret", settings)},
                {"Setting": "Fitbit client ID", "Value": mask_secret(integrations["fitbit_client_id"]), "Status": integration_status("fitbit_client_id", settings)},
                {"Setting": "Fitbit client secret", "Value": mask_secret(integrations["fitbit_client_secret"]), "Status": integration_status("fitbit_client_secret", settings)},
                {"Setting": "OpenAI API key", "Value": mask_secret(integrations["openai_api_key"]), "Status": integration_status("openai_api_key", settings)},
                {"Setting": "Apple Health export", "Value": integrations["apple_health_export_file"] or "Not configured", "Status": integration_status("apple_health_export_file", settings)},
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    st.info("Settings are stored locally in `data/processed/user_settings.json`, which is ignored by git.")


def render_sidebar() -> str:
    with st.sidebar:
        st.markdown("### Performance OS")
        st.caption("Local-first performance dashboard")
        st.divider()
        selected_page = st.radio("Navigation", PAGES, label_visibility="collapsed")
        st.divider()
        st.caption("Data stays local in `data/processed`.")
    return selected_page


apply_theme()
selected_page = render_sidebar()
render_app_header()
st.write("")

if selected_page == "Dashboard":
    render_dashboard()
elif selected_page == "Goals & Targets":
    render_goals_targets()
elif selected_page == "Food":
    render_nutrition_log()
elif selected_page == "Data & History":
    render_data_history()
elif selected_page == "Weight & Recovery":
    render_weight_recovery()
elif selected_page == "Training":
    render_training_log()
elif selected_page == "Integrations / Settings":
    render_integrations_settings()
