# -*- coding: utf-8 -*-
# Subdivx.com subtitles, based on a mod of Undertext subtitles
# Adaptation: enric_godes@hotmail.com | Please use email address for your
# comments
# Port to XBMC 13 Gotham subtitles infrastructure: cramm, Mar 2014
# Port to Kodi 19 Matrix/Python 3: pedrochiuaua, cramm, 2021-2022
# Update to Feb 2024 reengineering of subdivx.com site, cramm & srprogrammer

import sys

import xbmc
import xbmcaddon
import xbmcvfs

from libs.main import action_download, action_search
from libs.utils import get_params

__version__ = "0.4.1"


def main():
    """Main entry point of the script when it is invoked by Kodi."""
    params = get_params(sys.argv)
    action = params.get("action", "Unknown")
    xbmc.log("SUBDIVX - Version: %s -- Action: %s" % (__version__, action), level=xbmc.LOGINFO)

    if action in ("search", "manualsearch"):
        action_search()
    elif action == "download":
        action_download()


if __name__ == "__main__":
    main()
