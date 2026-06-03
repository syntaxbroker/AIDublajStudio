from fastapi import status

from app.schemas.common import ApiErrorResponse


COMMON_ERROR_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {"model": ApiErrorResponse, "description": "Bad request"},
    status.HTTP_401_UNAUTHORIZED: {"model": ApiErrorResponse, "description": "Unauthorized"},
    status.HTTP_403_FORBIDDEN: {"model": ApiErrorResponse, "description": "Forbidden"},
    status.HTTP_404_NOT_FOUND: {"model": ApiErrorResponse, "description": "Not found"},
    status.HTTP_409_CONFLICT: {"model": ApiErrorResponse, "description": "Conflict"},
    status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ApiErrorResponse, "description": "Validation error"},
    status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ApiErrorResponse, "description": "Internal server error"},
}
