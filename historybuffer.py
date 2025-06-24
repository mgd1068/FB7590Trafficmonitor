# historybuffer.py
from collections import deque

class HistoryBuffer:
    def __init__(self, maxlen=360):
        self.maxlen = maxlen
        self.download = deque(maxlen=maxlen)
        self.upload = deque(maxlen=maxlen)

    def append(self, dl, ul):
        self.download.append(dl)
        self.upload.append(ul)

    def get(self):
        return list(self.download), list(self.upload)

    def clear(self):
        self.download.clear()
        self.upload.clear()
