from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Log in with email + password.

    Patients store their email as the username too, but staff accounts may
    not, so look the user up by email. Anything without an "@" is treated as
    a username, which keeps the Django admin login (username) working.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None

        lookup = {"email__iexact": username} if "@" in username else {"username": username}
        try:
            user = User._default_manager.get(**lookup)
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            # Run the hasher anyway so a missing account takes as long as a wrong password.
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
