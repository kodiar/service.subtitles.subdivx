import logging
from urllib.parse import parse_qs

try:
    import xbmc
except ImportError:

    def log(msg, level=logging.DEBUG):
        logging.log(level, msg)

else:
    import sys

    from xbmc import (  # noqa: F401
        LOGDEBUG,
        LOGINFO,
        LOGWARNING,
        LOGERROR,
        LOGFATAL,
        LOGNONE,
    )

    levels = {
        logging.NOTSET: LOGNONE,
        logging.DEBUG: LOGDEBUG,
        logging.INFO: LOGINFO,
        logging.WARNING: LOGWARNING,
        logging.ERROR: LOGERROR,
        logging.CRITICAL: LOGFATAL,
    }

    def log(msg, level=logging.DEBUG):
        lvl = levels.get(level, LOGDEBUG)
        fname = sys._getframe(1).f_code.co_name
        s = "SUBDIVX - %s: %s" % (fname, msg)
        xbmc.log(s, level=LOGINFO)


def get_params(argv):
    params = {}
    qs = argv[2].lstrip("?")
    if qs:
        if qs.endswith("/"):
            qs = qs[:-1]
        parsed = parse_qs(qs)
        for k, v in parsed.items():
            params[k] = v[0]
    return params
