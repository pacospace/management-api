#!/usr/bin/env python3
# Stub
# Copyright(C) 2019 Christoph Görn
#
# This program is free software: you can redistribute it and / or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""Thoth Management API entrypoint."""


import os
import sys
import logging
from datetime import datetime

import connexion
from connexion.resolver import RestyResolver

from flask import redirect, jsonify
from flask_script import Manager
from prometheus_flask_exporter import PrometheusMetrics

from thoth.common import datetime2datetime_str
from thoth.common import init_logging
from thoth.management_api import __version__
from thoth.management_api.configuration import Configuration
from thoth.management_api.configuration import init_jaeger_tracer


# Configure global application logging using Thoth's init_logging.
init_logging(logging_env_var_start="THOTH_MANAGEMENT_API_LOG_")

_LOGGER = logging.getLogger("thoth.management_api")
_LOGGER.setLevel(logging.DEBUG if bool(int(os.getenv("THOTH_MANAGEMENT_API_DEBUG", 0))) else logging.INFO)

_LOGGER.info(f"This is Management API v%s", __version__)
_LOGGER.debug("DEBUG mode is enabled!")

# Expose for uWSGI.
app = connexion.FlaskApp(__name__, specification_dir=Configuration.SWAGGER_YAML_PATH, debug=True)

app.add_api(
    "openapi.yaml",
    options={"swagger_ui": True},
    arguments={"title": "Management API"},
    resolver=RestyResolver("thoth.management_api"),
    strict_validation=True,
    validate_responses=False,
)


application = app.app


# create tracer and put it in the application configuration
Configuration.tracer = init_jaeger_tracer("management_api")

# create metrics and manager
metrics = PrometheusMetrics(application)
manager = Manager(application)

# Needed for session.
application.secret_key = Configuration.APP_SECRET_KEY

# static information as metric
metrics.info("management_api_info", "Management API info", version=__version__)


@app.route("/")
@metrics.do_not_track()
def base_url():
    """Redirect to UI by default."""
    return redirect("api/v1/ui")


@app.route("/api/v1")
@metrics.do_not_track()
def api_v1():
    """Provide a listing of all available endpoints."""
    paths = []

    for rule in application.url_map.iter_rules():
        rule = str(rule)
        if rule.startswith("/api/v1"):
            paths.append(rule)

    return jsonify({"paths": paths})


def _healthiness():
    return jsonify({"status": "ready", "version": __version__}), 200, {"ContentType": "application/json"}


@app.route("/readiness")
@metrics.do_not_track()
def api_readiness():
    """Report readiness for OpenShift readiness probe."""
    return _healthiness()


@app.route("/liveness")
@metrics.do_not_track()
def api_liveness():
    """Report liveness for OpenShift readiness probe."""
    return _healthiness()


@application.errorhandler(404)
@metrics.do_not_track()
def page_not_found(exc):
    """Adjust 404 page to be consistent with errors reported back from API."""
    # Flask has a nice error message - reuse it.
    return jsonify({"error": str(exc)}), 404


@application.errorhandler(500)
@metrics.do_not_track()
def internal_server_error(exc):
    """Adjust 500 page to be consistent with errors reported back from API."""
    # Provide some additional information so we can easily find exceptions in logs (time and exception type).
    # Later we should remove exception type (for security reasons).
    return (
        jsonify(
            {
                "error": "Internal server error occurred, please contact administrator with provided details.",
                "details": {"type": exc.__class__.__name__, "datetime": datetime2datetime_str(datetime.utcnow())},
            }
        ),
        500,
    )


if __name__ == "__main__":
    app.run()

    Configuration.tracer.close()

    sys.exit(1)
