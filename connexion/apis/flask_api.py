import logging

import flask
import six
import werkzeug.exceptions
from werkzeug.local import LocalProxy

from connexion.apis import flask_utils
from connexion.apis.abstract import AbstractAPI
from connexion.handlers import AuthErrorHandler
from connexion.lifecycle import ConnexionRequest, ConnexionResponse
from connexion.operations.validation import validate_operation_output
from connexion.utils import Jsonifier

logger = logging.getLogger('connexion.apis.flask_api')


class FlaskApi(AbstractAPI):

    def _set_base_path(self, base_path):
        super(FlaskApi, self)._set_base_path(base_path)
        self._set_blueprint()

    def _set_blueprint(self):
        logger.debug('Creating API blueprint: %s', self.base_path)
        endpoint = flask_utils.flaskify_endpoint(self.base_path)
        self.blueprint = flask.Blueprint(endpoint, __name__, url_prefix=self.base_path,
                                         template_folder=str(self.options.openapi_console_ui_from_dir))

    def add_openapi_json(self):
        """
        Adds spec json to {base_path}/swagger.json
        or {base_path}/openapi.json (for oas3)
        """
        logger.debug('Adding spec json: %s/%s', self.base_path,
                     self.options.openapi_spec_path)
        endpoint_name = "{name}_openapi_json".format(name=self.blueprint.name)
        self.blueprint.add_url_rule(self.options.openapi_spec_path,
                                    endpoint_name,
                                    lambda: flask.jsonify(self.specification.raw))

    def add_swagger_ui(self):
        """
        Adds swagger ui to {base_path}/ui/
        """
        console_ui_path = self.options.openapi_console_ui_path.strip('/')
        logger.debug('Adding swagger-ui: %s/%s/',
                     self.base_path,
                     console_ui_path)

        static_endpoint_name = "{name}_swagger_ui_static".format(name=self.blueprint.name)
        static_files_url = '/{console_ui_path}/<path:filename>'.format(
            console_ui_path=console_ui_path)

        self.blueprint.add_url_rule(static_files_url,
                                    static_endpoint_name,
                                    self._handlers.console_ui_static_files)

        index_endpoint_name = "{name}_swagger_ui_index".format(name=self.blueprint.name)
        console_ui_url = '/{swagger_url}/'.format(
            swagger_url=self.options.openapi_console_ui_path.strip('/'))

        self.blueprint.add_url_rule(console_ui_url,
                                    index_endpoint_name,
                                    self._handlers.console_ui_home)

    def add_auth_on_not_found(self, security, security_definitions):
        """
        Adds a 404 error handler to authenticate and only expose the 404 status if the security validation pass.
        """
        logger.debug('Adding path not found authentication')
        not_found_error = AuthErrorHandler(self, werkzeug.exceptions.NotFound(), security=security,
                                           security_definitions=security_definitions)
        endpoint_name = "{name}_not_found".format(name=self.blueprint.name)
        self.blueprint.add_url_rule('/<path:invalid_path>', endpoint_name, not_found_error.function)

    def _add_operation_internal(self, method, path, operation):
        operation_id = operation.operation_id
        logger.debug('... Adding %s -> %s', method.upper(), operation_id,
                     extra=vars(operation))

        flask_path = flask_utils.flaskify_path(path, operation.get_path_parameter_types())
        endpoint_name = flask_utils.flaskify_endpoint(operation.operation_id,
                                                      operation.randomize_endpoint)
        function = operation.function
        self.blueprint.add_url_rule(flask_path, endpoint_name, function, methods=[method])

    @property
    def _handlers(self):
        # type: () -> InternalHandlers
        if not hasattr(self, '_internal_handlers'):
            self._internal_handlers = InternalHandlers(self.base_path, self.options)
        return self._internal_handlers

    @classmethod
    def get_response(cls, response, mimetype=None, request=None):
        """Gets ConnexionResponse instance for the operation handler
        result. Status Code and Headers for response.  If only body
        data is returned by the endpoint function, then the status
        code will be set to 200 and no headers will be added.

        If the returned object is a flask.Response then it will just
        pass the information needed to recreate it.

        :type operation_handler_result: flask.Response | (flask.Response, int) | (flask.Response, int, dict)
        :rtype: ConnexionRequest
        """
        logger.debug('Getting data and status code',
                     extra={
                         'data': response,
                         'data_type': type(response),
                         'url': flask.request.url
                     })

        if isinstance(response, ConnexionResponse):
            flask_response = cls._get_flask_response_from_connexion(response, mimetype)
        else:
            flask_response = cls._response_from_handler(response, mimetype)

        logger.debug('Got data and status code (%d)',
                     flask_response.status_code,
                     extra={
                         'data': response,
                         'datatype': type(response),
                         'url': flask.request.url
                     })

        return flask_response

    @classmethod
    def _get_flask_response_from_connexion(cls, response, mimetype):
        data = response.body
        status_code = response.status_code
        mimetype = response.mimetype or mimetype
        content_type = response.content_type or mimetype
        headers = response.headers

        flask_response = cls._build_flask_response(mimetype, content_type,
                                                   headers, status_code, data)

        return flask_response

    @classmethod
    def _build_flask_response(cls, mimetype=None, content_type=None,
                              headers=None, status_code=None, data=None):
        kwargs = {
            'mimetype': mimetype,
            'content_type': content_type,
            'headers': headers
        }
        kwargs = {k: v for k, v in six.iteritems(kwargs) if v is not None}
        flask_response = flask.current_app.response_class(**kwargs)  # type: flask.Response

        if status_code is not None:
            flask_response.status_code = status_code

        data = cls.encode_body(data, mimetype)
        flask_response.set_data(data)

        return flask_response

    @classmethod
    def _response_from_handler(cls, response, mimetype):
        """Create a framework response from the operation handler data.

        Handle all cases describe in `AbstractApi.get_response`.
        """
        if flask_utils.is_flask_response(response):
            return response
        elif isinstance(response, tuple) and flask_utils.is_flask_response(response[0]):
            return flask.current_app.make_response(response)

        body, status_code, headers = validate_operation_output(response)

        return cls._build_flask_response(
            mimetype=mimetype,
            headers=headers,
            status_code=status_code,
            data=body
        )

    @classmethod
    def get_connexion_response(cls, response, mimetype=None):
        if isinstance(response, ConnexionResponse):
            return response

        if not isinstance(response, flask.current_app.response_class):
            response = cls.get_response(response, mimetype)

        return ConnexionResponse(
            status_code=response.status_code,
            mimetype=response.mimetype,
            content_type=response.content_type,
            headers=response.headers,
            body=response.get_data(),
        )

    @classmethod
    def get_request(cls, *args, **params):
        # type: (*Any, **Any) -> ConnexionRequest
        """Gets ConnexionRequest instance for the operation handler
        result. Status Code and Headers for response.  If only body
        data is returned by the endpoint function, then the status
        code will be set to 200 and no headers will be added.

        If the returned object is a flask.Response then it will just
        pass the information needed to recreate it.

        :rtype: ConnexionRequest
        """
        context_dict = {}
        setattr(flask._request_ctx_stack.top, 'connexion_context', context_dict)
        flask_request = flask.request
        request = ConnexionRequest(
            flask_request.url,
            flask_request.method,
            headers=flask_request.headers,
            form=flask_request.form,
            query=flask_request.args,
            body=flask_request.get_data(),
            json_getter=lambda: flask_request.get_json(silent=True),
            files=flask_request.files,
            path_params=params,
            context=context_dict
        )
        logger.debug('Getting data and status code',
                     extra={
                         'data': request.body,
                         'data_type': type(request.body),
                         'url': request.url
                     })
        return request

    @classmethod
    def _set_jsonifier(cls):
        """
        Use Flask specific JSON loader
        """
        cls.jsonifier = Jsonifier(flask.json)


def _get_context():
    return getattr(flask._request_ctx_stack.top, 'connexion_context')


context = LocalProxy(_get_context)


class InternalHandlers(object):
    """
    Flask handlers for internally registered endpoints.
    """

    def __init__(self, base_path, options):
        self.base_path = base_path
        self.options = options

    def console_ui_home(self):
        """
        Home page of the OpenAPI Console UI.

        :return:
        """
        return flask.render_template(
            'index.j2',
            openapi_spec_url=(self.base_path + self.options.openapi_spec_path)
        )

    def console_ui_static_files(self, filename):
        """
        Servers the static files for the OpenAPI Console UI.

        :param filename: Requested file contents.
        :return:
        """
        # convert PosixPath to str
        static_dir = str(self.options.openapi_console_ui_from_dir)
        return flask.send_from_directory(static_dir, filename)
