"""Endpoints related to health."""

from enum import Enum

from fastapi import APIRouter
from pydantic import BaseModel
from starlette import status

health_api_prefix = "/health"

router = APIRouter(prefix=health_api_prefix, tags=["health_check"])


class HealthStatus(str, Enum):
    """Possible health states this service can be in."""

    UP = "UP"
    DOWN = "DOWN"


class HealthCheck(BaseModel):
    """Response model to validate and return when performing a health check."""

    status: HealthStatus = HealthStatus.DOWN


@router.get(
    "/liveness",
    tags=["liveness"],
    summary="Perform a Liveness Health Check",
    response_description="Return HTTP Status Code 200 (OK)",
    status_code=status.HTTP_200_OK,
)
def get_liveness() -> HealthCheck:
    """
    Liveness health check endpoint.

    Endpoint to perform a liveness health check. This endpoint is used to check if the
    service is up and running. Do NOT add any dependencies to this endpoint. When this
    endpoint fails, Kubernetes will restart the service.

    Returns
    -------
        HealthCheck: Returns a JSON response with the liveness status

    """
    return HealthCheck(status=HealthStatus.UP)


@router.get(
    "/readiness",
    tags=["readiness"],
    summary="Perform a Readiness Health Check",
    response_description="Return HTTP Status Code 200 (OK)",
    status_code=status.HTTP_200_OK,
)
def get_readiness() -> HealthCheck:
    """
    Readiness health check endpoint.

    Endpoint to perform a readiness health check. This endpoint is used to check if the
    service is ready to accept traffic. It can for example be used to check if all
    required dependencies (e.g. the database) of the service are up and running. If
    not, Kubernetes will not send traffic to the service, but will NOT restart it and
    will wait until the service is ready again.

    Returns
    -------
        HealthCheck: Returns a JSON response with the readiness status

    """
    return HealthCheck(status=HealthStatus.UP)
