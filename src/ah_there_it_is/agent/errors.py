"""Agent/tool boundary errors."""


class AgentError(RuntimeError):
    pass


class ToolExecutionError(AgentError):
    pass


class ToolPreconditionError(ToolExecutionError):
    pass


class AgentLoopLimitError(AgentError):
    pass


class ProviderRequestError(AgentError):
    """A model provider could not complete the HTTP request."""


class ProviderRateLimitError(ProviderRequestError):
    """A provider rejected the request because a rate/quota limit was reached."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderProtocolError(AgentError):
    """A model provider returned a response that violates its contract."""
