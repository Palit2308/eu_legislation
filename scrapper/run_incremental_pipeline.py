#!/usr/bin/env python3
"""
Incremental pipeline runner for your scraper project.

What it does
------------
- runs scripts in a fixed order
- skips tasks whose inputs / code / dependencies did not change
- reruns downstream tasks when an upstream task ran
- stores build state in `.pipeline_state.json`

Why this is useful
------------------
A normal shell script runs everything every time.
This runner behaves more like a lightweight build system.

How to use
----------
From the project root:

    python run_incremental_pipeline.py

Useful options:

    python run_incremental_pipeline.py --dry-run
    python run_incremental_pipeline.py --force
    python run_incremental_pipeline.py --force-task com_vote_info
    python run_incremental_pipeline.py --list

Notes
-----
1. Edit the TASKS section below to match your exact inputs / outputs.
2. You should include BOTH:
   - data inputs
   - code files that can affect the output
   in each task's `file_deps`.
3. If a function file changes, every task that depends on it will rerun.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set


# =============================================================================
# config
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
BLD = PROJECT_ROOT / "bld"
STATE_FILE = PROJECT_ROOT / ".pipeline_state.json"


@dataclass
class Task:
    name: str
    cmd: List[str]
    file_deps: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    task_deps: List[str] = field(default_factory=list)
    description: str = ""


# -----------------------------------------------------------------------------
# EDIT THIS SECTION TO MATCH YOUR PROJECT
# -----------------------------------------------------------------------------
TASKS: Dict[str, Task] = {
    # Example assumptions:
    # - raw input data lives in bld/
    # - scripts live in scripts/
    # - reusable functions live in functions/
    #
    # Adjust file names if yours differ.

    "committee_dictionary": Task(
        name="committee_dictionary",
        cmd=[sys.executable, "scripts/create_committee_dictionary.py"],
        file_deps=[
            "scripts/create_committee_dictionary.py",
            "functions/create_committee_dictionary.py",
        ],
        outputs=[
            "bld/committee_dictionary.csv",
            "bld/committee_dictionary.json",
        ],
        description="Build committee dictionary",
    ),

    "scrape_cod_procedures": Task(
        name="scrape_cod_procedures",
        cmd=[sys.executable, "scripts/scrape_cod_procedures.py"],
        file_deps=[
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
        ],
        outputs=[
            "bld/oeil_cod_procedures.csv",
        ],
        description="Scrape COD procedures",
    ),

    "meta_table": Task(
        name="meta_table",
        cmd=[sys.executable, "scripts/create_meta_table.py"],
        file_deps=[
            "scripts/create_meta_table.py",
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
            "functions/create_meta_table.py",
            "bld/oeil_cod_procedures.csv",
        ],
        outputs=[
            "bld/meta_table.csv",
            "bld/meta_table.json",
        ],
        task_deps=["scrape_cod_procedures"],
        description="Build meta table",
    ),

    "wide_meta": Task(
        name="wide_meta",
        cmd=[sys.executable, "scripts/create_wide_meta.py"],
        file_deps=[
            "scripts/create_wide_meta.py",
            "scripts/create_meta_table.py",
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
            "functions/create_meta_table.py",
            "bld/oeil_cod_procedures.csv",
            "bld/meta_table.csv",
            "bld/meta_table.json",
        ],
        outputs=[
            "bld/wide_meta.csv",
        ],
        task_deps=["scrape_cod_procedures", "meta_table"],
        description="Build wide meta table",
    ),

    "timeline_table": Task(
        name="timeline_table",
        cmd=[sys.executable, "scripts/create_timeline_table.py"],
        file_deps=[
            "scripts/create_timeline_table.py",
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
            "functions/create_timeline_table.py",
            "bld/oeil_cod_procedures.csv",
        ],
        outputs=[
            "bld/timeline_table.csv",
            "bld/timeline_table.json",
        ],
        task_deps=["scrape_cod_procedures"],
        description="Build timeline table",
    ),

    "transparency_table": Task(
        name="transparency_table",
        cmd=[sys.executable, "scripts/create_transparency_table.py"],
        file_deps=[
            "scripts/create_transparency_table.py",
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
            "functions/create_transparency_table.py",
            "bld/oeil_cod_procedures.csv",
        ],
        outputs=[
            "bld/transparency_table.csv",
            "bld/transparency_table.json",
        ],
        task_deps=["scrape_cod_procedures"],
        description="Build transparency table",
    ),

    "com_vote_info": Task(
        name="com_vote_info",
        cmd=[sys.executable, "scripts/create_com_vote_info.py"],
        file_deps=[
            "scripts/create_com_vote_info.py",
            "scripts/create_timeline_table.py",
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
            "functions/create_timeline_table.py",
            "functions/create_com_vote_info.py",
            "bld/oeil_cod_procedures.csv",
            "bld/timeline_table.csv",
            "bld/timeline_table.json",
        ],
        outputs=[
            "bld/committee_vote_info.csv",
            "bld/committee_vote_info.json",
        ],
        task_deps=["scrape_cod_procedures", "timeline_table"],
        description="Build committee vote info",
    ),

    "com_vote_procedure": Task(
        name="com_vote_procedure",
        cmd=[sys.executable, "scripts/create_com_vote_procedure.py"],
        file_deps=[
            "scripts/create_com_vote_procedure.py",
            "scripts/create_com_vote_info.py",
            "scripts/create_timeline_table.py",
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
            "functions/create_com_vote_procedure.py",
            "functions/create_timeline_table.py",
            "functions/create_com_vote_info.py",
            "bld/oeil_cod_procedures.csv",
            "bld/timeline_table.csv",
            "bld/timeline_table.json",
            "bld/committee_vote_info.csv",
            "bld/committee_vote_info.json",
        ],
        outputs=[
            "bld/committee_vote_procedure_table.csv",
            "bld/committee_vote_procedure_table.json",
        ],
        task_deps=["scrape_cod_procedures", "timeline_table", "com_vote_info"],
        description="Parse committee procedure tables",
    ),

    "com_roll_call": Task(
        name="com_roll_call",
        cmd=[sys.executable, "scripts/create_com_roll_call.py"],
        file_deps=[
            "scripts/create_com_roll_call.py",
            "scripts/create_com_vote_info.py",
            "scripts/create_timeline_table.py",
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
            "functions/create_com_roll_call.py",
            "functions/create_timeline_table.py",
            "functions/create_com_vote_info.py",
            "bld/oeil_cod_procedures.csv",
            "bld/timeline_table.csv",
            "bld/timeline_table.json",
            "bld/committee_vote_info.csv",
            "bld/committee_vote_info.json",
        ],
        outputs=[
            "bld/committee_roll_call_table.csv",
            "bld/committee_roll_call_table.json",
        ],
        task_deps=["scrape_cod_procedures", "timeline_table", "com_vote_info"],
        description="Expand committee roll call tables",
    ),

    "com_other_format_text": Task(
        name="com_other_format_text",
        cmd=[sys.executable, "scripts/create_com_other_format_text.py"],
        file_deps=[
            "scripts/create_com_other_format_text.py",
            "scripts/create_com_vote_info.py",
            "scripts/create_timeline_table.py",
            "scripts/scrape_cod_procedures.py",
            "functions/scrape_cod_procedures.py",
            "functions/create_other_format_text.py",
            "functions/create_timeline_table.py",
            "functions/create_com_vote_info.py",
            "bld/oeil_cod_procedures.csv",
            "bld/timeline_table.csv",
            "bld/timeline_table.json",
            "bld/committee_vote_info.csv",
            "bld/committee_vote_info.json",
        ],
        outputs=[
            "bld/committee_other_format_text.csv",
        ],
        task_deps=["scrape_cod_procedures", "timeline_table", "com_vote_info"],
        description="Extract text from fallback PDFs / other formats",
    ),

    # "other_format_com_vote_procedure": Task(
    #     name="other_format_com_vote_procedure",
    #     cmd=[sys.executable, "scripts/create_other_format_com_vote_procedure.py"],
    #     file_deps=[
    #         "scripts/create_other_format_com_vote_procedure.py",
    #         "functions/create_other_format_com_procedure_table.py",
    #         "bld/beta_test_procedures_committee_other_format_text.csv",
    #     ],
    #     outputs=[
    #         "bld/create_other_formats_com_vote_procedure.csv",
    #         "bld/create_other_formats_com_vote_procedure.json",
    #     ],
    #     task_deps=["com_other_format_text"],
    #     description="Parse procedural sections from other-format texts",
    # ),
}
# -----------------------------------------------------------------------------
# end editable section
# -----------------------------------------------------------------------------


# =============================================================================
# helpers
# =============================================================================

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_signature(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def resolve(rel_path: str) -> Path:
    return (PROJECT_ROOT / rel_path).resolve()


def load_state() -> Dict[str, object]:
    if not STATE_FILE.exists():
        return {"tasks": {}}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: Dict[str, object]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def get_task(name: str) -> Task:
    if name not in TASKS:
        raise KeyError(f"Unknown task: {name}")
    return TASKS[name]


def topo_sort(tasks: Dict[str, Task]) -> List[str]:
    order: List[str] = []
    temp: Set[str] = set()
    perm: Set[str] = set()

    def visit(name: str) -> None:
        if name in perm:
            return
        if name in temp:
            raise ValueError(f"Cyclic dependency detected at task: {name}")
        temp.add(name)
        for dep in tasks[name].task_deps:
            if dep not in tasks:
                raise KeyError(f"Task '{name}' depends on unknown task '{dep}'")
            visit(dep)
        temp.remove(name)
        perm.add(name)
        order.append(name)

    for name in tasks:
        visit(name)

    return order


def collect_signatures(paths: List[str]) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for p in paths:
        out[p] = file_signature(resolve(p))
    return out


def outputs_missing(task: Task) -> bool:
    return any(not resolve(p).exists() for p in task.outputs)


def task_needs_run(
    task: Task,
    state: Dict[str, object],
    upstream_ran: bool = False,
    force: bool = False,
) -> tuple[bool, str]:
    if force:
        return True, "forced"

    if upstream_ran:
        return True, "upstream task reran"

    if outputs_missing(task):
        return True, "missing output"

    prev_task_state = state.get("tasks", {}).get(task.name, {})

    current_inputs = collect_signatures(task.file_deps)
    previous_inputs = prev_task_state.get("inputs", {})
    if current_inputs != previous_inputs:
        return True, "input/code dependency changed"

    current_outputs = collect_signatures(task.outputs)
    previous_outputs = prev_task_state.get("outputs", {})
    if current_outputs != previous_outputs:
        return True, "output changed or not yet recorded"

    return False, "up to date"


def update_task_state(state: Dict[str, object], task: Task) -> None:
    state.setdefault("tasks", {})
    state["tasks"][task.name] = {
        "inputs": collect_signatures(task.file_deps),
        "outputs": collect_signatures(task.outputs),
        "cmd": task.cmd,
    }


def run_task(task: Task) -> None:
    print(f"\n[RUN ] {task.name}")
    print("      ", " ".join(task.cmd))
    subprocess.run(task.cmd, cwd=PROJECT_ROOT, check=True)


def print_task_table(order: List[str]) -> None:
    print("Pipeline order:")
    for i, name in enumerate(order, start=1):
        t = TASKS[name]
        print(f"{i:>2}. {name:<32} {t.description}")


# =============================================================================
# main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental pipeline runner")
    parser.add_argument("--dry-run", action="store_true", help="show what would run")
    parser.add_argument("--force", action="store_true", help="force all tasks to run")
    parser.add_argument("--force-task", action="append", default=[], help="force one task by name; can be given multiple times")
    parser.add_argument("--list", action="store_true", help="list tasks in order and exit")
    args = parser.parse_args()

    BLD.mkdir(parents=True, exist_ok=True)
    
    order = topo_sort(TASKS)

    if args.list:
        print_task_table(order)
        return 0

    state = load_state()
    forced_tasks = set(args.force_task)

    ran: Set[str] = set()
    skipped: Set[str] = set()

    print_task_table(order)

    for name in order:
        task = get_task(name)
        upstream_ran = any(dep in ran for dep in task.task_deps)
        force_this = args.force or (name in forced_tasks)

        needs_run, reason = task_needs_run(
            task=task,
            state=state,
            upstream_ran=upstream_ran,
            force=force_this,
        )

        if needs_run:
            print(f"\n[PLAN] {name}: {reason}")
            if not args.dry_run:
                run_task(task)
                update_task_state(state, task)
                save_state(state)
            ran.add(name)
        else:
            print(f"\n[SKIP] {name}: {reason}")
            skipped.add(name)

    print("\nSummary")
    print(f"  ran    : {len(ran)}")
    print(f"  skipped: {len(skipped)}")
    if ran:
        print("  ran tasks:", ", ".join(order_name for order_name in order if order_name in ran))
    if skipped:
        print("  skipped tasks:", ", ".join(order_name for order_name in order if order_name in skipped))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
