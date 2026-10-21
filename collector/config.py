"""Paths and sampling rates."""
from dataclasses import dataclass, field

@dataclass
class Settings:
    data_root: str = field(default_factory=lambda: __import__("project").data_root())
    base_interval: float = 3.0            # seconds between saved routine samples per device (idle)
    ring_idle_interval: float = 1.0       # screenshots kept in memory (not saved) while idle
    ring_active_interval: float = 0.3     # ... and while someone is touching the screen
    capture: str = "window"               # how the driver should take shots, if it has a choice (e.g. android: window /
                                          # adb); the driver may fall back to a costlier way
    slow_ring_idle_interval: float = 3.0  # slower rates whenever the shots are costly (e.g. taken inside the emulator)
    slow_ring_active_interval: float = 1.0
    ring_seconds: float = 8.0             # how far back the in-memory buffer reaches (pre-touch frames)
    png_level: int = 3                    # PNG compression 0-9 (3 = good speed/size balance)
    event_offsets: tuple = (0.3, 0.8, 1.5)  # extra samples after an event (a touch, or a recorder's)
    event_cooldown: float = 2.0           # min seconds between event bursts per device
    active_interval: float = 1.0          # routine sampling while someone is touching the screen
    active_window: float = 15.0           # seconds after the last touch that count as "active"
    record_touches: bool = True
    rescan_every: float = 10.0            # emulator / connection discovery
    status_every: float = 30.0            # console status line
    duration: float = 0.0                 # 0 = run until Ctrl+C
    status_file_every: float = 2.0        # live status for the UI: <data_root>\collector_status.json
                                          # stop request from the UI:  <data_root>\collector.stop
    only: list = field(default_factory=list)  # restrict to these instance names (empty = all)
