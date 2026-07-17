from starlette.responses import Response

SECURE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    ),
}


def apply_security_headers(response: Response) -> Response:
    for header, value in SECURE_HEADERS.items():
        response.headers.setdefault(header, value)
    return response
