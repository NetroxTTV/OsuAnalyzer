"""Checks GitHub for a newer release in the background."""

import threading

from PySide6.QtCore import QObject, Signal

from ..updates import describe_error, latest_release


class UpdateChecker(QObject):
    """check() -> finished(Release or None, error message or "")."""

    finished = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.checking = False
        self.release = None       # last answer
        self.error_detail = ""    # technical message of the last failure

    def check(self):
        if self.checking:
            return
        self.checking = True

        def work():
            try:
                release, error = latest_release(), ""
            except Exception as e:  # noqa: BLE001 - offline, GitHub down, rate limited...
                release, error = None, describe_error(e)
                self.error_detail = str(e) or type(e).__name__
            self.finished.emit(release, error)

        self.finished.connect(self._done)
        threading.Thread(target=work, daemon=True).start()

    def _done(self, release, _error):
        self.finished.disconnect(self._done)
        self.checking = False
        if release:
            self.release = release
