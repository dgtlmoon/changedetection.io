
from distutils.util import strtobool
from flask import Blueprint, request, make_response
from flask_login import login_required
import os
import logging
from changedetectionio.store import ChangeDetectionStore



def construct_blueprint(datastore: ChangeDetectionStore):

    browser_steps_blueprint = Blueprint('browser_steps', __name__, template_folder="templates")

    @login_required
    @browser_steps_blueprint.route("/extract-regex", methods=['POST'])
    def browsersteps_ui_update():
        import time

        return {123123123: 'yup'}

    return browser_steps_blueprint


