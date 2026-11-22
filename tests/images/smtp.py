"""Minimal local SMTP backend that delivers accepted mail to Dovecot over LMTP."""
from smtplib import LMTP
from socketserver import StreamRequestHandler, ThreadingTCPServer


class SMTP(StreamRequestHandler):
    def reply(self, line):
        self.wfile.write(line + b"\r\n")

    def handle(self):
        self.request.settimeout(10)
        self.reply(b"220 smtp.example.org test SMTP")
        for line in self.rfile:
            command = line.rstrip(b"\r\n").partition(b" ")[0].upper()
            if command == b"XCLIENT":
                self.reply(b"220 smtp.example.org test SMTP")
            elif command in (b"EHLO", b"HELO", b"MAIL", b"RCPT", b"RSET"):
                self.reply(b"250 OK")
            elif command == b"DATA":
                self.reply(b"354 End with a dot")
                message = []
                for part in self.rfile:
                    if part == b".\r\n":
                        break
                    message.append(part[1:] if part.startswith(b"..") else part)
                with LMTP("imap", 2525, timeout=5) as lmtp:
                    lmtp.sendmail("sender@example.org", ["alice@example.org"], b"".join(message))
                self.reply(b"250 Delivered to fixture mailbox")
            elif command == b"QUIT":
                self.reply(b"221 Bye")
                return
            else:
                self.reply(b"502 Unknown command")


with ThreadingTCPServer(("", 25), SMTP) as server:
    server.serve_forever()
