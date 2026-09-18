"""Package: template_rendering
Description: High-fidelity template preservation rendering engine for MSB MB07 DOCX proposals.
"""

from .bindings import (
    MutationType,
    TargetRelationship,
    TemplateBinding,
    MB07_STANDARD_BINDINGS,
)
from .anchor_resolver import (
    AnchorError,
    AnchorNotFoundError,
    AnchorAmbiguousError,
    TemplateStructureMismatchError,
    AnchorResolver,
)
from .safe_mutation import (
    SafeCellMutator,
    SafeParagraphMutator,
    DynamicRowCloner,
)
from .structure_guard import (
    MB07FidelityError,
    UnsupportedTemplateVersionError,
    StructureGuard,
    validate_template_compatibility,
)

__all__ = [
    "MutationType",
    "TargetRelationship",
    "TemplateBinding",
    "MB07_STANDARD_BINDINGS",
    "AnchorError",
    "AnchorNotFoundError",
    "AnchorAmbiguousError",
    "TemplateStructureMismatchError",
    "AnchorResolver",
    "SafeCellMutator",
    "SafeParagraphMutator",
    "DynamicRowCloner",
    "MB07FidelityError",
    "UnsupportedTemplateVersionError",
    "StructureGuard",
    "validate_template_compatibility",
]
