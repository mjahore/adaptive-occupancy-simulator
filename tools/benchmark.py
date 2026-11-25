"""Synthetic year-size benchmark; run from repository root."""

import json
import platform
import sys
import tracemalloc
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.adaptive_occupancy_simulator.const import settings  # noqa: E402
from custom_components.adaptive_occupancy_simulator.model import Frame, HybridModel, constrain  # noqa: E402


def main():
    config = settings({"lights": [f"light.room_{i}" for i in range(32)]})
    tracemalloc.start()
    start = perf_counter()
    frames = []
    for day in range(365):
        for slot in range(288):
            # Eight correlated four-light groups; observed states remain sparse.
            groups = ((slot // 6 + day) % 256) if slot >= 190 or slot < 85 else 0
            mask = sum(15 << (4 * i) for i in range(8) if groups & (1 << i))
            frames.append(
                Frame(
                    1767225600 + day * 86400 + slot * 300,
                    mask,
                    slot * 5,
                    int(day % 7 >= 5),
                    -15 if slot >= 190 or slot < 85 else 30,
                )
            )
    created = perf_counter()
    model = HybridModel(frames, config, ZoneInfo("UTC"))
    fitted = perf_counter()
    targets = [
        Frame(1798761600 + i * 300, 0, i * 5, 0, -15 if i >= 190 or i < 85 else 30) for i in range(288)
    ]
    plan = constrain(model.generate(targets, 2026), config["lights"], config, 2026)
    generated = perf_counter()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.system(),
                "architecture": platform.machine(),
                "frames": len(frames),
                "lights": 32,
                "fixture_seconds": round(created - start, 3),
                "fit_seconds": round(fitted - created, 3),
                "plan_seconds": round(generated - fitted, 3),
                "peak_python_allocations_mib": round(peak / 2**20, 2),
                "actions": len(plan),
                "model": model.diagnostics(),
                "note": "Synthetic benchmark with tracemalloc overhead; not a Raspberry Pi measurement.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
