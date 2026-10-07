import hashlib
import unicodedata

from app.core.config import settings


async def sign_args(*args):
    """Sign arguments using the signing key"""
    s = settings.signing_key + ':' + '-'.join(str(a) for a in args if a)
    return hashlib.sha1(s.encode()).hexdigest()


def get_bearer(auth: str):
    """Extract bearer token from Authorization header"""
    try:
        return auth.split(' ')[1]
    except (AttributeError, IndexError):
        return None


def sanitise_string(input_string: str) -> str:
    """
    Sanitises the input string:
    - Convert to ASCII
    - Convert spaces to hyphens
    - Remove characters that aren't alphanumerics, underscores, or hyphens
    - Convert to lowercase
    - Strip leading and trailing whitespace
    """
    # Convert to ASCII
    ascii_string = unicodedata.normalize('NFKD', input_string).encode('ascii', 'ignore').decode()

    # Convert spaces to hyphens and strip leading/trailing whitespace
    hyphenated_string = ascii_string.replace(' ', '-').strip()

    # Remove characters that aren't alphanumerics, underscores, or hyphens
    sanitized_string = ''.join(char for char in hyphenated_string if char.isalnum() or char in ['_', '-'])

    # Convert to lowercase
    return sanitized_string.lower()
