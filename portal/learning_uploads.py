"""Bound multipart uploads while streaming, including before CSRF parsing."""

from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.db import transaction


def delete_files_after_commit(files):
    # A locked file (for example an active Windows download) must never turn a
    # successful database commit into a failed upload or delete the new file.
    for storage, name in files:
        transaction.on_commit(lambda storage=storage, name=name: storage.delete(name), robust=True)


class LimitedUploadHandler(FileUploadHandler):
    def __init__(self, request=None):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > settings.LEARNING_FILE_MAX_BYTES:
            self.request.learning_upload_too_large = True
            raise StopUpload(connection_reset=False)
        return raw_data

    def file_complete(self, file_size):
        return None
