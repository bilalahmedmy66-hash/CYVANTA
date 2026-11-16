from google.genai.errors import APIError

from app.ai.service import _is_quota_exhaustion, _is_temporary_provider_failure


def make_error(code=429, status="RESOURCE_EXHAUSTED", message="Provider request failed", details=None):
    return APIError(code, {"error": {
        "code": code, "status": status, "message": message, "details": details or []
    }})


def quota_failure(description, quota_id=""):
    return {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [{
            "subject": "project",
            "description": description,
            "quotaId": quota_id,
        }],
    }


def test_daily_quota_is_detected_as_terminal():
    error = make_error(details=[quota_failure("Daily request quota exceeded", "requestsPerDay")])
    assert _is_quota_exhaustion(error) is True


def test_per_minute_quota_is_retryable_not_terminal():
    error = make_error(details=[quota_failure("Requests per minute quota exceeded", "requestsPerMinute")])
    assert _is_quota_exhaustion(error) is False
    assert _is_temporary_provider_failure(error) is True


def test_ambiguous_resource_exhausted_is_retryable():
    error = make_error(message="Quota exceeded")
    assert _is_quota_exhaustion(error) is False
    assert _is_temporary_provider_failure(error) is True


def test_plain_429_is_retryable():
    error = make_error(message="Too many requests")
    assert _is_quota_exhaustion(error) is False
    assert _is_temporary_provider_failure(error) is True


def test_gateway_timeout_is_retryable():
    error = make_error(504, "GATEWAY_TIMEOUT", "Gateway timeout")
    assert _is_quota_exhaustion(error) is False
    assert _is_temporary_provider_failure(error) is True


def test_service_unavailable_is_retryable():
    error = make_error(503, "UNAVAILABLE", "Service unavailable")
    assert _is_temporary_provider_failure(error) is True


def test_invalid_argument_is_not_retryable():
    error = make_error(400, "INVALID_ARGUMENT", "Invalid request")
    assert _is_quota_exhaustion(error) is False
    assert _is_temporary_provider_failure(error) is False


def test_daily_quota_id_is_detected():
    error = make_error(details=[quota_failure("Quota exceeded", "generateRequestsPerDayPerProject")])
    assert _is_quota_exhaustion(error) is True