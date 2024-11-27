import datetime
import glob
import threading

from flask import Blueprint, render_template, send_from_directory, flash, url_for, redirect, abort

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    introduction_blueprint = Blueprint('introduction', __name__, template_folder="templates")

    @login_optionally_required
    @introduction_blueprint.route("/", methods=['GET'])
    def index():
        from zoneinfo import available_timezones
        output = render_template("settings.html",
                                 available_timezones=sorted(available_timezones()),
                                 )

        return output

    return introduction_blueprint
