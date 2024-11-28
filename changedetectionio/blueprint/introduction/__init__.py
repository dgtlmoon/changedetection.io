from flask import Blueprint, render_template, send_from_directory, flash, url_for, redirect, abort, request

from changedetectionio.blueprint.introduction import forms
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    introduction_blueprint = Blueprint('introduction', __name__, template_folder="templates")

    @login_optionally_required
    @introduction_blueprint.route("/setup", methods=['GET'])
    def index():
        from zoneinfo import available_timezones
        form = forms.IntroductionSettings()
        output = render_template("introduction.html",
                                 available_timezones=sorted(available_timezones()),
                                 form=form
                                 )

        return output

    @login_optionally_required
    @introduction_blueprint.route("/", methods=['POST'])
    def index_post():
        form = forms.IntroductionSettings(formdata=request.form)

        if form.validate():
            datastore.data['settings']['application']['timezone'] = form.data.get('default_timezone')
            flash("Updated!")
            return redirect(url_for("index"))
        else:
            flash("The timezone not is not valid, enter a valid timezone name.", "error")
            return redirect(url_for('introduction.index'))

    return introduction_blueprint
