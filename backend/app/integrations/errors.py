class IntegrationError(RuntimeError):
    """A secret-safe failure raised by an external service boundary."""

    retryable = False

    def __init__(self, code: str, unsafe_context: object | None = None) -> None:
        del unsafe_context
        self.code = code
        super().__init__(code)


class TransientIntegrationError(IntegrationError):
    """An external failure that a worker may retry later."""

    retryable = True


class PermanentIntegrationError(IntegrationError):
    """An external failure that retrying unchanged input cannot fix."""


class InvalidModelOutput(PermanentIntegrationError):
    """A model response failed schema validation after one repair."""
