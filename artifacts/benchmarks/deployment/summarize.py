"""Summarize the four completed raw measurements without rewriting evidence."""

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODES = ("native-backend", "native-full", "docker-backend", "docker-full")


def main():
    rows = []
    for mode in MODES:
        result = json.loads((ROOT / f"{mode}.json").read_text())
        assert len(result["startup_seconds"]) == 3
        assert not result["load"]["failures"]
        rows.append(
            {
                "mode": mode,
                "startup_seconds": [round(t, 2) for t in result["startup_seconds"]],
                "startup_median_seconds": round(statistics.median(result["startup_seconds"]), 2),
                "idle_cpu_one_core_percent": round(result["idle"]["cpu_mean_one_core_percent"], 2),
                "load_cpu_one_core_percent": round(result["load"]["cpu_mean_one_core_percent"], 2),
                "idle_rss_mib": round(result["idle"]["rss_mean_mib"], 1),
                "load_rss_peak_mib": round(result["load"]["rss_peak_mib"], 1),
                "idle_working_set_mib": round(result["idle"]["working_set_mean_mib"], 1),
                "load_working_set_peak_mib": round(result["load"]["working_set_peak_mib"], 1),
                "host_available_min_mib": round(
                    min(result[phase]["host_available_min_mib"] for phase in ("idle", "load")), 1
                ),
                "requests": result["load"]["successful_requests"],
                "latency_p95_ms": round(result["load"]["latency_p95_ms"], 2),
            }
        )
    summary = {"cpu_basis": "100%=one logical core", "measurements": rows}
    (ROOT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
