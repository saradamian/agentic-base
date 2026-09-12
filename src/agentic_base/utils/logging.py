"""Structlog configuration for JSON logging."""

import logging
import sys
import time
from types import TracebackType
from typing import Any

import structlog
from asgi_correlation_id import correlation_id
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from structlog.typing import EventDict, ExceptionRenderer, Processor, WrappedLogger

from agentic_base.config import get_settings

event_key = "message"

settings = get_settings()


def drop_color_message_key(
    _: WrappedLogger, __: str, event_dict: EventDict
) -> EventDict:
    """
    Processor that drops the `color_message` key from the event dict if it exists.

    Uvicorn logs the message a second time in the extra `color_message`, but we don't
    need it.
    """
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging(
    *, json_logs: bool = False, log_level: str = "INFO"
) -> None:  # pragma: no cover
    """Setups logging configuration."""
    timestamper = structlog.processors.TimeStamper(fmt="iso")

    shared_processors: list[Processor] = [
        # Merge context vars into the event dict, such as the request id.
        # Must be the first processor in the chain.
        structlog.contextvars.merge_contextvars,
        # Add the logger name to the event dict
        structlog.stdlib.add_logger_name,
        # Add the log level to the event dict
        structlog.stdlib.add_log_level,
        # make sure positional arguments are correctly formatted in log messages.
        structlog.stdlib.PositionalArgumentsFormatter(),
        # Add extra attributes of LogRecord objects to the event dictionary
        # so that values passed in the extra parameter of log methods pass
        # through to log output.
        structlog.stdlib.ExtraAdder(),
        # Remove the uvicorn color_message key from
        # the event dict as we will have the message twice otherwise.
        drop_color_message_key,
        # Add the timestamp to the event dict
        timestamper,
        # Add stack information with key ``stack`` if ``stack_info`` is `True`.
        structlog.processors.StackInfoRenderer(),
        # Rename the ``event`` key in event dict to the value of
        # the ``event_key`` parameter. This will make sure the key
        # in the JSON log message is the value of ``event_key`` parameter.
        structlog.processors.EventRenamer(to=event_key),
    ]

    if json_logs:
        # Format the exception only for JSON logs, as we want to pretty-print them when
        # using the ConsoleRenderer
        shared_processors.append(structlog.processors.format_exc_info)

    structlog.configure(
        processors=[
            *shared_processors,
            # Prepare event dict for `ProcessorFormatter`.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    log_renderer: structlog.types.Processor
    if json_logs:
        log_renderer = structlog.processors.JSONRenderer()
    else:
        console_kwargs: dict[str, object | ExceptionRenderer] = {"event_key": event_key}
        if settings.log_plain_traceback:
            console_kwargs["exception_formatter"] = structlog.dev.plain_traceback
        log_renderer = structlog.dev.ConsoleRenderer(**console_kwargs)  # type: ignore[arg-type]

    formatter = structlog.stdlib.ProcessorFormatter(
        # These run ONLY on `logging` entries that do NOT originate within
        # structlog.
        foreign_pre_chain=shared_processors,
        # These run on ALL entries after the pre_chain is done.
        processors=[
            # Remove _record & _from_structlog.
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            log_renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logging.basicConfig(level=log_level.upper(), handlers=[handler])

    for _log in ["uvicorn", "uvicorn.error"]:
        # Clear the log handlers for uvicorn loggers, and enable propagation
        # so the messages are caught by our root logger and formatted correctly
        # by structlog
        logging.getLogger(_log).handlers.clear()
        logging.getLogger(_log).propagate = True

    # Since we re-create the access logs ourselves, to add all information
    # in the structured log (see the `logging_middleware` in main.py), we clear
    # the handlers and prevent the logs to propagate to a logger higher up in the
    # hierarchy (effectively rendering them silent).
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False

    def handle_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        """
        Exception handler that catches everything except KeyboardInterrupt.

        Log any uncaught exception instead of letting it be printed by Python
        (but leave KeyboardInterrupt untouched to allow users to Ctrl+C to stop)
        See https://stackoverflow.com/a/16993115/3641865
        """
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logging.error(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_exception


class LogMiddleware(BaseHTTPMiddleware):
    """Logging middleware for starlette/fastapi."""

    def __init__(
        self, *args: Any, ignore_prefix: str | None = None, **kwargs: Any
    ) -> None:  # noqa: ANN401
        """Init LogMiddelware."""
        super().__init__(*args, **kwargs)
        self.access_logger = structlog.stdlib.get_logger("api.access")
        self.ignore_prefix = ignore_prefix

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Middleware entrypoint."""
        structlog.contextvars.clear_contextvars()
        # These context vars will be added to all log entries emitted during the request
        request_id = correlation_id.get()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start_time = time.perf_counter_ns()
        try:
            response = await call_next(request)
        except Exception:
            await structlog.stdlib.get_logger("api.error").aexception(
                "Uncaught exception"
            )
            # If the call_next raises an error, we still want to log this as a 500
            response = Response(status_code=500)
            raise
        finally:
            process_time = time.perf_counter_ns() - start_time
            status_code = response.status_code
            url = str(
                f"""{request.url.path}{"".join(["?", str(request.query_params)]) if request.query_params else ""}"""
            )
            client_host = request.client.host if request.client else "unknown"
            client_port = request.client.port if request.client else 0
            http_method = request.method
            http_version = request.scope["http_version"]
            # Recreate the Uvicorn access log format, but add all parameters as
            # structured information
            if not request.url.path.startswith(self.ignore_prefix):
                await self.access_logger.ainfo(
                    f"""{client_host}:{client_port} - "{http_method} {url} HTTP/{http_version}" {status_code}""",  # noqa: G004 # There is little chance we want to silence this logger
                    http={
                        "url": str(request.url),
                        "status_code": status_code,
                        "method": http_method,
                        "request_id": request_id,
                        "version": http_version,
                    },
                    network={"client": {"ip": client_host, "port": client_port}},
                    duration=process_time,
                )

        response.headers["X-Process-Time"] = str(process_time / 10**9)
        return response
