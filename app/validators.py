from fastapi import HTTPException


def validate_coordinates(stage_id: int, x: float, y: float, conn, exclude_point_id: int = None):
    cursor = conn.cursor()
    if exclude_point_id:
        cursor.execute(
            "SELECT id FROM measurement_points WHERE stage_id = ? AND x = ? AND y = ? AND id != ?",
            (stage_id, x, y, exclude_point_id),
        )
    else:
        cursor.execute(
            "SELECT id FROM measurement_points WHERE stage_id = ? AND x = ? AND y = ?",
            (stage_id, x, y),
        )
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail=f"测量点坐标 ({x}, {y}) 在该戏台中已存在，坐标不能重复")


def validate_acoustic_values(sound_pressure=None, reverberation_time=None, speech_clarity=None):
    if sound_pressure is not None and sound_pressure < 0:
        raise HTTPException(status_code=400, detail="声压值不能为负数")
    if reverberation_time is not None and reverberation_time < 0:
        raise HTTPException(status_code=400, detail="混响时间不能为负数")
    if speech_clarity is not None and (speech_clarity < 0 or speech_clarity > 1):
        raise HTTPException(status_code=400, detail="语言清晰度(STI)应在0到1之间")


def validate_same_stage(session_ids: list, conn):
    if len(session_ids) < 2:
        raise HTTPException(status_code=400, detail="对比实验至少需要两个测量场次")
    cursor = conn.cursor()
    placeholders = ",".join("?" * len(session_ids))
    cursor.execute(
        f"SELECT DISTINCT stage_id FROM measurement_sessions WHERE id IN ({placeholders})",
        session_ids,
    )
    stage_ids = [row["stage_id"] for row in cursor.fetchall()]
    if len(stage_ids) > 1:
        raise HTTPException(status_code=400, detail="对比实验必须来自同一戏台")


def check_abnormal_data(stage_id: int, conn) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ad.sound_pressure, ad.reverberation_time, ad.speech_clarity
        FROM acoustic_data ad
        JOIN measurement_sessions ms ON ad.session_id = ms.id
        WHERE ms.stage_id = ?
        """,
        (stage_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return False

    sp_values = [r["sound_pressure"] for r in rows if r["sound_pressure"] is not None]
    rt_values = [r["reverberation_time"] for r in rows if r["reverberation_time"] is not None]
    sc_values = [r["speech_clarity"] for r in rows if r["speech_clarity"] is not None]

    def has_outliers(values):
        if len(values) < 3:
            return False
        mean = sum(values) / len(values)
        std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
        if std == 0:
            return False
        return any(abs(v - mean) > 2 * std for v in values)

    return has_outliers(sp_values) or has_outliers(rt_values) or has_outliers(sc_values)


def invalidate_heatmaps(session_id: int, conn):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE heatmap_cache SET is_stale = 1 WHERE session_id = ?",
        (session_id,),
    )
