from collections.abc import Callable
from dataclasses import dataclass
from tqdm import tqdm

@dataclass
class ProgressEvent:
    stage: str
    current: int
    total: int
    message: str | None = None
    done: bool = False

ProgressCallback = Callable[[ProgressEvent], None]

def emit_progress(
    progress: ProgressCallback | None,
    stage: str,
    current: int,
    total: int,
    message: str | None = None,
    done: bool = False,
):

    if progress is None:
        return

    progress(
        ProgressEvent(
            stage=stage,
            current=current,
            total=total,
            message=message,
            done=done,
        )
    )

class TerminalProgress:
    def __init__(self):
        self.bar = None

    def __call__(self, event: ProgressEvent):
        if self.bar is None:
            self.bar = tqdm(
                total=event.total,
                desc=event.stage,
            )

        delta = event.current - self.bar.n

        if delta>0:
            self.bar.update(delta)
        if event.done:
            self.bar.close()
            self.bar = None
