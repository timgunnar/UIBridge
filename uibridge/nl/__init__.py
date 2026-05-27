"""NL knowledge extraction — document ingestion + dialogue + manual injection.

Non-silent. The only module that actively converses with the user/Agent.
"""

from .doc_ingest import DocumentIngestor
from .intent_handler import IntentHandler
from .dialogue import DialogueManager

__all__ = ["DocumentIngestor", "IntentHandler", "DialogueManager"]
