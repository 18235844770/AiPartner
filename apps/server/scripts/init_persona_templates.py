"""校验六种人格模板。模板是配置数据，重复执行不会写入数据库。"""

import sys
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.modules.persona.domain.enums import MbtiType
from app.modules.persona.domain.templates import load_persona_templates


def main() -> None:
    templates = load_persona_templates()
    names = ", ".join(item.value for item in MbtiType)
    print(f"persona templates ok: {len(templates)} ({names})")


if __name__ == "__main__":
    main()
