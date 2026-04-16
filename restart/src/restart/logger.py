import logging
import os
import sys

class DecimatedTimeFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt, datefmt, style)
        self.count = 0

    def formatTime(self, record, datefmt=None):
        self.count += 1
        if self.count % 10 == 1:
            return super().formatTime(record, datefmt)
        return " " * 23

def setup_logger(logfile="restart.log", level_name="INFO"):
    logger = logging.getLogger("restart")
    if logger.handlers:
        return logger

    level = getattr(logging, level_name.upper(), logging.INFO)
    logger.setLevel(level)
    fmt = DecimatedTimeFormatter("%(asctime)s %(levelname)s: %(message)s")

    fh = logging.FileHandler(logfile)
    fh.setFormatter(fmt)
    fh.setLevel(level)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(level)
    logger.addHandler(sh)

    return logger
