"""Exceptions that carry useful messages to the GeoLibre interface."""


class AORCToDSSError(Exception):
    """Base class for expected processing failures."""

    code = "processing_error"
    retryable = False

    def __init__(self, message: str, guidance: str = "") -> None:
        super().__init__(message)
        self.guidance = guidance


class GeometryError(AORCToDSSError):
    """Raised when an area of interest cannot be used."""

    code = "invalid_geometry"


class ArchiveError(AORCToDSSError):
    """Raised when AORC metadata or data cannot be read."""

    code = "archive_error"
    retryable = True


class CancelledError(AORCToDSSError):
    """Raised when the user cancels a running job."""

    code = "cancelled"


class DSSDependencyError(AORCToDSSError):
    """Raised when the native HEC-DSS component cannot be loaded."""

    code = "dss_dependency_error"


class DSSWriteError(AORCToDSSError):
    """Raised when a DSS record cannot be written or read back."""

    code = "dss_write_error"


class ValidationError(AORCToDSSError):
    """Raised when output validation has failures."""

    code = "validation_error"
