from collections.abc import Callable
from dataclasses import dataclass
from tqdm import tqdm

@dataclass
class ProgressEvent:
    stage: str
    current: int
    total: int
    message: str | None = None

ProgressCallback = Callable[[ProgressEvent], None]

def emit_progress(
    progress: ProgressCallback | None,
    stage: str,
    current: int,
    total: int,
    message: str | None = None,
):

    if progress is None:
        return

    progress(
        ProgressEvent(
            stage=stage,
            current=current,
            total=total,
            message=message,
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
        if event.message and "concluído" in event.message.lower():
            self.bar.close()
            self.bar = None
