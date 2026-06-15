import sqlite3
import sys
sys.path.insert(0, '.')

from app.database import init_db, get_db

# 初始化数据库
init_db()
print("数据库初始化完成")

conn = sqlite3.connect('acoustics.db')
cursor = conn.cursor()

# 检查新表是否存在
tables = [
    'version_task_snapshots', 
    'version_equipment_snapshots', 
    'version_calibration_snapshots', 
    'version_execution_snapshots'
]
print("\n=== 新表检查 ===")
for t in tables:
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{t}'")
    result = cursor.fetchone()
    status = "✓ 存在" if result else "✗ 不存在"
    print(f"  表 {t}: {status}")

# 检查 measurement_versions 是否有 task_id 字段
cursor.execute('PRAGMA table_info(measurement_versions)')
cols = [col[1] for col in cursor.fetchall()]
print(f"\nmeasurement_versions 表包含字段数: {len(cols)}")
print(f"是否有 task_id 字段: {'✓' if 'task_id' in cols else '✗'}")

# 查看任务
cursor.execute('SELECT id, stage_id, task_name, responsible_person FROM measurement_tasks')
tasks = cursor.fetchall()
print(f"\n=== 任务列表 (共 {len(tasks)} 个) ===")
for t in tasks:
    print(f"  任务ID: {t[0]}, 戏台ID: {t[1]}, 名称: {t[2]}, 负责人: {t[3]}")

# 查看设备
cursor.execute('SELECT id, name, type, status FROM equipment')
equipment = cursor.fetchall()
print(f"\n=== 设备列表 (共 {len(equipment)} 个) ===")
for e in equipment:
    print(f"  设备ID: {e[0]}, 名称: {e[1]}, 类型: {e[2]}, 状态: {e[3]}")

# 查看现有版本
cursor.execute('SELECT id, stage_id, version_number, task_id FROM measurement_versions ORDER BY id')
versions = cursor.fetchall()
print(f"\n=== 现有版本 (共 {len(versions)} 个) ===")
for v in versions:
    print(f"  版本ID: {v[0]}, 戏台ID: {v[1]}, 版本号: {v[2]}, 关联任务ID: {v[3]}")

conn.close()
print("\n数据库检查完成！")
