"""Versioned prompt baselines and prompt previewing."""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, func, select

from app.api.deps import SessionDep
from app.api.schemas import (
    PromptPreviewIn,
    PromptPreviewOut,
    PromptVersionIn,
    PromptVersionOut,
)
from app.models import DocumentSample, GroundTruth, PromptVersion
from app.prompts.store import resolve_prompt
from app.runner.spec import task_pack_for

router = APIRouter(prefix="/prompts", tags=["prompts"])
_VARIABLE = re.compile(
    r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})|\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}"
)


def _pack(pack: str):
    try:
        return task_pack_for(pack.upper(), None)
    except (KeyError, NotImplementedError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"Unknown task pack {pack!r}") from exc


def _version_out(row: PromptVersion) -> PromptVersionOut:
    return PromptVersionOut(
        id=row.id,
        pack=row.pack,
        task_name=row.task_name,
        version=row.version,
        system_prompt=row.system_prompt,
        instruction_template=row.instruction_template,
        source_repo=row.source_repo,
        source_branch=row.source_branch,
        source_path=row.source_path,
        active=row.active,
        created_at=row.created_at,
        active_version=row.version if row.active else None,
        source=f"db:v{row.version}",
    )


@router.get("", response_model=list[PromptVersionOut])
def active_prompts(
    session: SessionDep,
    pack: str = Query(...),
) -> list[PromptVersionOut]:
    task_pack = _pack(pack)
    active = {
        row.task_name: row
        for row in session.exec(
            select(PromptVersion).where(
                PromptVersion.pack == pack.upper(),
                PromptVersion.active.is_(True),  # type: ignore[union-attr]
            )
        ).all()
    }
    output: list[PromptVersionOut] = []
    for task_name in task_pack.order:
        task = task_pack.tasks[task_name]
        row = active.get(task_name)
        if row:
            item = _version_out(row)
            item.differs_from_code = (
                row.system_prompt != task.system_prompt
                or row.instruction_template != task.instruction
            )
            output.append(item)
        else:
            output.append(
                PromptVersionOut(
                    pack=pack.upper(),
                    task_name=task_name,
                    system_prompt=task.system_prompt,
                    instruction_template=task.instruction,
                    active=False,
                    source="code",
                )
            )
    return output


@router.get("/{pack}/{task}/versions", response_model=list[PromptVersionOut])
def prompt_versions(
    pack: str,
    task: str,
    session: SessionDep,
) -> list[PromptVersionOut]:
    task_pack = _pack(pack)
    if task not in task_pack.tasks:
        raise HTTPException(status_code=404, detail="Task not found in pack")
    rows = session.exec(
        select(PromptVersion)
        .where(PromptVersion.pack == pack.upper(), PromptVersion.task_name == task)
        .order_by(PromptVersion.version.desc())  # type: ignore[union-attr]
    ).all()
    return [_version_out(row) for row in rows]


@router.post("/{pack}/{task}/versions", response_model=PromptVersionOut, status_code=201)
def create_prompt_version(
    pack: str,
    task: str,
    body: PromptVersionIn,
    session: SessionDep,
) -> PromptVersionOut:
    task_pack = _pack(pack)
    if task not in task_pack.tasks:
        raise HTTPException(status_code=404, detail="Task not found in pack")
    latest = session.exec(
        select(func.max(PromptVersion.version)).where(
            PromptVersion.pack == pack.upper(), PromptVersion.task_name == task
        )
    ).one()
    if body.activate:
        for row in session.exec(
            select(PromptVersion).where(
                PromptVersion.pack == pack.upper(),
                PromptVersion.task_name == task,
                PromptVersion.active.is_(True),  # type: ignore[union-attr]
            )
        ).all():
            row.active = False
            session.add(row)
        session.flush()
    row = PromptVersion(
        pack=pack.upper(),
        task_name=task,
        version=(latest or 0) + 1,
        system_prompt=body.system_prompt,
        instruction_template=body.instruction_template,
        source_repo=body.source_repo,
        source_branch=body.source_branch,
        source_path=body.source_path,
        active=body.activate,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _version_out(row)


@router.post("/{pack}/{task}/versions/{version}/activate", response_model=PromptVersionOut)
def activate_prompt_version(
    pack: str,
    task: str,
    version: int,
    session: SessionDep,
) -> PromptVersionOut:
    task_pack = _pack(pack)
    if task not in task_pack.tasks:
        raise HTTPException(status_code=404, detail="Task not found in pack")
    target = session.exec(
        select(PromptVersion).where(
            PromptVersion.pack == pack.upper(),
            PromptVersion.task_name == task,
            (PromptVersion.version == version) | (PromptVersion.id == version),
        )
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Prompt version not found")

    for row in session.exec(
        select(PromptVersion).where(
            PromptVersion.pack == pack.upper(),
            PromptVersion.task_name == task,
            PromptVersion.active.is_(True),  # type: ignore[union-attr]
        )
    ).all():
        row.active = False
        session.add(row)
    session.flush()

    target.active = True
    session.add(target)
    session.commit()
    session.refresh(target)
    return _version_out(target)


@router.delete("/{pack}/{task}/versions/{version}")
def delete_prompt_version(
    pack: str,
    task: str,
    version: int,
    session: SessionDep,
) -> dict[str, Any]:
    task_pack = _pack(pack)
    if task not in task_pack.tasks:
        raise HTTPException(status_code=404, detail="Task not found in pack")
    target = session.exec(
        select(PromptVersion).where(
            PromptVersion.pack == pack.upper(),
            PromptVersion.task_name == task,
            (PromptVersion.version == version) | (PromptVersion.id == version),
        )
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Prompt version not found")

    was_active = target.active
    session.delete(target)
    session.flush()

    if was_active:
        latest = session.exec(
            select(PromptVersion)
            .where(PromptVersion.pack == pack.upper(), PromptVersion.task_name == task)
            .order_by(PromptVersion.version.desc())  # type: ignore[union-attr]
        ).first()
        if latest:
            latest.active = True
            session.add(latest)

    session.commit()
    return {"status": "deleted", "version": version}


def _preview_context(session: Session, document_id: int | None) -> dict[str, Any]:
    if document_id is None:
        return {}
    if session.get(DocumentSample, document_id) is None:
        raise HTTPException(status_code=404, detail="Sample document not found")
    tasks = {
        row.task: row.gold
        for row in session.exec(
            select(GroundTruth).where(GroundTruth.document_id == document_id)
        ).all()
    }
    context: dict[str, Any] = dict(tasks)
    context.update(
        {
            "bills_json": tasks.get("upstream_bills") or tasks.get("merge_bills") or {},
            "categories_json": tasks.get("items_categorisation") or {},
            "nme_json": tasks.get("nme_analysis") or {},
            "policy_json": tasks.get("policy_extraction") or {},
            "benefits_json": tasks.get("upstream_benefits") or tasks.get("benefits") or {},
        }
    )
    return {
        key: json.dumps(value, indent=2, ensure_ascii=False)
        if not isinstance(value, str)
        else value
        for key, value in context.items()
    }


@router.post("/preview", response_model=PromptPreviewOut)
def preview_prompt(
    body: PromptPreviewIn,
    session: SessionDep,
) -> PromptPreviewOut:
    task_pack = _pack(body.pack)
    task = task_pack.tasks.get(body.task)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found in pack")
    prompt = resolve_prompt(session, body.pack.upper(), task)
    system = body.system_prompt if body.system_prompt is not None else prompt.system_prompt
    template = (
        body.instruction_template
        if body.instruction_template is not None
        else prompt.instruction_template
    )
    context = _preview_context(session, body.sample_document_id)
    unresolved: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        if name not in context:
            unresolved.add(name)
            return match.group(0)
        return str(context[name])

    rendered = _VARIABLE.sub(replace, template)
    return PromptPreviewOut(
        pack=body.pack.upper(),
        task=body.task,
        system_prompt=system,
        instruction_template=template,
        rendered_instruction=rendered,
        unresolved_variables=sorted(unresolved),
    )
