from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache


def can_view(user, model):
    app, name = model.split('.')
    return user.has_perm(f'{app}.view_{name}') or user.has_perm(f'{app}.change_{name}')


def staff_access(model=None, *, change=False):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path(), 'staff:login')
            if not user.is_active or not user.is_staff:
                raise PermissionDenied
            if model:
                app, name = model.split('.')
                allowed = user.has_perm(f'{app}.change_{name}') if change else can_view(user, model)
                if not allowed:
                    raise PermissionDenied
            return view(request, *args, **kwargs)
        return never_cache(wrapped)
    return decorator
