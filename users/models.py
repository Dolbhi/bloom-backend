"""
Custom user model, created on day one.

Swapping the user model after the first migration is painful, so it exists now even
though it only adds a few fields. Login is by email; there is no username.
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    use_in_migrations = True

    def normalize_email(self, email):
        return (email or "").strip().lower()

    def get_by_natural_key(self, email):
        # Login (API, admin, createsuperuser) ignores case: Bob@x.com == bob@x.com
        return self.get(email__iexact=email)

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)   # stores a hash, never the raw password
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.ADMIN)
        return self.create_user(email, password, **extra)


class User(AbstractUser):
    class Role(models.TextChoices):
        USER = "user"
        MODERATOR = "moderator"
        ADMIN = "admin"

    username = None                       # remove the username field
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=50, blank=True)
    reputation = models.IntegerField(default=0)   # no lower limit: rejections can push it negative
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        constraints = [
            # Bob@x.com and bob@x.com count as the same email
            models.UniqueConstraint(Lower("email"), name="users_email_lower_uq"),
            models.CheckConstraint(condition=Q(role__in=["user", "moderator", "admin"]), name="users_role_valid"),
        ]

    def __str__(self):
        return self.email

    @property
    def can_moderate(self):
        """Decides who sees the Review tab (UF10): role-based OR reputation-based."""
        if not self.is_active:
            return False
        if self.is_superuser or self.role in (self.Role.MODERATOR, self.Role.ADMIN):
            return True
        threshold = settings.BLOOM["MODERATOR_REPUTATION"]
        return threshold > 0 and self.reputation >= threshold

    @property
    def public_name(self):
        return self.display_name or "Anonymous"
