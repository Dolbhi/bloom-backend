class ApiTrailingSlashMiddleware:
    """
    API routes are defined WITHOUT a trailing slash (/api/v1/plants/search).
    This makes /api/v1/plants/search/ work too, so the mobile app can use either style.
    (Django's APPEND_SLASH redirect can't do this for POST requests.)
    """

    PREFIX = "/api/v1/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if path.startswith(self.PREFIX) and path.endswith("/") and len(path) > len(self.PREFIX):
            request.path_info = path.rstrip("/")
        return self.get_response(request)
