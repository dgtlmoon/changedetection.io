from flask import Blueprint, request, redirect, url_for, flash, render_template
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio import worker_handler
from changedetectionio.blueprint.imports.importer import (
    import_url_list, 
    import_distill_io_json, 
    import_xlsx_wachete, 
    import_xlsx_custom
)

def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData):
    import_blueprint = Blueprint('imports', __name__, template_folder="templates")
    
    @import_blueprint.route("/import", methods=['GET', 'POST'])
    @login_optionally_required
    def import_page():
        remaining_urls = []
        from changedetectionio import forms

        if request.method == 'POST':
            # URL List import
            if request.values.get('urls') and len(request.values.get('urls').strip()):
                # Import and push into the queue for immediate update check
                importer_handler = import_url_list()
                importer_handler.run(data=request.values.get('urls'), flash=flash, datastore=datastore, processor=request.values.get('processor', 'text_json_diff'))
                for uuid in importer_handler.new_uuids:
                    worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

                if len(importer_handler.remaining_data) == 0:
                    return redirect(url_for('watchlist.index'))
                else:
                    remaining_urls = importer_handler.remaining_data

            # Distill.io import
            if request.values.get('distill-io') and len(request.values.get('distill-io').strip()):
                # Import and push into the queue for immediate update check
                d_importer = import_distill_io_json()
                d_importer.run(data=request.values.get('distill-io'), flash=flash, datastore=datastore)
                for uuid in d_importer.new_uuids:
                    worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

            # XLSX importer
            if request.files and request.files.get('xlsx_file'):
                file = request.files['xlsx_file']

                if request.values.get('file_mapping') == 'wachete':
                    w_importer = import_xlsx_wachete()
                    w_importer.run(data=file, flash=flash, datastore=datastore)
                else:
                    w_importer = import_xlsx_custom()
                    # Building mapping of col # to col # type
                    map = {}
                    for i in range(10):
                        c = request.values.get(f"custom_xlsx[col_{i}]")
                        v = request.values.get(f"custom_xlsx[col_type_{i}]")
                        if c and v:
                            map[int(c)] = v

                    w_importer.import_profile = map
                    w_importer.run(data=file, flash=flash, datastore=datastore)

                for uuid in w_importer.new_uuids:
                    worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

        # Could be some remaining, or we could be on GET
        form = forms.importForm(formdata=request.form if request.method == 'POST' else None)
        output = render_template("import.html",
                                form=form,
                                import_url_list_remaining="\n".join(remaining_urls),
                                original_distill_json=''
                                )
        return output

    return import_blueprint