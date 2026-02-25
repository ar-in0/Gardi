"""Inter-station traversal time analyzer for WTT data."""

import statistics
from collections import defaultdict

import pandas as pd

from gardi.core.models import DISTANCE_MAP


# Ordered station list derived from DISTANCE_MAP
STATIONS_ORDERED = sorted(DISTANCE_MAP.keys(), key=lambda s: DISTANCE_MAP[s])

# Adjacent station pairs: (station_a, station_b, distance_km between them)
ADJACENT_PAIRS = []
for i in range(len(STATIONS_ORDERED) - 1):
    a, b = STATIONS_ORDERED[i], STATIONS_ORDERED[i + 1]
    ADJACENT_PAIRS.append((a, b, round(DISTANCE_MAP[b] - DISTANCE_MAP[a], 1)))

_ADJACENT_SET = set()
for a, b, _ in ADJACENT_PAIRS:
    _ADJACENT_SET.add((a, b))
    _ADJACENT_SET.add((b, a))


class TraversalAnalyzer:
    """Computes inter-station run times from parsed WTT services."""

    def analyze(self, wtt):
        """Return (DataFrame, metadata_dict) of traversal times."""
        # Collect raw run times keyed by (station_a, station_b, direction)
        samples = defaultdict(list)
        total_services = 0

        services = wtt.suburbanServices or (wtt.upServices + wtt.downServices)

        for svc in services:
            if not svc.events or len(svc.events) < 2:
                continue
            total_services += 1
            direction = svc.direction.name if svc.direction else "UNKNOWN"

            if not svc.legs:
                svc.build_legs()
            for leg in svc.legs:
                if (leg.from_station, leg.to_station) not in _ADJACENT_SET:
                    continue
                if leg.run_minutes <= 0 or leg.run_minutes > 30:
                    continue  # skip implausible values
                samples[(leg.from_station, leg.to_station, direction)].append(leg.run_minutes)

        # Build rows
        rows = []
        for (st_a, st_b, direction), times in samples.items():
            dist = abs(DISTANCE_MAP.get(st_a, 0) - DISTANCE_MAP.get(st_b, 0))
            rows.append({
                "station_a": st_a,
                "station_b": st_b,
                "distance_km": round(dist, 1),
                "direction": direction,
                "median_time": round(statistics.median(times), 1),
                "sample_count": len(times),
                "min_time": min(times),
                "max_time": max(times),
                "std_dev": round(statistics.stdev(times), 2) if len(times) > 1 else 0.0,
            })

        # Sort by direction then station order
        def sort_key(row):
            dir_ord = 0 if row["direction"] == "UP" else 1
            a_dist = DISTANCE_MAP.get(row["station_a"], 999)
            return (dir_ord, a_dist)

        rows.sort(key=sort_key)
        df = pd.DataFrame(rows)
        for col in ("sample_count", "min_time", "max_time"):
            if col in df.columns:
                df[col] = df[col].astype(int)

        low_sample_pairs = sum(1 for r in rows if r["sample_count"] < 10)
        metadata = {
            "total_services_sampled": total_services,
            "pair_count": len(rows),
            "pairs_with_low_samples": low_sample_pairs,
        }

        return df, metadata
