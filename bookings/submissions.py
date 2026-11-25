"""Session-bound, signed submission keys; customer status references never change."""
from uuid import UUID, uuid4
from django.core import signing
from django.utils.crypto import salted_hmac

SALT = 'reservation-submission-v1'
SESSION_KEY = 'reservation_submission_key'


def browser_binding(request):
    # Never expose the actual session cookie value in a hidden form field.
    return salted_hmac(SALT, request.session.session_key or '').hexdigest()


def new_submission_token(request):
    if not request.session.session_key:
        request.session.create()
    key = str(uuid4())
    request.session[SESSION_KEY] = key
    return signing.dumps({'key': key, 'session': browser_binding(request)}, salt=SALT)


def submission_key(request):
    token = request.POST.get('submission_token', '')
    if token:
        expired = False
        try:
            payload = signing.loads(token, salt=SALT, max_age=86400)
        except signing.SignatureExpired:
            # An already-saved request stays idempotent even after the form's creation window.
            payload = signing.loads(token, salt=SALT)
            expired = True
        if not isinstance(payload, dict) or payload.get('session') != browser_binding(request):
            raise signing.BadSignature('This form belongs to another browser session.')
        key = UUID(payload['key'])
        if expired:
            from .models import ReservationRequest
            if not ReservationRequest.objects.filter(submission_key=key).exists():
                raise signing.SignatureExpired('The unsent booking form expired.')
        return key
    # Support old open forms/direct clients, with repeat protection in the same session.
    if not request.session.session_key:
        request.session.create()
    key = request.session.get(SESSION_KEY)
    if not key:
        key = str(uuid4())
        request.session[SESSION_KEY] = key
    return UUID(key)
