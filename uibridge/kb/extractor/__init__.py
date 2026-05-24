"""KBExtractor — assembled from mixin modules for maintainability."""

from ._base import _ExtractorBase
from ._python import _PythonMixin
from ._java import _JavaMixin
from ._documents import _DocumentsMixin
from ._profile import _ProfileMixin
from ._aggregation import _AggregationMixin
from ._conventions import _ConventionsMixin


class KBExtractor(
    _ConventionsMixin,
    _AggregationMixin,
    _ProfileMixin,
    _DocumentsMixin,
    _JavaMixin,
    _PythonMixin,
    _ExtractorBase,
):
    """Extracts framework knowledge from source code, runtime traces, and NL documents."""
    pass
