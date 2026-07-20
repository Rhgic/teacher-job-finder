"""Generate a strong SESSION_SECRET for production .env."""
import secrets

print(secrets.token_urlsafe(48))
