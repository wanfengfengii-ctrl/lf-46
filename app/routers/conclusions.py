from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from ..database import get_db
from ..validators import check_abnormal_data
from .versions import auto_create_version

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/stages/{stage_id}/conclusions/create")
def create_conclusion(request: Request, stage_id: int, content: str = Form(...), db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM stages WHERE id = ?", (stage_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="戏台不存在")

    if not content.strip():
        raise HTTPException(status_code=400, detail="结论内容不能为空")

    has_abnormal = check_abnormal_data(stage_id, db)

    cursor.execute(
        "INSERT INTO conclusions (stage_id, content, has_abnormal_data, is_confirmed) VALUES (?, ?, ?, ?)",
        (stage_id, content.strip(), int(has_abnormal), 0),
    )
    db.commit()
    auto_create_version(stage_id, db, created_by="系统",
                        modification_description="新增分析结论")
    return RedirectResponse(url=f"/stages/{stage_id}", status_code=303)


@router.post("/stages/{stage_id}/conclusions/{conclusion_id}/confirm")
def confirm_conclusion(stage_id: int, conclusion_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM conclusions WHERE id = ? AND stage_id = ?", (conclusion_id, stage_id))
    conclusion = cursor.fetchone()
    if not conclusion:
        raise HTTPException(status_code=404, detail="结论不存在")

    if conclusion["has_abnormal_data"]:
        raise HTTPException(status_code=400, detail="存在异常数据，不能直接确认实验结论。请先处理异常数据或修改结论。")

    cursor.execute("UPDATE conclusions SET is_confirmed = 1 WHERE id = ?", (conclusion_id,))
    db.commit()
    auto_create_version(stage_id, db, created_by="系统",
                        modification_description="确认分析结论")
    return RedirectResponse(url=f"/stages/{stage_id}", status_code=303)


@router.post("/stages/{stage_id}/conclusions/{conclusion_id}/delete")
def delete_conclusion(stage_id: int, conclusion_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM conclusions WHERE id = ? AND stage_id = ?", (conclusion_id, stage_id))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="结论不存在")
    cursor.execute("DELETE FROM conclusions WHERE id = ?", (conclusion_id,))
    db.commit()
    auto_create_version(stage_id, db, created_by="系统",
                        modification_description="删除分析结论")
    return RedirectResponse(url=f"/stages/{stage_id}", status_code=303)
