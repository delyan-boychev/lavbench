"""Pseudonym generation and metric constants."""

import secrets
import time
from typing import Any

ADJECTIVES = [
    "Quantum",
    "Cyber",
    "Stellar",
    "Hyper",
    "Neural",
    "Shadow",
    "Alpha",
    "Zenith",
    "Vector",
    "Binary",
    "Cosmic",
    "Solar",
    "Galactic",
    "Vortex",
    "Aurora",
    "Plasma",
    "Pixel",
    "Neon",
    "Aero",
    "Crypto",
    "Apex",
    "Sonic",
    "Tectonic",
    "Magneto",
    "Astral",
    "Ember",
    "Frost",
    "Aether",
    "Primal",
    "Kinetic",
    "Omega",
    "Obsidian",
    "Radiant",
    "Volcanic",
    "Spectral",
    "Dynamic",
    "Abyssal",
    "Magnetic",
    "Luminous",
]
NOUNS = [
    "Falcon",
    "Pioneer",
    "Voyager",
    "Oracle",
    "Matrix",
    "Nomad",
    "Eclipse",
    "Ranger",
    "Titan",
    "Specter",
    "Phoenix",
    "Horizon",
    "Sentinel",
    "Comet",
    "Odyssey",
    "Genesis",
    "Summit",
    "Pulse",
    "Beacon",
    "Glitch",
    "Helix",
    "Spark",
    "Quasar",
    "Rogue",
    "Nova",
    "Seeker",
    "Pulsar",
    "Catalyst",
    "Entropy",
    "Nebula",
    "Vanguard",
    "Anomaly",
    "Warden",
    "Strider",
    "Rift",
    "Core",
    "Void",
    "Phantom",
    "Goliath",
    "Mirage",
]

METRIC_LOWER_IS_BETTER = {
    "logloss": True,
    "brier_score": True,
    "rmse": True,
    "mae": True,
    "mape": True,
    "median_ae": True,
    "ter": True,
    "mse": True,
    "fid": True,
    "lpips": True,
    "niqe": True,
    "mel_lsd": True,
}


def is_metric_lower_better(metric_name: str) -> bool:
    if not metric_name:
        return False
    return METRIC_LOWER_IS_BETTER.get(metric_name.lower().strip(), False)


def metric_direction_from_config(metric_name: str, cfg: Any) -> bool:
    """Return True when a metric is lower-better, honoring per-metric config.

    Priority: the task's ``metrics_config`` entry ``higher_is_better`` wins when
    explicitly set; otherwise fall back to the static METRIC_LOWER_IS_BETTER
    map. The runner (score normalization) and the leaderboards (sort direction)
    must call this same function so stored scores are ALWAYS normalized to
    higher-is-better and every leaderboard can sort descending.
    """
    if isinstance(cfg, dict):
        flag = cfg.get("higher_is_better")
        if isinstance(flag, bool):
            return not flag
    return is_metric_lower_better(metric_name)


def to_base36(num: int) -> str:
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    result = ""
    while num > 0:
        num, d = divmod(num, 36)
        result = chars[d] + result
    return result or "0"


def generate_pseudonym() -> str:
    adj = secrets.choice(ADJECTIVES)
    noun = secrets.choice(NOUNS)
    ts_ms = int(time.time() * 1000)
    raw_num = ts_ms % 1679616
    scrambled = (raw_num * 7919 + 104729) % 1679616
    suffix = to_base36(scrambled).zfill(4)
    return f"{adj}-{noun}-{suffix}"
