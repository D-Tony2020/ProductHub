"""存量导入（admin）：上传 → dry-run 报告 → 确认入库。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.security import require_admin
from app.models import AppUser, ImportBatch
from app.services.import_service import RowError, file_sha256, parse_workbook, process_row
from app.services.template_service import get_or_404

router = APIRouter(prefix="/imports", tags=["imports"])


class BatchOut(BaseModel):
    id: int
    filename: str
    file_hash: str
    status: str
    total_rows: int
    ok_rows: int
    error_rows: int
    report_json: dict | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[BatchOut])
def list_batches(db: Session = Depends(get_db), _: AppUser = Depends(require_admin)):
    return db.execute(
        select(ImportBatch).order_by(ImportBatch.id.desc()).limit(50)
    ).scalars().all()


@router.post("/dry-run", response_model=BatchOut)
def dry_run(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: AppUser = Depends(require_admin),
):
    content = file.file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件超过 10MB")
    fhash = file_sha256(content)
    committed = db.execute(
        select(ImportBatch).where(
            ImportBatch.file_hash == fhash, ImportBatch.status == "committed"
        )
    ).scalar_one_or_none()
    if committed is not None:
        raise HTTPException(409, f"同一文件已在批次 #{committed.id} 提交过（幂等拦截）")

    try:
        headers, rows = parse_workbook(content)
    except RowError as e:
        raise HTTPException(422, str(e))
    except Exception:
        raise HTTPException(422, "无法解析 Excel 文件，请使用模板格式（.xlsx）")

    report_rows = []
    ok = err = 0
    for row in rows:
        try:
            item = process_row(db, row["cells"], commit_mode=False, actor_id=admin.id)
            item["row_no"] = row["row_no"]
            ok += 1
        except RowError as e:
            item = {"row_no": row["row_no"], "status": "error", "message": str(e)}
            err += 1
        report_rows.append(item)
    db.rollback()  # dry-run 不留任何副作用

    # 行单元格序列化存档（confirm 阶段重新校验后入库）
    raw_rows = [
        {"row_no": r["row_no"],
         "cells": {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                   for k, v in r["cells"].items() if v is not None}}
        for r in rows
    ]
    batch = ImportBatch(
        filename=file.filename or "import.xlsx",
        file_hash=fhash,
        status="dry_run",
        total_rows=len(rows),
        ok_rows=ok,
        error_rows=err,
        report_json={"headers": headers, "report": report_rows, "raw_rows": raw_rows},
        created_by=admin.id,
    )
    db.add(batch)
    db.commit()
    return batch


@router.post("/{batch_id}/confirm", response_model=BatchOut)
def confirm(
    batch_id: int, db: Session = Depends(get_db), admin: AppUser = Depends(require_admin)
):
    batch = get_or_404(db, ImportBatch, batch_id)
    if batch.status != "dry_run":
        raise HTTPException(409, f"批次状态为 {batch.status}，不可确认")
    raw_rows = (batch.report_json or {}).get("raw_rows", [])
    if not raw_rows:
        raise HTTPException(422, "批次没有可入库的行")

    report = []
    ok = err = 0
    # 单事务：全量重校验后入库；任何意外异常整体回滚
    for row in raw_rows:
        try:
            item = process_row(
                db, row["cells"], commit_mode=True, actor_id=admin.id, batch_id=batch.id
            )
            item["row_no"] = row["row_no"]
            ok += 1
        except RowError as e:
            item = {"row_no": row["row_no"], "status": "error", "message": str(e)}
            err += 1
        report.append(item)

    batch.status = "committed"
    batch.ok_rows = ok
    batch.error_rows = err
    batch.report_json = {**(batch.report_json or {}), "commit_report": report}
    write_audit(db, actor_id=admin.id, action="import_commit", entity_type="import_batch",
                entity_id=batch.id, after={"ok": ok, "err": err})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "同一文件已被并发提交（幂等拦截）")
    return batch
