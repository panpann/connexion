import json

from .utils import decode, encode


class ConnexionRequest(object):
    def __init__(self,
                 url,
                 method,
                 path_params=None,
                 query=None,
                 headers=None,
                 form=None,
                 body=None,
                 json_getter=None,
                 files=None,
                 context=None):
        self.url = url
        self.method = method
        self.path_params = path_params or {}
        self.query = query or {}
        self.headers = headers or {}
        self.form = form or {}
        self.body = body
        self.json_getter = json_getter
        self.files = files
        self.context = context if context is not None else {}

    @property
    def json(self):
        return self.json_getter()


class ConnexionResponse(object):
    def __init__(self,
                 status_code=200,
                 mimetype=None,
                 content_type=None,
                 body=None,
                 headers=None):
        if not isinstance(status_code, int) or not (100 <= status_code <= 505):
            raise ValueError("{} is not a valid status code".format(status_code))
        self.status_code = status_code
        self.mimetype = mimetype
        self.body = body
        self.headers = headers or {}
        self.content_type = content_type or self.headers.get("Content-Type")

    @property
    def text(self):
        """return a decoded version of body."""
        return decode(self.body)

    @property
    def json(self):
        """Return JSON decoded body.

        This method is naive, it will try to load JSON even
        if the content_type is not JSON.
        It will raise in case of a non JSON string
        """
        return json.loads(self.text)

    @property
    def data(self):
        """return the encoded body."""
        return encode(self.body)

    @property
    def content_length(self):
        """return the content length.

        If Content-Length is not present in headers,
        get the size of encoded body.
        """
        return int(self.headers.get("Content-Length", len(self.data)))
