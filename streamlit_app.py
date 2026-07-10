import streamlit as st
from sqlmodel import SQLModel, select
# Clear SQLAlchemy metadata to prevent re-registration errors during Streamlit hot-reloads
SQLModel.metadata.clear()

import pandas as pd
import json
import asyncio
from pathlib import Path
from decimal import Decimal
from typing import Any

# SQLModel/DB imports
from app.db import get_engine, session_scope
from app.models import BenchmarkRun, RunCell, RunResult, DocumentSample, GroundTruth, Score, RunStatus
from app.providers.registry import list_models, families, get_capability
from app.tasks import TASKS, OPD_TASKS, merge_bills
from app.tasks.opd import build_text_inputs, calculated_total
from app.tasks.prompts.opd_healthpay import build_audit_prompt
from app.providers.gateway import ModelGateway, GatewayResult
from app.runner.persistence import register_document, persist_cell_result
from app.scoring.report import score_run, comparison, field_breakdown, render_field_breakdown
from app.scoring.field_metrics import score_against_gold

# Set page config
st.set_page_config(
    page_title="Colosseum LLM Benchmark Arena",
    page_icon="⚔️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Premium Aesthetics
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    /* Title styling */
    .title-text {
        font-weight: 700;
        background: linear-gradient(45deg, #6C5CE7, #a29bfe);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 20px;
    }
    
    /* Metric Card styling */
    .custom-card {
        background-color: #181829;
        border-radius: 12px;
        padding: 20px;
        border: 1px solid rgba(108, 92, 231, 0.2);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        margin-bottom: 15px;
    }
    
    /* Code blocks container */
    .stCodeBlock {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)

# Project directory helpers
REPO_ROOT = Path(__file__).resolve().parent
TEST_DOCS = REPO_ROOT / "test-docs"
GOLD_EXPORTS = REPO_ROOT / "data" / "gold_exports"

# Default Sample Policy Context
_SAMPLE_POLICY_CONTEXT = {
    "policy_rules": [
        "Health check-up, vaccines and health supplements are not covered.",
        "Correction of eyesight, spectacles, contact lenses and hearing aids are not covered.",
        "Maximum consultation fee: 1000.",
    ],
    "nme_items": ["Registration Charges", "Documentation Charges", "Service Charges"],
}

# ---------------------------------------------------------------------------
# Data/Utility Helpers
# ---------------------------------------------------------------------------
def get_test_pdfs() -> list[str]:
    if TEST_DOCS.is_dir():
        return sorted([str(p) for p in TEST_DOCS.glob("*.pdf")])
    return []

def get_csv_exports() -> list[str]:
    if GOLD_EXPORTS.is_dir():
        return sorted([str(p) for p in GOLD_EXPORTS.glob("*.csv")])
    return []

def _gold_for(session, document_id: int, task: str) -> dict | None:
    gt = session.exec(
        select(GroundTruth).where(
            GroundTruth.document_id == document_id, GroundTruth.task == task
        )
    ).first()
    return gt.gold if gt else None

def _categorised_from_upstream(upstream: dict) -> dict:
    groups = []
    for entry in upstream.get("bills", []) or []:
        bill_id = (entry.get("bill") or {}).get("bill_id")
        cat_items = [
            {"s.no.": it.get("s.no."), "category": it.get("category")}
            for it in entry.get("items", []) or []
            if it.get("category") and it.get("s.no.") is not None
        ]
        if bill_id and cat_items:
            groups.append({"bill_id": bill_id, "categorized_items": cat_items})
    return {"bill_item_categories": groups}

def draw_live_grid(grid_area, cell_statuses, selected_docs, selected_models, ordered_tasks):
    with grid_area.container():
        st.markdown("#### ⚡ Colosseum Arena Live Execution Grid")
        for doc_path in selected_docs:
            doc_name = Path(doc_path).name
            st.markdown(f"📂 **Document:** `{doc_name}`")
            
            # Create columns for each model
            cols = st.columns(len(selected_models))
            for m_idx, model_id in enumerate(selected_models):
                model_name = model_id.split("/")[-1]
                with cols[m_idx]:
                    st.markdown(f"🤖 **{model_name}**")
                    for task_name in ordered_tasks:
                        status = cell_statuses.get((doc_path, model_id, task_name), "pending")
                        if status == "pending":
                            badge = "⚪ `pending` — " + task_name
                        elif status == "running":
                            badge = "🟡 **`running`** — " + task_name
                        elif status == "succeeded":
                            badge = "🟢 `success` — " + task_name
                        elif status == "failed":
                            badge = "🔴 `failed` — " + task_name
                        elif status == "skipped":
                            badge = "🔵 `skipped` — " + task_name
                        else:
                            badge = "⚪ `pending` — " + task_name
                        st.markdown(badge)
            st.divider()

# Async cell runner task
async def run_custom_benchmark(
    run_name: str,
    selected_docs: list[str],
    selected_models: list[str],
    selected_tasks: list[str],
    gold_upstream: bool,
    pause_seconds: float,
    progress_bar,
    status_text,
    log_area,
    grid_area,
):
    engine = get_engine()
    gateway = ModelGateway()
    
    with session_scope(engine) as session:
        run = BenchmarkRun(name=run_name, task_pack_version="opd-v1", status="running")
        session.add(run)
        session.flush()
        run_id = run.id
        
    total_cells = len(selected_docs) * len(selected_models) * len(selected_tasks)
    completed_cells = 0
    logs = []
    
    def log(msg):
        logs.append(msg)
        log_area.code("\n".join(logs[-15:]))
        status_text.text(msg)
        
    # Standard task order for pipeline dependencies
    pipeline_order = [
        "segregation", "itemized_bills", "consolidated_bills",
        "items_categorisation", "policy_extraction",
        "nme_analysis", "benefit_plan", "audit"
    ]
    ordered_tasks = [t for t in pipeline_order if t in selected_tasks]
    for t in selected_tasks:
        if t not in ordered_tasks:
            ordered_tasks.append(t)
            
    cell_statuses = {}
    for doc_path in selected_docs:
        for model_id in selected_models:
            for task_name in ordered_tasks:
                cell_statuses[(doc_path, model_id, task_name)] = "pending"
                
    draw_live_grid(grid_area, cell_statuses, selected_docs, selected_models, ordered_tasks)
            
    for doc_path in selected_docs:
        log(f"📄 Processing document: {Path(doc_path).name}")
        
        with session_scope(engine) as session:
            doc = register_document(session, doc_path, claim_type="OPD")
            session.flush()
            doc_id = doc.id
            
        with session_scope(engine) as session:
            gold_upstream_bills = _gold_for(session, doc_id, "upstream_bills")
            gold_policy = _gold_for(session, doc_id, "policy_extraction")
            gold_audit = _gold_for(session, doc_id, "audit")
            gold_benefits = (
                (_gold_for(session, doc_id, "upstream_benefits") or {}).get("benefits")
            )
            gold_claimed = (gold_audit or {}).get("original_claimed_amount", 0) if gold_audit else 0
            policy_context = (
                {"policy_rules": gold_policy.get("policy_rules", []), "nme_items": gold_policy.get("nme_items", [])}
                if gold_policy else _SAMPLE_POLICY_CONTEXT
            )
            
        for model_id in selected_models:
            log(f"🤖 Running model {model_id} on {Path(doc_path).name}")
            model_outputs = {}
            
            for task_name in ordered_tasks:
                cell_name = f"{task_name} ➔ {model_id.split('/')[-1]} on {Path(doc_path).name}"
                log(f"⏳ Running: {cell_name}")
                
                cell_statuses[(doc_path, model_id, task_name)] = "running"
                draw_live_grid(grid_area, cell_statuses, selected_docs, selected_models, ordered_tasks)
                
                if pause_seconds > 0:
                    await asyncio.sleep(pause_seconds)
                    
                task = TASKS.get(task_name)
                if not task:
                    log(f"❌ Unknown task: {task_name}")
                    cell_statuses[(doc_path, model_id, task_name)] = "failed"
                    draw_live_grid(grid_area, cell_statuses, selected_docs, selected_models, ordered_tasks)
                    continue
                    
                system_prompt = task.system_prompt
                instruction = task.instruction
                documents = []
                
                try:
                    if task.is_text_task:
                        if gold_upstream:
                            current_merged = gold_upstream_bills
                            current_categories = _categorised_from_upstream(gold_upstream_bills) if gold_upstream_bills else None
                        else:
                            itemized = model_outputs.get("itemized_bills")
                            consolidated = model_outputs.get("consolidated_bills")
                            current_merged = merge_bills(itemized, consolidated)
                            current_categories = model_outputs.get("items_categorisation")
                            
                        if task_name in ("policy_extraction", "items_categorisation"):
                            text_inputs = build_text_inputs(
                                itemized=current_merged, 
                                consolidated=None,
                                policy_context=policy_context,
                            )
                            instruction = text_inputs[task_name]
                        elif task_name in ("nme_analysis", "benefit_plan"):
                            text_inputs = build_text_inputs(
                                itemized=current_merged,
                                consolidated=None,
                                categorised=current_categories,
                                policy_context=policy_context,
                                benefits=gold_benefits,
                                claimed_amount=gold_claimed,
                            )
                            instruction = text_inputs[task_name]
                    else:
                        if task_name == "audit":
                            if gold_upstream:
                                current_merged = gold_upstream_bills
                                current_claimed = gold_claimed
                            else:
                                itemized = model_outputs.get("itemized_bills")
                                consolidated = model_outputs.get("consolidated_bills")
                                current_merged = merge_bills(itemized, consolidated)
                                current_claimed = gold_claimed
                                
                            system_prompt = build_audit_prompt(
                                claimed_amount=current_claimed,
                                calculated_total=calculated_total(current_merged),
                                extracted_json=json.dumps(current_merged)
                            )
                        else:
                            documents = task.build_input(doc_path).documents
                            
                    result = await gateway.structured(
                        model_id=model_id,
                        system=system_prompt,
                        instruction=instruction,
                        schema=task.schema,
                        documents=documents,
                    )
                    
                    with session_scope(engine) as session:
                        cell = RunCell(
                            run_id=run_id,
                            task=task_name,
                            document_id=doc_id,
                            model_id=model_id,
                            config={},
                        )
                        session.add(cell)
                        session.flush()
                        
                        row = persist_cell_result(session, cell=cell, result=result)
                        session.flush()
                        
                        if result.parsed is not None:
                            model_outputs[task_name] = result.parsed.model_dump(mode="json")
                            
                    status_emoji = "✅" if result.valid else "⚠️"
                    if result.skipped:
                        status_emoji = "⏭️"
                        cell_statuses[(doc_path, model_id, task_name)] = "skipped"
                    elif result.valid:
                        cell_statuses[(doc_path, model_id, task_name)] = "succeeded"
                    else:
                        cell_statuses[(doc_path, model_id, task_name)] = "failed"
                    draw_live_grid(grid_area, cell_statuses, selected_docs, selected_models, ordered_tasks)
                    
                    log(f"{status_emoji} Finished: {cell_name} (valid={result.valid}, cost=${result.cost.total_usd:.6f}, lat={result.latency_ms}ms)")
                    
                except Exception as e:
                    log(f"❌ Error in cell {cell_name}: {e}")
                    cell_statuses[(doc_path, model_id, task_name)] = "failed"
                    draw_live_grid(grid_area, cell_statuses, selected_docs, selected_models, ordered_tasks)
                    
                completed_cells += 1
                progress_bar.progress(completed_cells / total_cells)
                
    with session_scope(engine) as session:
        run = session.get(BenchmarkRun, run_id)
        if run:
            run.status = "succeeded"
            session.add(run)
            
    with session_scope(engine) as session:
        score_run(session, run_id)
        
    log("🎉 Benchmark completed successfully!")
    return run_id

# CSV Ground Truth Converter/Importer
def import_csv_baselines(csv_path: str) -> dict:
    from scripts.convert_gold_exports import load_rows, convert_row
    from app.scoring.ground_truth_import import import_ground_truth
    
    out_dir = Path("data/gold")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    rows = load_rows([Path(csv_path)])
    written = 0
    for stem, row in rows.items():
        record = convert_row(row)
        if record is None:
            continue
        (out_dir / f"{stem}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        written += 1
        
    counts = import_ground_truth([str(out_dir)])
    counts["written_json_files"] = written
    return counts

# ---------------------------------------------------------------------------
# UI Construction
# ---------------------------------------------------------------------------
engine = get_engine()

st.markdown("<h1 class='title-text'>⚔️ Colosseum LLM Benchmark Arena</h1>", unsafe_allow_html=True)
st.write("A model-agnostic benchmarking and evaluation platform for structured health-claims processing.")

# Slot for global notifications (e.g. running background jobs)
runner_notification_slot = st.empty()

# Load models catalog
all_registered_models = list_models(enabled_only=False)
enabled_models = [m.model_id for m in all_registered_models if m.enabled]
disabled_models = [m.model_id for m in all_registered_models if not m.enabled]

# ---------------------------------------------------------------------------
# SIDEBAR: Runner Controls
# ---------------------------------------------------------------------------
st.sidebar.header("🕹️ Run Controller")

# Form/Inputs for run config
run_name = st.sidebar.text_input("Run Name", value="opd-streamlit-run")

# Document Selector
available_pdfs = get_test_pdfs()
selected_docs = st.sidebar.multiselect(
    "Select Claim Documents",
    options=available_pdfs,
    format_func=lambda x: Path(x).name,
    default=available_pdfs[:2] if available_pdfs else []
)

# Model Selector
selected_models = st.sidebar.multiselect(
    "Select LLM Models",
    options=enabled_models,
    default=[enabled_models[0]] if enabled_models else []
)
if disabled_models:
    with st.sidebar.expander("Disabled Catalog Models"):
        st.write("To enable, provide API credentials or modify catalog configuration:")
        for m in disabled_models:
            st.caption(f"- `{m}`")

# Tasks Selector
available_tasks = list(OPD_TASKS.keys())
selected_tasks = st.sidebar.multiselect(
    "Select Pipeline Tasks / Agents",
    options=available_tasks,
    default=available_tasks[:3]
)

# Advanced options
st.sidebar.write("⚙️ Config Options")
gold_upstream = st.sidebar.checkbox(
    "Gold Upstream Feed",
    value=True,
    help="If enabled, downstream tasks run on ground-truth upstream data instead of model-generated outputs. Essential for comparing individual task accuracies."
)
pause_seconds = st.sidebar.slider(
    "Vertex AI Rate-Limit Pause (s)",
    min_value=0.0,
    max_value=10.0,
    value=2.0,
    step=0.5,
    help="Sleep duration between API calls to stay under per-minute rate-limit quotas."
)

# Action button
run_btn = st.sidebar.button("🔥 Run Benchmark Arena", type="primary", use_container_width=True)

# Golden CSV Import Panel
st.sidebar.divider()
st.sidebar.header("📁 Ground Truth Importer")
available_csvs = get_csv_exports()
selected_csv = st.sidebar.selectbox(
    "Select Golden Export CSV",
    options=available_csvs,
    format_func=lambda x: Path(x).name
)
import_btn = st.sidebar.button("📥 Import Ground Truth", use_container_width=True)

# Database Connection Check
st.sidebar.divider()
try:
    with session_scope(engine) as session:
        doc_count = session.exec(select(DocumentSample)).all()
        gt_count = session.exec(select(GroundTruth)).all()
    st.sidebar.success(f"Database Connected. Docs: {len(doc_count)} | GT baselines: {len(gt_count)}")
except Exception as e:
    st.sidebar.error(f"Database connection failed: {e}")

# ---------------------------------------------------------------------------
# MAIN AREA TABS
# ---------------------------------------------------------------------------
tab_scoreboard, tab_inspector, tab_runner_logs, tab_datasets, tab_catalog = st.tabs([
    "🏆 Leaderboard & Scoreboard",
    "🔍 Output Inspector",
    "🔬 Run Live Benchmark",
    "📁 Ground Truth & Datasets",
    "🤖 Models Catalog"
])

# Import Action Trigger
if import_btn and selected_csv:
    with tab_datasets:
        st.info(f"Importing and converting ground truth from {Path(selected_csv).name}...")
        try:
            results = import_csv_baselines(selected_csv)
            st.success(f"Import complete! Details: {results}")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to import ground truth: {e}")

# ---------------------------------------------------------------------------
# TAB 1: LEADERBOARD & SCOREBOARD
# ---------------------------------------------------------------------------
with tab_scoreboard:
    st.write("### Benchmark Performance Leaderboard")
    
    with session_scope(engine) as session:
        runs = session.exec(select(BenchmarkRun).order_by(BenchmarkRun.id.desc())).all()
        run_options = {f"Run {r.id}: {r.name} ({r.created_at}) [Status: {r.status.value if hasattr(r.status, 'value') else r.status}]": r.id for r in runs}
    
    if not run_options:
        st.warning("No benchmark runs found in the database. Run a benchmark using the sidebar controller first!")
    else:
        # Run Selector dropdown
        selected_run_id = st.selectbox("Select Benchmark Run", options=list(run_options.keys()))
        run_id = run_options[selected_run_id]
        
        # Load run results and render
        with session_scope(engine) as session:
            by_task = comparison(session, [run_id])
            
        if not by_task:
            st.info("No scored cell outputs found for this run. If the run is in progress or failed, check the Live Benchmark tab.")
        else:
            # Aggregate stats across tasks
            flat_aggs = []
            for task, aggs in by_task.items():
                for agg in aggs:
                    flat_aggs.append(agg)
                    
            total_spent = sum(agg.cost for agg in flat_aggs)
            mean_acc = statistics_mean = pd.Series([agg.mean_accuracy for agg in flat_aggs if agg.mean_accuracy is not None]).mean()
            
            # Metric highlight cards
            col_m1, col_m2, col_m3 = st.columns(3)
            with col_m1:
                st.metric("Total Run Cost (USD)", f"${total_spent:.4f}")
            with col_m2:
                st.metric("Aggregate Mean Accuracy", f"{mean_acc:.2%}" if not pd.isna(mean_acc) else "N/A")
            with col_m3:
                st.metric("Total Tasks Processed", len(flat_aggs))
                
            # Scoreboard visualization charts
            st.write("### Visual Insights")
            chart_data = []
            for task, aggs in by_task.items():
                for agg in aggs:
                    chart_data.append({
                        "Model": agg.model_id.split("/")[-1],
                        "Task": task,
                        "Accuracy": agg.mean_accuracy if agg.mean_accuracy is not None else 0.0,
                        "Cost ($)": agg.cost,
                        "Latency (s)": agg.median_latency_ms / 1000 if agg.median_latency_ms else 0.0,
                        "Valid Cells": agg.valid,
                        "Total Cells": agg.cells
                    })
            
            if chart_data:
                chart_df = pd.DataFrame(chart_data)
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    st.write("**Accuracy vs. Cost by Model/Task**")
                    st.scatter_chart(
                        chart_df,
                        x="Cost ($)",
                        y="Accuracy",
                        color="Model",
                        size="Latency (s)"
                    )
                with col_c2:
                    st.write("**Median Latency (Seconds) by Model**")
                    st.bar_chart(
                        chart_df,
                        x="Model",
                        y="Latency (s)",
                        color="Model"
                    )
                    
            st.write("### Detailed Per-Task Performance")
            for task, aggs in by_task.items():
                with st.expander(f"Task: {task.upper()}", expanded=True):
                    task_rows = []
                    for a in aggs:
                        run_n = a.cells - a.skipped
                        acc = f"{a.mean_accuracy:.2%}" if a.mean_accuracy is not None else "n/a"
                        valid = f"{a.valid}/{run_n}" if run_n else f"skipped ({a.skipped})"
                        lat = f"{a.median_latency_ms / 1000:.2f}s" if a.median_latency_ms else "-"
                        task_rows.append({
                            "Model ID": a.model_id,
                            "Scored Docs": run_n,
                            "Valid Outputs": valid,
                            "Mean Accuracy": acc,
                            "Total Cost": f"${a.cost:.5f}",
                            "Median Latency": lat,
                            "Output Tokens": f"{a.output_tokens:,}",
                            "Thinking Tokens": f"{a.thinking_tokens:,}"
                        })
                    st.dataframe(pd.DataFrame(task_rows), use_container_width=True, hide_index=True)
                    
                    # Field match rates breakdown
                    st.write("🔍 *Per-field Match Rate Breakdown*")
                    with session_scope(engine) as session:
                        f_breakdown = field_breakdown(session, [run_id], task)
                    if f_breakdown:
                        f_rows = []
                        models_in_breakdown = sorted({m for per_model in f_breakdown.values() for m in per_model})
                        for path in sorted(f_breakdown):
                            r = {"Field Path": path}
                            for m in models_in_breakdown:
                                c = f_breakdown[path].get(m)
                                r[m.split("/")[-1]] = f"{c['matched']}/{c['total']} ({c['matched']/c['total']:.0%})" if c and c["total"] else "-"
                            f_rows.append(r)
                        st.dataframe(pd.DataFrame(f_rows), use_container_width=True, hide_index=True)
                    else:
                        st.caption("No field breakdown available (requires ground truth baselines).")

# ---------------------------------------------------------------------------
# TAB 2: OUTPUT INSPECTOR
# ---------------------------------------------------------------------------
with tab_inspector:
    st.write("### Side-by-Side Model Output Comparison")
    
    with session_scope(engine) as session:
        runs = session.exec(select(BenchmarkRun).order_by(BenchmarkRun.id.desc())).all()
        run_options = {f"Run {r.id}: {r.name}": r.id for r in runs}
        
    if not run_options:
        st.warning("No runs found in the database.")
    else:
        selected_insp_run = st.selectbox("Select Run", options=list(run_options.keys()), key="insp_run")
        insp_run_id = run_options[selected_insp_run]
        
        # Fetch docs and tasks in this run
        with session_scope(engine) as session:
            cells_db = session.exec(select(RunCell).where(RunCell.run_id == insp_run_id)).all()
            cells = [
                {
                    "id": c.id,
                    "document_id": c.document_id,
                    "task": c.task,
                    "model_id": c.model_id,
                    "status": c.status.value if hasattr(c.status, "value") else c.status
                }
                for c in cells_db
            ]
            
        if not cells:
            st.info("No cells found in this run.")
        else:
            doc_ids = list(set(c["document_id"] for c in cells))
            tasks_list = sorted(list(set(c["task"] for c in cells)))
            
            with session_scope(engine) as session:
                docs = session.exec(select(DocumentSample).where(DocumentSample.id.in_(doc_ids))).all()
                doc_map = {d.id: d.path for d in docs}
                
            col_sel1, col_sel2 = st.columns(2)
            with col_sel1:
                selected_doc_id = st.selectbox(
                    "Select Document", 
                    options=list(doc_map.keys()), 
                    format_func=lambda x: Path(doc_map[x]).name
                )
            with col_sel2:
                selected_task_name = st.selectbox("Select Task / Agent", options=tasks_list)
                
            # Filter cells to this doc and task
            match_cells = [c for c in cells if c["document_id"] == selected_doc_id and c["task"] == selected_task_name]
            
            if not match_cells:
                st.warning("No runs matched the selected Document + Task.")
            else:
                # Load Ground Truth
                with session_scope(engine) as session:
                    gold_val = _gold_for(session, selected_doc_id, selected_task_name)
                
                if gold_val:
                    with st.expander("👑 GROUND TRUTH (Baseline)", expanded=False):
                        st.json(gold_val)
                        
                st.divider()
                
                # Render model outputs side-by-side
                cols = st.columns(len(match_cells))
                for idx, cell in enumerate(match_cells):
                    with session_scope(engine) as session:
                        result_db = session.exec(select(RunResult).where(RunResult.cell_id == cell["id"])).first()
                        if result_db:
                            result = {
                                "latency_ms": result_db.latency_ms,
                                "input_tokens": result_db.input_tokens,
                                "output_tokens": result_db.output_tokens,
                                "total_cost_usd": float(result_db.total_cost_usd) if result_db.total_cost_usd is not None else None,
                                "parsed_output": result_db.parsed_output,
                                "prompt_system": result_db.prompt_system,
                                "prompt_instruction": result_db.prompt_instruction,
                                "raw_response": result_db.raw_response,
                                "result_id": result_db.id
                            }
                        else:
                            result = None
                            
                        score = None
                        if result:
                            score_db = session.exec(select(Score).where(Score.result_id == result["result_id"])).first()
                            if score_db:
                                score = {
                                    "composite": float(score_db.composite) if score_db.composite is not None else None,
                                    "field_metrics": score_db.field_metrics
                                }
                        
                    with cols[idx]:
                        st.markdown(f"#### 🤖 {cell['model_id'].split('/')[-1]}")
                        
                        # Status indicator
                        status_color = "success" if cell["status"] == "succeeded" else "warning" if cell["status"] == "skipped" else "danger"
                        st.markdown(f"<span class='badge badge-{status_color}'>{cell['status'].upper()}</span>", unsafe_allow_html=True)
                        
                        if result:
                            # Quick stats
                            col_st1, col_st2 = st.columns(2)
                            with col_st1:
                                st.metric("Latency", f"{result['latency_ms'] / 1000:.2f}s" if result['latency_ms'] else "-")
                                st.metric("Input Tokens", f"{result['input_tokens']:,}")
                            with col_st2:
                                st.metric("Cost (USD)", f"${result['total_cost_usd']:.5f}" if result['total_cost_usd'] else "-")
                                st.metric("Output Tokens", f"{result['output_tokens']:,}")
                                
                            if score and score["composite"] is not None:
                                st.metric("Task Accuracy", f"{score['composite']:.1%}")
                                
                            # Parsed output
                            st.write("**Parsed JSON Output:**")
                            st.json(result["parsed_output"] or {})
                            
                            # Mismatches list
                            if score and score["field_metrics"] and "mismatches" in score["field_metrics"]:
                                mismatches = score["field_metrics"]["mismatches"]
                                if mismatches:
                                    st.warning(f"⚠️ Mismatches ({len(mismatches)} fields):")
                                    for m in mismatches:
                                        st.caption(f"**`{m.get('path')}`**\n- Predicted: `{m.get('predicted')}`\n- Gold: `{m.get('gold')}`")
                                else:
                                    st.success("🎯 100% Match with Ground Truth!")
                                    
                            # Raw prompt inspector
                            with st.expander("Inspect Raw Prompts"):
                                st.text("System Prompt:")
                                st.code(result["prompt_system"] or "")
                                st.text("Instruction:")
                                st.code(result["prompt_instruction"] or "")
                                
                            with st.expander("Inspect Raw API Response"):
                                st.json(result["raw_response"] or {})
                        else:
                            st.info("No call log details found for this run cell.")

# ---------------------------------------------------------------------------
# TAB 3: RUN LIVE BENCHMARK
# ---------------------------------------------------------------------------
with tab_runner_logs:
    st.write("### Live Benchmark Execution Console")
    
    if run_btn:
        if not selected_docs:
            st.error("Please select at least one document.")
        elif not selected_models:
            st.error("Please select at least one model.")
        elif not selected_tasks:
            st.error("Please select at least one task.")
        else:
            runner_notification_slot.info("⚡ Colosseum Arena is active! Running benchmarks. Switch to **🔬 Run Live Benchmark** tab to watch live.")
            st.info("Starting Colosseum Arena runs...")
            
            # Setup interactive components
            pb = st.progress(0.0)
            st_text = st.empty()
            grid_area = st.empty()
            l_area = st.empty()
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                run_id = loop.run_until_complete(
                    run_custom_benchmark(
                        run_name=run_name,
                        selected_docs=selected_docs,
                        selected_models=selected_models,
                        selected_tasks=selected_tasks,
                        gold_upstream=gold_upstream,
                        pause_seconds=pause_seconds,
                        progress_bar=pb,
                        status_text=st_text,
                        log_area=l_area,
                        grid_area=grid_area,
                    )
                )
                runner_notification_slot.empty()
                st.success(f"🎉 Benchmark execution complete! Run ID: {run_id}")
                st.balloons()
            except Exception as e:
                runner_notification_slot.error(f"Benchmark failed: {e}")
                st.error(f"Benchmark failed: {e}")
            finally:
                loop.close()
    else:
        st.write("Configure details in the left sidebar, and click **Run Benchmark Arena** to stream execution logs here.")

# ---------------------------------------------------------------------------
# TAB 4: GROUND TRUTH & DATASETS
# ---------------------------------------------------------------------------
with tab_datasets:
    st.write("### Ground Truth Baseline Dataset Manager")
    
    with session_scope(engine) as session:
        samples_db = session.exec(select(DocumentSample)).all()
        samples = [
            {
                "id": s.id,
                "path": s.path,
                "claim_type": s.claim_type,
                "page_count": s.page_count,
                "sha256": s.sha256
            }
            for s in samples_db
        ]
        gts_db = session.exec(select(GroundTruth)).all()
        gts = [
            {
                "document_id": g.document_id,
                "task": g.task,
                "gold": g.gold
            }
            for g in gts_db
        ]
        
    st.write(f"Total Registered Documents: **{len(samples)}** | Total Ground Truth Baselines: **{len(gts)}**")
    
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.write("#### Registered Documents List")
        doc_rows = []
        for s in samples:
            doc_rows.append({
                "ID": s["id"],
                "Path": s["path"],
                "Claim Type": s["claim_type"],
                "Page Count": s["page_count"] or "Unknown",
                "Hash": s["sha256"][:10]
            })
        if doc_rows:
            st.dataframe(pd.DataFrame(doc_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No documents registered.")
            
    with col_g2:
        st.write("#### Ground Truth Baselines List")
        gt_rows = []
        for g in gts:
            gt_rows.append({
                "Document ID": g["document_id"],
                "Task": g["task"],
                "Gold JSON Size": len(json.dumps(g["gold"]))
            })
        if gt_rows:
            st.dataframe(pd.DataFrame(gt_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No ground truth baselines imported.")
            
    if gts:
        st.divider()
        st.write("#### Ground Truth Inspector")
        inspect_doc = st.selectbox(
            "Select Document to inspect gold JSON", 
            options=list(set(g["document_id"] for g in gts)),
            format_func=lambda x: next((Path(s["path"]).name for s in samples if s["id"] == x), f"Doc {x}")
        )
        with session_scope(engine) as session:
            doc_gts_db = session.exec(select(GroundTruth).where(GroundTruth.document_id == inspect_doc)).all()
            doc_gts = [
                {
                    "task": g.task,
                    "gold": g.gold
                }
                for g in doc_gts_db
            ]
            
        for g in doc_gts:
            with st.expander(f"Task: {g['task']}"):
                st.json(g["gold"])

# ---------------------------------------------------------------------------
# TAB 5: MODELS CATALOG
# ---------------------------------------------------------------------------
with tab_catalog:
    st.write("### Model Capability & Pricing Registry")
    
    st.write("Below are the models registered in Colosseum (`providers/catalog/*.yaml`). Enabling a model exposes it to the gateway.")
    
    from app.providers.pricing import load_rate_card, resolve_pricing_ref
    card = load_rate_card()
    
    model_rows = []
    for cap in all_registered_models:
        resolved = resolve_pricing_ref(cap.pricing_ref, card)
        rates = card.get("models", {}).get(resolved, {}) if resolved else {}
        input_rate = float(rates.get("input_usd_per_million", 0.0))
        output_rate = float(rates.get("output_usd_per_million", 0.0))
        
        model_rows.append({
            "Model ID": cap.model_id,
            "Provider": cap.provider.value,
            "Enabled": "✅ Yes" if cap.enabled else "❌ Gated Off",
            "Modalities": ", ".join(m.value for m in cap.modalities),
            "Structured Method": cap.structured_method.value if cap.structured_method else "-",
            "Input Cost ($/M)": input_rate,
            "Output Cost ($/M)": output_rate,
            "Reason Gated / Notes": cap.notes or ""
        })
        
    df_cat = pd.DataFrame(model_rows)
    st.dataframe(df_cat, use_container_width=True, hide_index=True)
