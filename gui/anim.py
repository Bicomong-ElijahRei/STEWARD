"""Safe animation primitives for Phase B.

Every animation in STEWARD must:
- run on the Tk main thread via after() and never block it,
- cancel itself when its widget is destroyed,
- never raise TclError during shutdown.
"""


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def lerp_color(hex_a: str, hex_b: str, t: float) -> str:
    """Interpolate between two #RRGGBB colors. t=0 -> a, t=1 -> b."""
    t = max(0.0, min(1.0, t))
    ra, ga, ba = int(hex_a[1:3], 16), int(hex_a[3:5], 16), int(hex_a[5:7], 16)
    rb, gb, bb = int(hex_b[1:3], 16), int(hex_b[3:5], 16), int(hex_b[5:7], 16)
    r = int(lerp(ra, rb, t))
    g = int(lerp(ga, gb, t))
    b = int(lerp(ba, bb, t))
    return f"#{r:02X}{g:02X}{b:02X}"


class SafeTick:
    """Repeating after() loop that dies quietly with its widget.

    on_tick() returning False ends the loop and fires on_done once.
    cancel() ends it without on_done. A destroyed widget or an after()
    error also ends it without raising.
    """

    def __init__(self, widget, interval_ms, on_tick, on_done=None):
        self._widget = widget
        self._interval = int(interval_ms)
        self._on_tick = on_tick
        self._on_done = on_done
        self._cancelled = False
        self._finished = False
        self._after_id = None

    def start(self):
        self._schedule()
        return self

    def cancel(self):
        self._cancelled = True
        self._cancel_after()

    def _schedule(self):
        if self._cancelled or self._finished:
            return
        try:
            if not self._widget.winfo_exists():
                self._finish()
                return
            self._after_id = self._widget.after(self._interval, self._step)
        except Exception:
            self._finish()

    def _step(self):
        self._after_id = None
        if self._cancelled or self._finished:
            return
        if self._on_tick() is False:
            self._finish()
        else:
            self._schedule()

    def _finish(self):
        if self._finished:
            return
        self._finished = True
        self._cancel_after()
        if self._on_done is not None and not self._cancelled:
            self._on_done()

    def _cancel_after(self):
        if self._after_id is not None:
            try:
                if self._widget.winfo_exists():
                    self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None