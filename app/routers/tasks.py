import os
import shutil
from datetime import datetime, date
from fastapi import APIRouter, Depends, Request, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from ..database import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

EQUIPMENT_TYPES = [
    "声级计",
    "脉冲声源",
    "录音设备",
    "麦克风",
    "信号发生器",
    "分析仪器",
    "其他"
]

TASK_STATUSES = [
    "planned",
    "in_progress",
    "completed",
    "cancelled"
]

CALIBRATION_RESULTS = [
    "合格",
    "不合格",
    "待确认"
]


def get_calibration_warning(db):
    today = date.today()
    cursor = db.cursor()
    cursor.execute("""
        SELECT e.*, 
               julianday(e.next_calibration_date) - julianday(?) as days_remaining
        FROM equipment e
        WHERE e.next_calibration_date IS NOT NULL 
          AND e.status != 'maintenance'
          AND (julianday(e.next_calibration_date) - julianday(?)) <= 30
        ORDER BY days_remaining ASC
    """, (today, today))
    return [dict(row) for row in cursor.fetchall()]


@router.get("/tasks", response_class=HTMLResponse)
def task_list(request: Request, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        SELECT mt.*, s.name as stage_name, s.location as stage_location,
               (SELECT COUNT(*) FROM task_equipment te WHERE te.task_id = mt.id) as equipment_count,
               (SELECT COUNT(*) FROM measurement_sessions ms WHERE ms.task_id = mt.id) as session_count,
               (SELECT COUNT(*) FROM task_execution_records ter WHERE ter.task_id = mt.id) as record_count
        FROM measurement_tasks mt
        JOIN stages s ON mt.stage_id = s.id
        ORDER BY mt.created_at DESC
    """)
    tasks = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM stages ORDER BY name")
    stages = [dict(row) for row in cursor.fetchall()]

    warnings = get_calibration_warning(db)

    return templates.TemplateResponse("task_list.html", {
        "request": request,
        "tasks": tasks,
        "stages": stages,
        "equipment_types": EQUIPMENT_TYPES,
        "task_statuses": TASK_STATUSES,
        "warnings": warnings,
        "today": date.today().isoformat()
    })


@router.post("/tasks/create")
def create_task(
    request: Request,
    stage_id: int = Form(...),
    task_name: str = Form(...),
    responsible_person: str = Form(""),
    measurement_date: str = Form(""),
    sampling_start_time: str = Form(""),
    sampling_end_time: str = Form(""),
    status: str = Form("planned"),
    site_notes: str = Form(""),
    db=Depends(get_db)
):
    if not task_name.strip():
        raise HTTPException(status_code=400, detail="任务名称不能为空")
    if status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="无效的任务状态")

    cursor = db.cursor()
    cursor.execute("SELECT id FROM stages WHERE id = ?", (stage_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="戏台不存在")

    cursor.execute("""
        INSERT INTO measurement_tasks 
        (stage_id, task_name, responsible_person, measurement_date, 
         sampling_start_time, sampling_end_time, status, site_notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        stage_id, task_name.strip(), responsible_person.strip(),
        measurement_date if measurement_date else None,
        sampling_start_time if sampling_start_time else None,
        sampling_end_time if sampling_end_time else None,
        status, site_notes.strip()
    ))
    db.commit()
    return RedirectResponse(url="/tasks", status_code=303)


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: int, db=Depends(get_db)):
    cursor = db.cursor()

    cursor.execute("""
        SELECT mt.*, s.name as stage_name, s.location as stage_location
        FROM measurement_tasks mt
        JOIN stages s ON mt.stage_id = s.id
        WHERE mt.id = ?
    """, (task_id,))
    task = cursor.fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    task = dict(task)

    cursor.execute("""
        SELECT e.* FROM equipment e
        JOIN task_equipment te ON e.id = te.equipment_id
        WHERE te.task_id = ?
        ORDER BY e.type, e.name
    """, (task_id,))
    task_equipment = [dict(row) for row in cursor.fetchall()]

    task_equipment_ids = [e["id"] for e in task_equipment]

    cursor.execute("""
        SELECT * FROM equipment 
        WHERE id NOT IN ({}) 
        ORDER BY type, name
    """.format(','.join(['?'] * len(task_equipment_ids)) if task_equipment_ids else '0'),
        task_equipment_ids if task_equipment_ids else [])
    available_equipment = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT * FROM task_execution_records
        WHERE task_id = ?
        ORDER BY created_at DESC
    """, (task_id,))
    execution_records = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT * FROM task_photos
        WHERE task_id = ?
        ORDER BY uploaded_at DESC
    """, (task_id,))
    photos = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT ms.*, 
               (SELECT COUNT(*) FROM acoustic_data WHERE session_id = ms.id) as data_count
        FROM measurement_sessions ms
        WHERE ms.task_id = ?
        ORDER BY ms.created_at DESC
    """, (task_id,))
    sessions = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT ms.*, s.name as stage_name
        FROM measurement_sessions ms
        JOIN stages s ON ms.stage_id = s.id
        WHERE ms.task_id IS NULL AND ms.stage_id = ?
        ORDER BY ms.created_at DESC
    """, (task["stage_id"],))
    available_sessions = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT id, name FROM stages WHERE id = ?", (task["stage_id"],))
    stage = dict(cursor.fetchone())

    return templates.TemplateResponse("task_detail.html", {
        "request": request,
        "task": task,
        "stage": stage,
        "task_equipment": task_equipment,
        "available_equipment": available_equipment,
        "execution_records": execution_records,
        "photos": photos,
        "sessions": sessions,
        "available_sessions": available_sessions,
        "calibration_results": CALIBRATION_RESULTS,
        "task_statuses": TASK_STATUSES,
        "today": date.today().isoformat()
    })


@router.post("/tasks/{task_id}/update")
def update_task(
    task_id: int,
    task_name: str = Form(...),
    responsible_person: str = Form(""),
    measurement_date: str = Form(""),
    sampling_start_time: str = Form(""),
    sampling_end_time: str = Form(""),
    status: str = Form("planned"),
    site_notes: str = Form(""),
    db=Depends(get_db)
):
    if not task_name.strip():
        raise HTTPException(status_code=400, detail="任务名称不能为空")
    if status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="无效的任务状态")

    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_tasks WHERE id = ?", (task_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")

    cursor.execute("""
        UPDATE measurement_tasks SET
            task_name = ?, responsible_person = ?, measurement_date = ?,
            sampling_start_time = ?, sampling_end_time = ?, status = ?, site_notes = ?
        WHERE id = ?
    """, (
        task_name.strip(), responsible_person.strip(),
        measurement_date if measurement_date else None,
        sampling_start_time if sampling_start_time else None,
        sampling_end_time if sampling_end_time else None,
        status, site_notes.strip(), task_id
    ))
    db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/delete")
def delete_task(task_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_tasks WHERE id = ?", (task_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")

    photo_dir = os.path.join(UPLOAD_DIR, f"task_{task_id}")
    if os.path.exists(photo_dir):
        shutil.rmtree(photo_dir)

    cursor.execute("DELETE FROM measurement_tasks WHERE id = ?", (task_id,))
    db.commit()
    return RedirectResponse(url="/tasks", status_code=303)


@router.post("/tasks/{task_id}/equipment/add")
def add_task_equipment(task_id: int, equipment_id: int = Form(...), db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_tasks WHERE id = ?", (task_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")
    cursor.execute("SELECT id FROM equipment WHERE id = ?", (equipment_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="设备不存在")

    cursor.execute("""
        INSERT OR IGNORE INTO task_equipment (task_id, equipment_id)
        VALUES (?, ?)
    """, (task_id, equipment_id))
    db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/equipment/{equipment_id}/remove")
def remove_task_equipment(task_id: int, equipment_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        DELETE FROM task_equipment WHERE task_id = ? AND equipment_id = ?
    """, (task_id, equipment_id))
    db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/session/link")
def link_task_session(task_id: int, session_id: int = Form(...), db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_tasks WHERE id = ?", (task_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")
    cursor.execute("SELECT id FROM measurement_sessions WHERE id = ?", (session_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="测量场次不存在")

    cursor.execute("""
        UPDATE measurement_sessions SET task_id = ? WHERE id = ?
    """, (task_id, session_id))
    db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/session/{session_id}/unlink")
def unlink_task_session(task_id: int, session_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        UPDATE measurement_sessions SET task_id = NULL WHERE id = ?
    """, (session_id,))
    db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/execution/create")
def create_execution_record(
    task_id: int,
    execution_date: str = Form(""),
    weather_condition: str = Form(""),
    ambient_noise_level: str = Form(""),
    temperature: str = Form(""),
    humidity: str = Form(""),
    environment_notes: str = Form(""),
    executor: str = Form(""),
    db=Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_tasks WHERE id = ?", (task_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")

    cursor.execute("""
        INSERT INTO task_execution_records
        (task_id, execution_date, weather_condition, ambient_noise_level,
         temperature, humidity, environment_notes, executor)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_id,
        execution_date if execution_date else None,
        weather_condition.strip(),
        float(ambient_noise_level) if ambient_noise_level else None,
        float(temperature) if temperature else None,
        float(humidity) if humidity else None,
        environment_notes.strip(),
        executor.strip()
    ))
    db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/photos/upload")
async def upload_photo(
    task_id: int,
    photo: UploadFile = File(...),
    photo_description: str = Form(""),
    db=Depends(get_db)
):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM measurement_tasks WHERE id = ?", (task_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="任务不存在")

    task_dir = os.path.join(UPLOAD_DIR, f"task_{task_id}")
    os.makedirs(task_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_ext = os.path.splitext(photo.filename)[1] if photo.filename else ".jpg"
    filename = f"{timestamp}{file_ext}"
    file_path = os.path.join(task_dir, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)

    relative_path = f"/static/uploads/task_{task_id}/{filename}"

    cursor.execute("""
        INSERT INTO task_photos (task_id, photo_path, photo_description)
        VALUES (?, ?, ?)
    """, (task_id, relative_path, photo_description.strip()))
    db.commit()

    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/photos/{photo_id}/delete")
def delete_photo(task_id: int, photo_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT photo_path FROM task_photos WHERE id = ? AND task_id = ?", (photo_id, task_id))
    photo = cursor.fetchone()
    if not photo:
        raise HTTPException(status_code=404, detail="照片不存在")

    photo_path = photo["photo_path"]
    full_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), photo_path.lstrip("/"))
    if os.path.exists(full_path):
        os.remove(full_path)

    cursor.execute("DELETE FROM task_photos WHERE id = ?", (photo_id,))
    db.commit()
    return RedirectResponse(url=f"/tasks/{task_id}", status_code=303)


@router.get("/equipment", response_class=HTMLResponse)
def equipment_list(request: Request, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("""
        SELECT e.*,
               (SELECT calibration_date FROM equipment_calibration 
                WHERE equipment_id = e.id ORDER BY calibration_date DESC LIMIT 1) as last_cal_date,
               (SELECT calibration_result FROM equipment_calibration 
                WHERE equipment_id = e.id ORDER BY calibration_date DESC LIMIT 1) as last_cal_result,
               julianday(e.next_calibration_date) - julianday(?) as days_remaining
        FROM equipment e
        ORDER BY e.type, e.name
    """, (date.today(),))
    equipment = [dict(row) for row in cursor.fetchall()]

    warnings = get_calibration_warning(db)

    return templates.TemplateResponse("equipment.html", {
        "request": request,
        "equipment": equipment,
        "equipment_types": EQUIPMENT_TYPES,
        "calibration_results": CALIBRATION_RESULTS,
        "warnings": warnings,
        "today": date.today().isoformat()
    })


@router.post("/equipment/create")
def create_equipment(
    name: str = Form(...),
    type: str = Form(...),
    model: str = Form(""),
    serial_number: str = Form(""),
    status: str = Form("available"),
    calibration_interval_days: int = Form(365),
    last_calibration_date: str = Form(""),
    next_calibration_date: str = Form(""),
    notes: str = Form(""),
    db=Depends(get_db)
):
    if not name.strip():
        raise HTTPException(status_code=400, detail="设备名称不能为空")
    if type not in EQUIPMENT_TYPES:
        raise HTTPException(status_code=400, detail="无效的设备类型")

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO equipment
        (name, type, model, serial_number, status, calibration_interval_days,
         last_calibration_date, next_calibration_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name.strip(), type, model.strip(), serial_number.strip(), status,
        calibration_interval_days,
        last_calibration_date if last_calibration_date else None,
        next_calibration_date if next_calibration_date else None,
        notes.strip()
    ))
    db.commit()
    return RedirectResponse(url="/equipment", status_code=303)


@router.post("/equipment/{equipment_id}/update")
def update_equipment(
    equipment_id: int,
    name: str = Form(...),
    type: str = Form(...),
    model: str = Form(""),
    serial_number: str = Form(""),
    status: str = Form("available"),
    calibration_interval_days: int = Form(365),
    last_calibration_date: str = Form(""),
    next_calibration_date: str = Form(""),
    notes: str = Form(""),
    db=Depends(get_db)
):
    if not name.strip():
        raise HTTPException(status_code=400, detail="设备名称不能为空")
    if type not in EQUIPMENT_TYPES:
        raise HTTPException(status_code=400, detail="无效的设备类型")

    cursor = db.cursor()
    cursor.execute("SELECT id FROM equipment WHERE id = ?", (equipment_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="设备不存在")

    cursor.execute("""
        UPDATE equipment SET
            name = ?, type = ?, model = ?, serial_number = ?, status = ?,
            calibration_interval_days = ?, last_calibration_date = ?,
            next_calibration_date = ?, notes = ?
        WHERE id = ?
    """, (
        name.strip(), type, model.strip(), serial_number.strip(), status,
        calibration_interval_days,
        last_calibration_date if last_calibration_date else None,
        next_calibration_date if next_calibration_date else None,
        notes.strip(), equipment_id
    ))
    db.commit()
    return RedirectResponse(url="/equipment", status_code=303)


@router.post("/equipment/{equipment_id}/delete")
def delete_equipment(equipment_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT id FROM equipment WHERE id = ?", (equipment_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="设备不存在")

    cursor.execute("DELETE FROM equipment WHERE id = ?", (equipment_id,))
    db.commit()
    return RedirectResponse(url="/equipment", status_code=303)


@router.get("/equipment/{equipment_id}/calibrations", response_class=HTMLResponse)
def equipment_calibrations(request: Request, equipment_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,))
    equipment = cursor.fetchone()
    if not equipment:
        raise HTTPException(status_code=404, detail="设备不存在")
    equipment = dict(equipment)

    cursor.execute("""
        SELECT * FROM equipment_calibration
        WHERE equipment_id = ?
        ORDER BY calibration_date DESC
    """, (equipment_id,))
    calibrations = [dict(row) for row in cursor.fetchall()]

    return templates.TemplateResponse("equipment_calibrations.html", {
        "request": request,
        "equipment": equipment,
        "calibrations": calibrations,
        "calibration_results": CALIBRATION_RESULTS,
        "today": date.today().isoformat()
    })


@router.post("/equipment/{equipment_id}/calibrations/create")
def create_calibration(
    equipment_id: int,
    calibration_date: str = Form(...),
    calibration_result: str = Form(...),
    calibration_value: str = Form(""),
    calibrated_by: str = Form(""),
    certificate_number: str = Form(""),
    next_calibration_date: str = Form(""),
    notes: str = Form(""),
    db=Depends(get_db)
):
    if not calibration_date:
        raise HTTPException(status_code=400, detail="校准日期不能为空")
    if calibration_result not in CALIBRATION_RESULTS:
        raise HTTPException(status_code=400, detail="无效的校准结果")

    cursor = db.cursor()
    cursor.execute("SELECT id FROM equipment WHERE id = ?", (equipment_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="设备不存在")

    cursor.execute("""
        INSERT INTO equipment_calibration
        (equipment_id, calibration_date, calibration_result, calibration_value,
         calibrated_by, certificate_number, next_calibration_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        equipment_id, calibration_date, calibration_result,
        float(calibration_value) if calibration_value else None,
        calibrated_by.strip(), certificate_number.strip(),
        next_calibration_date if next_calibration_date else None,
        notes.strip()
    ))

    cursor.execute("""
        UPDATE equipment SET
            last_calibration_date = ?,
            next_calibration_date = ?
        WHERE id = ?
    """, (
        calibration_date,
        next_calibration_date if next_calibration_date else None,
        equipment_id
    ))

    db.commit()
    return RedirectResponse(url=f"/equipment/{equipment_id}/calibrations", status_code=303)


@router.post("/equipment/calibrations/{calibration_id}/delete")
def delete_calibration(calibration_id: int, db=Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT equipment_id FROM equipment_calibration WHERE id = ?", (calibration_id,))
    cal = cursor.fetchone()
    if not cal:
        raise HTTPException(status_code=404, detail="校准记录不存在")

    equipment_id = cal["equipment_id"]

    cursor.execute("DELETE FROM equipment_calibration WHERE id = ?", (calibration_id,))

    cursor.execute("""
        SELECT calibration_date, next_calibration_date 
        FROM equipment_calibration 
        WHERE equipment_id = ? 
        ORDER BY calibration_date DESC 
        LIMIT 1
    """, (equipment_id,))
    latest = cursor.fetchone()

    if latest:
        cursor.execute("""
            UPDATE equipment SET
                last_calibration_date = ?,
                next_calibration_date = ?
            WHERE id = ?
        """, (latest["calibration_date"], latest["next_calibration_date"], equipment_id))
    else:
        cursor.execute("""
            UPDATE equipment SET
                last_calibration_date = NULL,
                next_calibration_date = NULL
            WHERE id = ?
        """, (equipment_id,))

    db.commit()
    return RedirectResponse(url=f"/equipment/{equipment_id}/calibrations", status_code=303)
