"""Loopback-only SMTP inbox and isolated worker runner for acceptance QA."""
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
import json
from pathlib import Path
import socketserver
import threading

TEST_INBOX = 'acceptance@silent-space.test'


class SMTPHandler(socketserver.StreamRequestHandler):
    def reply(self, message):
        self.wfile.write((message+'\r\n').encode('ascii'))
        self.wfile.flush()

    def handle(self):
        self.request.settimeout(10)
        recipients = []
        self.reply('220 localhost Silent Space acceptance capture')
        while True:
            line = self.rfile.readline(65537)
            if not line:
                return
            command = line.decode('ascii', errors='replace').strip()
            verb = command.split(' ', 1)[0].upper()
            if verb in ('EHLO', 'HELO'):
                self.reply('250-localhost\r\n250 SIZE 1048576')
            elif verb == 'MAIL':
                recipients = []
                self.reply('250 OK')
            elif verb == 'RCPT':
                address = command.partition('<')[2].partition('>')[0].lower()
                if address != TEST_INBOX:
                    self.reply('550 This capture accepts the configured test inbox only')
                else:
                    recipients.append(address)
                    self.reply('250 OK')
            elif verb == 'DATA':
                if self.server.reject_deliveries:
                    self.reply('451 Controlled acceptance test outage')
                    continue
                if not recipients:
                    self.reply('554 No test recipient')
                    continue
                self.reply('354 End data with <CRLF>.<CRLF>')
                body = []
                while True:
                    part = self.rfile.readline(65537)
                    if part == b'.\r\n':
                        break
                    if not part:
                        return
                    body.append(part[1:] if part.startswith(b'..') else part)
                message = BytesParser(policy=policy.default).parsebytes(b''.join(body))
                with self.server.inbox_lock:
                    self.server.messages.append(message)
                self.reply('250 Captured in test inbox')
            elif verb == 'QUIT':
                self.reply('221 Bye')
                return
            elif verb in ('RSET', 'NOOP'):
                self.reply('250 OK')
            else:
                self.reply('502 Unsupported command')


class CaptureServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self):
        self.messages = []
        self.reject_deliveries = False
        self.inbox_lock = threading.Lock()
        super().__init__(('127.0.0.1', 0), SMTPHandler)

    def matching(self, prefix, reference):
        with self.inbox_lock:
            return [message for message in self.messages if
                    str(message['Subject']).startswith(prefix+':') and str(reference) in str(message['Subject'])]


@contextmanager
def smtp_capture():
    server = CaptureServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def run_worker(config_path):
    """Run the real management command against a private database/configuration."""
    import os
    os.environ['DJANGO_SETTINGS_MODULE'] = 'silent_space.settings'
    from django.conf import settings
    config = json.loads(Path(config_path).read_text())
    settings.DATABASES['default']['NAME'] = config['database']
    settings.EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    settings.EMAIL_HOST = '127.0.0.1'
    settings.EMAIL_PORT = config['smtp_port']
    settings.EMAIL_HOST_USER = ''
    settings.EMAIL_HOST_PASSWORD = ''
    settings.EMAIL_USE_TLS = False
    settings.EMAIL_USE_SSL = False
    settings.EMAIL_TIMEOUT = 5
    settings.DEFAULT_FROM_EMAIL = 'cafe@silent-space.test'
    settings.STAFF_NOTIFICATION_RECIPIENTS = [TEST_INBOX]
    settings.SITE_BASE_URL = config['base_url']
    settings.ORDER_REMINDER_MINUTES = config.get('order_minutes', 10)
    settings.RESERVATION_REMINDER_MINUTES = config.get('reservation_minutes', 60)
    settings.NOTIFICATION_MAX_ATTEMPTS = 2
    settings.NOTIFICATION_RETRY_SECONDS = 1
    import django
    django.setup()
    from django.core.management import call_command
    from django.utils import timezone
    from unittest.mock import patch
    from datetime import datetime
    if config.get('now'):
        with patch('notifications.services.timezone.now', return_value=datetime.fromisoformat(config['now'])):
            call_command('process_notifications', limit=100)
    else:
        call_command('process_notifications', limit=100)
    if config.get('marker'):
        Path(config['marker']).write_text(json.dumps({'executed_at': timezone.now().isoformat()}))
