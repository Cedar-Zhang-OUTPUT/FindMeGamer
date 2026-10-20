"""One MIME representation for SMTP and Graph, including reply correlation."""

from base64 import b64decode
from email.message import EmailMessage
from email.utils import formatdate, formataddr
from hashlib import sha256

from .sending import email_address


def build_message(message, message_id):
    sender = email_address(message["from"])
    recipient = email_address(message["to"])
    mail = EmailMessage()
    name = message.get("from_name", "")
    if not isinstance(name, str) or any(char in name for char in "\r\n"):
        raise ValueError("Invalid sender display name.")
    mail["From"] = formataddr((name, sender)) if name else sender
    mail["To"] = recipient
    mail["Subject"] = message["subject"]
    mail["Date"] = message.get("_smtp_date") or formatdate(localtime=False)
    mail["Message-ID"] = f'<fmg-{message_id}@{sender.split("@", 1)[1]}>'
    mail.set_content(message["text"])
    if message.get("format") == "signature_image":
        mail.add_alternative(message["html"], subtype="html")
        if message.get("footer_jpeg_base64"):
            mail.get_payload()[-1].add_related(
                b64decode(message["footer_jpeg_base64"], validate=True),
                maintype="image",
                subtype="jpeg",
                cid="<thieves-game-banner>",
                disposition="inline",
                filename="thieves-banner.jpg",
            )
        else:
            mail.get_payload()[-1].add_related(
                b64decode(message["signature_png_base64"], validate=True),
                maintype="image",
                subtype="png",
                cid="<ontology-play-signature>",
                disposition="inline",
                filename="ontology-play.png",
            )
            # Old drafts with only a signature stay unchanged.
            if message.get("footer_png_base64"):
                mail.get_payload()[-1].add_related(
                    b64decode(message["footer_png_base64"], validate=True),
                    maintype="image",
                    subtype="png",
                    cid="<liminal-game-banner>",
                    disposition="inline",
                    filename="liminal-within.png",
                )
    if message.get("_smtp_date"):
        # New SMTP archive-enabled sends use already-durable reservation time
        # and send ID. A repair can reproduce exact bytes without saving another
        # large image in diagnostics or changing the immutable preview.
        seed = sha256(message_id.encode()).hexdigest()[:40]
        for index, part in enumerate(mail.walk()):
            if part.is_multipart():
                part.set_boundary(f"===============fmg-{seed}-{index}==")
    return mail
