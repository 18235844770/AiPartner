"""GPU 状态查询。未安装 torch 时安全降级。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GpuStatus:
    available: bool
    name: str | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None


def read_gpu_status() -> GpuStatus:
    try:
        import torch
    except ImportError:
        return GpuStatus(available=False)
    if not torch.cuda.is_available():
        return GpuStatus(available=False)
    index = torch.cuda.current_device()
    props = torch.cuda.get_device_properties(index)
    free_b, total_b = torch.cuda.mem_get_info(index)
    used_mb = (total_b - free_b) / (1024 * 1024)
    total_mb = total_b / (1024 * 1024)
    return GpuStatus(
        available=True,
        name=props.name,
        memory_used_mb=round(used_mb, 1),
        memory_total_mb=round(total_mb, 1),
    )
