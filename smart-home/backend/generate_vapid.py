"""Generate VAPID keys once; copy BOTH into backend/.env, never commit that file."""
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def base64url(blob: bytes) -> str:
    return base64.urlsafe_b64encode(blob).decode().rstrip("=")


def main():
    key = ec.generate_private_key(ec.SECP256R1())
    public_key = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    private_der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    print("Copy into backend/.env and keep private key secret:")
    print("VAPID_PUBLIC_KEY=" + base64url(public_key))
    print("VAPID_PRIVATE_KEY=" + base64url(private_der))
    print("VAPID_SUBJECT=mailto:you@example.com")


if __name__ == "__main__":
    main()
