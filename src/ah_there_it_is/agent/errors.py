"""Agent/tool boundary errors."""


class AgentError(RuntimeError):
    pass


class ToolExecutionError(AgentError):
    pass


class ToolPreconditionError(ToolExecutionError):
    pass


class AgentLoopLimitError(AgentError):
    pass
