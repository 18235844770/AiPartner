"""确认四个模型任务标识。不写入型号：具体型号尚未核实，重复执行也不会覆盖已有配置。"""

import sys
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.modules.infrastructure.domain.enums import CONFIG_TASK_TYPES, ModelConfigKey


def main() -> None:
    pairs = ", ".join(f"{key.value}->{task.value}" for key, task in CONFIG_TASK_TYPES.items())
    print(f"model config keys ok: {len(ModelConfigKey)} ({pairs})")
    print("no model name inserted")


if __name__ == "__main__":
    main()
