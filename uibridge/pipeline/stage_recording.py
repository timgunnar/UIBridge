"""Stage 1: Recording — Browser interaction → RawRecording"""
import logging

logger = logging.getLogger(__name__)


class StageRecording:
    def record(self, page, locator_attrs=None):
        from ..engine.recorder import RecordingSession
        return RecordingSession(page, locator_attrs=locator_attrs)
