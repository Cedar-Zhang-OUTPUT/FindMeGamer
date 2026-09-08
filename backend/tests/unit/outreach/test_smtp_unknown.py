import smtplib
import pytest
from app.outreach.smtp import SMTPUnknownOutcome, SMTPPermanentError, SMTPTransientError
from tests.unit.outreach.test_smtp import FakeSMTP, gateway, smtp_config, message


class SubmissionSMTP(FakeSMTP):
    def __init__(self, failure):
        super().__init__()
        self.submission_failure = failure

    def send_message(self, value):
        self.events.append("send")
        raise self.submission_failure


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("private upstream"),
        smtplib.SMTPServerDisconnected("private upstream"),
    ],
)
def test_disconnect_after_submission_is_unknown_and_not_ordinary_retryable(error):
    fake = SubmissionSMTP(error)
    with pytest.raises(SMTPUnknownOutcome) as caught:
        gateway(fake).send(smtp_config(), message())
    assert not isinstance(caught.value, SMTPTransientError)
    assert "private upstream" not in str(caught.value)
    assert fake.events.count("send") == 1 and fake.events[-1] == "close"


@pytest.mark.parametrize(
    "code,kind", [(451, SMTPTransientError), (550, SMTPPermanentError)]
)
def test_explicit_data_rejection_is_known_not_unknown(code, kind):
    fake = SubmissionSMTP(smtplib.SMTPDataError(code, b"private upstream"))
    with pytest.raises(kind):
        gateway(fake).send(smtp_config(), message())
    assert fake.events.count("send") == 1


def test_timeout_before_submission_remains_known_failure():
    fake = FakeSMTP()
    fake.failure = TimeoutError("private upstream")
    with pytest.raises(SMTPTransientError):
        gateway(fake).send(smtp_config(), message())
    assert "send" not in fake.events


def test_legacy_public_projection_preserves_unknown_verification_warning():
    from types import SimpleNamespace
    from app.api.routes.outreach import _smtp_error
    from app.db.models.outreach import DeliverySendState

    result = _smtp_error(
        SimpleNamespace(
            send_state=DeliverySendState.FAILED,
            smtp_error_code="smtp_outcome_unknown",
            smtp_error_message="SMTP submission outcome is unknown. Verify before sending again.",
            smtp_retryable=False,
        )
    )
    assert result is not None
    assert result.model_dump() == {
        "code": "smtp_outcome_unknown",
        "message": "SMTP submission outcome is unknown. Verify before sending again.",
        "retryable": False,
    }
