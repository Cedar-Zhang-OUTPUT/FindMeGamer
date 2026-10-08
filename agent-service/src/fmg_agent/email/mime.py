"""One MIME representation for SMTP and Graph, including reply correlation."""

from base64 import b64decode
from email.message import EmailMessage
from email.utils import formatdate

from .sending import email_address


def build_message(message, message_id):
    sender = email_address(message["from"])
    recipient = email_address(message["to"])
    mail = EmailMessage()
    mail["From"] = sender
    mail["To"] = recipient
    mail["Subject"] = message["subject"]
    mail["Date"] = formatdate(localtime=False)
    mail["Message-ID"] = f'<fmg-{message_id}@{sender.split("@", 1)[1]}>'
    mail.set_content(message["text"])
    if message.get("format") == "signature_image":
        mail.add_alternative(message["html"], subtype="html")
        mail.get_payload()[-1].add_related(
            b64decode(message["signature_png_base64"], validate=True),
            maintype="image",
            subtype="png",
            cid="<ontology-play-signature>",
            disposition="inline",
            filename="ontology-play.png",
        )
    return mail
