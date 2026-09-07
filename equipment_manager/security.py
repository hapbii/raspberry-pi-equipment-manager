"""Text comparisons that also support user-chosen Unicode credentials."""
import secrets


def constant_time_equal(supplied: str, expected: str) -> bool:
    # JSON can contain lone surrogates; compare them as bytes instead of raising.
    return secrets.compare_digest(
        supplied.encode("utf-8", errors="surrogatepass"),
        expected.encode("utf-8", errors="surrogatepass"),
    )
