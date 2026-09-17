"""Server-configured SMTP, TLS by default; post-DATA uncertainty is not retried."""

from email.message import EmailMessage
from email.utils import formatdate
import smtplib
import ssl

from .sending import email_address, smtp_ready


def deliver(config, message, message_id):
    if config.smtp_allowed_recipients and message["to"].casefold() not in {
        address.casefold() for address in config.smtp_allowed_recipients
    }:
        return {"state": "failed", "code": "smtp_recipient_not_allowed"}
    if not smtp_ready(config):
        return {"state": "failed", "code": "configuration_missing"}
    connection = None
    attempting_data = False
    try:
        sender = email_address(message["from"])
        recipient = email_address(message["to"])
        mail = EmailMessage()
        mail["From"] = sender
        mail["To"] = recipient
        mail["Subject"] = message["subject"]
        mail["Date"] = formatdate(localtime=False)
        mail["Message-ID"] = f'<fmg-{message_id}@{sender.split("@",1)[1]}>'
        mail.set_content(message["text"])
        mail.add_alternative(message["html"], subtype="html")
        if config.smtp_encryption == "tls":
            connection = smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=10,
                context=ssl.create_default_context(),
            )
        else:
            connection = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10)
            if config.smtp_encryption == "starttls":
                connection.starttls(context=ssl.create_default_context())
        if config.smtp_encryption != "none":
            connection.login(
                config.smtp_username, config.smtp_password.get_secret_value()
            )
        attempting_data = True
        refusals = connection.send_message(mail, from_addr=sender, to_addrs=[recipient])
        if refusals:
            return {"state": "failed", "code": "smtp_recipient_rejected"}
        return {"state": "sent", "code": None}
    except smtplib.SMTPAuthenticationError:
        return {"state": "failed", "code": "smtp_authentication_rejected"}
    except smtplib.SMTPRecipientsRefused:
        return {"state": "failed", "code": "smtp_recipient_rejected"}
    except (smtplib.SMTPResponseException, smtplib.SMTPNotSupportedError):
        # An explicit negative SMTP response is not an ambiguous acceptance.
        return {"state": "failed", "code": "smtp_request_rejected"}
    except Exception:
        return {
            "state": "unknown" if attempting_data else "failed",
            "code": (
                "smtp_confirmation_lost"
                if attempting_data
                else "smtp_connection_failed"
            ),
        }
    finally:
        if connection is not None:
            try:
                connection.quit()
            except Exception:
                pass
            try:
                connection.close()
            except Exception:
                pass
