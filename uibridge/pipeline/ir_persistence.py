"""IRPersistence — save/load pipeline IR for code regeneration."""
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

from ..engine.ir.semantic_action import SemanticActionSequence
from ..engine.ir.framework_call import FrameworkCallSequence
from ..engine.ir.raw_recording import RawRecording


class IRPersistence:
    """Persist intermediate representations under .uibridge/sessions/.

    Directory structure:
        .uibridge/sessions/{name}/
            raw_recording.json
            semantic.json
            framework.json
            generated_code.json
    """

    def __init__(self, project_root: str = "."):
        self.root = Path(project_root) / ".uibridge" / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)

    def _session_dir(self, input_file: str) -> Path:
        name = Path(input_file).stem
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, input_file: str, recording: RawRecording,
             semantic: SemanticActionSequence,
             framework: FrameworkCallSequence):
        d = self._session_dir(input_file)
        (d / "raw_recording.json").write_text(
            json.dumps(recording.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")
        (d / "semantic.json").write_text(
            json.dumps(semantic.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")
        (d / "framework.json").write_text(
            json.dumps(framework.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")

    def load(self, input_file: str) -> tuple[RawRecording, SemanticActionSequence, FrameworkCallSequence] | None:
        d = self._session_dir(input_file)
        if not (d / "framework.json").exists():
            return None
        recording = RawRecording.from_dict(
            json.loads((d / "raw_recording.json").read_text("utf-8")))
        semantic = SemanticActionSequence.from_dict(
            json.loads((d / "semantic.json").read_text("utf-8")))
        framework = FrameworkCallSequence.from_dict(
            json.loads((d / "framework.json").read_text("utf-8")))
        return recording, semantic, framework

    def save_generated_code(self, input_file: str, results: list[dict]):
        d = self._session_dir(input_file)
        serializable = []
        for r in results:
            item = {
                "test_name": r.get("test_name", ""),
                "status": str(r.get("verify", "")),
                "code_preview": r.get("code", "")[:500],
                "review_needed": r.get("review_needed", False),
                "kb_items_updated": r.get("kb_items_updated", 0),
            }
            serializable.append(item)
        (d / "generated_code.json").write_text(
            json.dumps(serializable, indent=2, ensure_ascii=False),
            encoding="utf-8")

    def load_generated_code(self, input_file: str) -> list[dict] | None:
        d = self._session_dir(input_file)
        fp = d / "generated_code.json"
        if not fp.exists():
            return None
        return json.loads(fp.read_text("utf-8"))

    def list_sessions(self) -> list[str]:
        if not self.root.exists():
            return []
        return [p.stem for p in self.root.iterdir()
                if p.is_dir() and (p / "framework.json").exists()]
