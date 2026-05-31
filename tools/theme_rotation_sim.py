"""
Simulate ThemeManager._do_rotate() N times with all themes in the pool.
Outputs theme_sequence.txt and theme_frequency.txt in the project root.
Run from anywhere: python tools/theme_rotation_sim.py
"""

import random
import colorsys
from collections import deque, Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from fabulor.themes import THEMES

ALL_THEMES = sorted(THEMES.keys())
N = 10_000


def _theme_distance(name_a: str, name_b: str) -> float:
    def hex_to_hsl(hex_color: str):
        hex_color = hex_color.lstrip("#")
        r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
        h, lum, s = colorsys.rgb_to_hls(r, g, b)
        return h * 360, s, lum

    def hue_dist(h1, h2):
        d = abs(h1 - h2)
        return min(d, 360 - d) / 180.0

    t_a = THEMES.get(name_a, {})
    t_b = THEMES.get(name_b, {})
    bg_a = t_a.get("bg_main", "#1A1A1A")
    bg_b = t_b.get("bg_main", "#1A1A1A")
    acc_a = t_a.get("accent", "#FFFFFF")
    acc_b = t_b.get("accent", "#FFFFFF")

    h_bg_a, s_bg_a, l_bg_a = hex_to_hsl(bg_a)
    h_bg_b, s_bg_b, l_bg_b = hex_to_hsl(bg_b)
    h_acc_a = hex_to_hsl(acc_a)[0]
    h_acc_b = hex_to_hsl(acc_b)[0]

    return (hue_dist(h_bg_a, h_bg_b) * 0.45
            + abs(s_bg_a - s_bg_b) * 0.15
            + abs(l_bg_a - l_bg_b) * 0.25
            + hue_dist(h_acc_a, h_acc_b) * 0.15)


def simulate(selected_themes: list[str], n: int) -> list[str]:
    _EXCLUSION_THRESHOLD = 0.5
    _MIN_POOL = 4

    current = random.choice(selected_themes)
    recent: deque[str] = deque(maxlen=10)
    recent.append(current)
    sequence = [current]

    for _ in range(n - 1):
        candidates = list(selected_themes)
        pool = [c for c in candidates if c != current]

        named = [c for c in pool if c is not None]

        full_named_count = len(named)
        recent_exclude_n = min(full_named_count // 4, 8)

        recent_set = set(list(recent)[-recent_exclude_n:]) if recent_exclude_n > 0 else set()
        named_after_recent = [c for c in named if c not in recent_set]

        if len(named_after_recent) < _MIN_POOL:
            recent_ordered = list(recent)
            for candidate in recent_ordered:
                if candidate in named and candidate not in named_after_recent:
                    named_after_recent.append(candidate)
                if len(named_after_recent) >= _MIN_POOL:
                    break
        named = named_after_recent

        if current is not None and len(named) > _MIN_POOL:
            distances = {c: _theme_distance(current, c) for c in named}
            filtered = [c for c in named if distances[c] <= _EXCLUSION_THRESHOLD]
            if len(filtered) >= _MIN_POOL:
                named = filtered
                distances = {c: distances[c] for c in named}
        else:
            distances = {c: _theme_distance(current, c) for c in named} if current else {}

        epsilon = 1e-6
        weights = [1.0 / (distances.get(c, 0.25) ** 1.0 + epsilon) for c in named]

        chosen = random.choices(named, weights=weights, k=1)[0]
        sequence.append(chosen)
        recent.append(chosen)
        current = chosen

    return sequence


if __name__ == "__main__":
    ROOT = Path(__file__).parent.parent
    random.seed(42)
    seq = simulate(ALL_THEMES, N)

    with open(ROOT / "theme_sequence.txt", "w") as f:
        for i, name in enumerate(seq, 1):
            f.write(f"{i:4d}  {name}\n")

    counts = Counter(seq)
    total = len(seq)
    with open(ROOT / "theme_frequency.txt", "w") as f:
        f.write(f"{'Theme':<32}  {'Count':>5}  {'%':>6}\n")
        f.write("-" * 48 + "\n")
        for name, count in sorted(counts.items(), key=lambda x: -x[1]):
            f.write(f"{name:<32}  {count:>5}  {count/total*100:>5.1f}%\n")
        f.write("-" * 48 + "\n")
        f.write(f"{'Total':<32}  {total:>5}  100.0%\n")
        missing = [t for t in ALL_THEMES if t not in counts]
        if missing:
            f.write(f"\nNEVER SHOWN ({len(missing)}):\n")
            for t in missing:
                f.write(f"  {t}\n")

    print(f"Simulated {N} rotations across {len(ALL_THEMES)} themes.")
    print(f"Wrote {ROOT}/theme_sequence.txt and theme_frequency.txt")

    # Quick console summary
    print(f"\n{'Theme':<32}  {'Count':>5}  {'%':>6}")
    print("-" * 48)
    for name, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"{name:<32}  {count:>5}  {count/total*100:>5.1f}%")
    missing = [t for t in ALL_THEMES if t not in counts]
    if missing:
        print(f"\nNEVER SHOWN: {missing}")
