import logging
import os
import os.path
import shutil
from json import loads
from os.path import join as pjoin
from pprint import pformat
import sys
import tempfile
from unicodedata import normalize
from urllib.parse import quote_plus, unquote, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

try:
    import StorageServer
except Exception:
    import storageserverdummy as StorageServer

from libs.subdivx_api import download_subtitle, search_subtitles
from libs.utils import get_params, log

__all__ = ["action_search", "action_download"]

INTERNAL_LINK_URL_BASE = "plugin://%s/?"


def build_xbmc_item_url(url, item, filename):
    """Return an internal Kodi pseudo-url for the provided sub search result"""
    return url + urlencode((("id", str(item["subdivx_subtitle_id"])), ("filename", filename.encode("utf-8"))))


def build_tvshow_searchstring(item):
    parts = ["%s" % item["tvshow"]]
    try:
        season = int(item["season"])
    except Exception:
        pass
    else:
        parts.append(" S%#02d" % season)
        try:
            episode = int(item["episode"])
        except Exception:
            pass
        else:
            parts.append("E%#02d" % episode)
    return "".join(parts)


def action_search():
    kodi_dir_handle = int(sys.argv[1])
    params = get_params(sys.argv)
    item = {
        "temp": False,
        "rar": False,
        "year": xbmc.getInfoLabel("VideoPlayer.Year"),
        "season": xbmc.getInfoLabel("VideoPlayer.Season"),
        "episode": xbmc.getInfoLabel("VideoPlayer.Episode"),
        "tvshow": normalize("NFKD", xbmc.getInfoLabel("VideoPlayer.TVshowtitle")),
        # Try to get original title
        "title": normalize("NFKD", xbmc.getInfoLabel("VideoPlayer.OriginalTitle")),
        # Full path of a playing file
        "file_original_path": unquote(xbmc.Player().getPlayingFile()),
        "3let_language": [],
        "2let_language": [],
        "manual_search": "searchstring" in params,
    }

    if "searchstring" in params:
        item["manual_search_string"] = params["searchstring"]

    for lang in unquote(params["languages"]).split(","):
        item["3let_language"].append(xbmc.convertLanguage(lang, xbmc.ISO_639_2))
        item["2let_language"].append(xbmc.convertLanguage(lang, xbmc.ISO_639_1))

    if not item["title"]:
        # No original title, get just Title
        item["title"] = normalize("NFKD", xbmc.getInfoLabel("VideoPlayer.Title"))

    if "s" in item["episode"].lower():
        # Check if season is "Special"
        item["season"] = "0"
        item["episode"] = item["episode"][-1:]

    if "http" in item["file_original_path"]:
        item["temp"] = True

    elif "rar://" in item["file_original_path"]:
        item["rar"] = True
        item["file_original_path"] = os.path.dirname(item["file_original_path"][6:])

    elif "stack://" in item["file_original_path"]:
        stackPath = item["file_original_path"].split(" , ")
        item["file_original_path"] = stackPath[0][8:]

    search_and_set_kodi_entries(kodi_dir_handle, item)
    # Send end of directory to Kodi
    xbmcplugin.endOfDirectory(kodi_dir_handle)


def search_and_set_kodi_entries(kodi_dir_handle, item):
    """Called when subtitle search is requested from Kodi.

    Do what's needed to get the list of subtitles from service site
    use item["some_property"] that was set earlier.
    Once done, set xbmcgui.ListItem() below and pass it to
    xbmcplugin.addDirectoryItem()
    """
    addon_obj = xbmcaddon.Addon()
    log("item = %s" % pformat(item))
    file_original_path = item["file_original_path"]

    if item["manual_search"]:
        searchstring = unquote(item["manual_search_string"])
    elif item["tvshow"]:
        searchstring = build_tvshow_searchstring(item)
    else:
        searchstring = "%s%s" % (
            item["title"],
            " (%s)" % item["year"].strip("()") if item.get("year") else "",
        )
    log("Search string = %s" % searchstring)

    cache_ttl_value = addon_obj.getSetting("cache_ttl")
    try:
        cache_ttl = int(cache_ttl_value)
    except Exception:
        cache_ttl = 0
    if cache_ttl:
        cache = StorageServer.StorageServer("service.subtitles.subdivx", cache_ttl / 60.0)
        subtitle_items = cache.cacheFunction(search_subtitles, searchstring, "es", file_original_path)
    else:
        subtitle_items = search_subtitles(searchstring, "es", file_original_path)

    if not subtitle_items:
        log("No subtitle found", level=logging.WARNING)
        return

    # Sort the list putting the best quality entries and the ones with sync=True at the top
    subtitle_items = sorted(subtitle_items, key=lambda s: (s["sync"], s["promedio"], s["downloads"]), reverse=True)
    log("subtitle_items = %s" % pformat(subtitle_items))

    for subtitle_item in subtitle_items:
        # Kodi expects a [0, 5] rating field int value
        subtitle_item["rating"] = int(round((float(subtitle_item["promedio"]))))
        del subtitle_item["promedio"]
        add_xbmc_entry(kodi_dir_handle, subtitle_item, file_original_path)


def add_xbmc_entry(kodi_dir_handle, item, filename):
    addon_obj = xbmcaddon.Addon()
    script_id = addon_obj.getAddonInfo("id")
    if addon_obj.getSetting("show_nick_in_place_of_lang") == "true":
        item_label = item["uploader"]
    else:
        item_label = "Spanish"
    listitem = xbmcgui.ListItem(label=item_label, label2=item["descr"])
    listitem.setArt(
        {
            "icon": str(item["rating"]),
            "thumb": "",
        }
    )
    listitem.setProperty("sync", "true" if item["sync"] else "false")
    listitem.setProperty("hearing_imp", "true" if item.get("hearing_imp", False) else "false")

    # Below arguments are optional, they can be used to pass any info needed in
    # download function. Anything after "action=download&" will be sent to
    # addon once user clicks listed subtitle to download
    url = INTERNAL_LINK_URL_BASE % script_id
    xbmc_url = build_xbmc_item_url(url, item, filename)
    # Add it to list, this can be done as many times as needed for all
    # subtitles found
    xbmcplugin.addDirectoryItem(handle=kodi_dir_handle, url=xbmc_url, listitem=listitem, isFolder=False)


def action_download():
    """Called when subtitle download is requested from Kodi."""
    addon_obj = xbmcaddon.Addon()
    profile_dir = xbmcvfs.translatePath(addon_obj.getAddonInfo("profile"))
    kodi_dir_handle = int(sys.argv[1])
    params = get_params(sys.argv)
    cleanup_tempdirs(profile_dir)
    workdir = tempfile.mkdtemp(dir=profile_dir)
    # Make sure it ends with a path separator (Kodi 14)
    workdir = workdir + os.path.sep
    debug_dump_path(workdir, "workdir")
    # We pickup our arguments sent from the action_search() function
    download_and_set_kodi_entries(kodi_dir_handle, params["id"], profile_dir, workdir)

    sleep(2)
    if addon_obj.getSetting("show_nick_in_place_of_lang") == "true":
        double_dot_fix_hack(params["filename"])
    cleanup_tempdir(workdir, verbose=True)


def download_and_set_kodi_entries(kodi_dir_handle, subdivx_subtitle_id, profile_dir, workdir):
    debug_dump_path(profile_dir, "__profile__")
    xbmcvfs.mkdirs(profile_dir)
    subs = download_subtitle(subdivx_subtitle_id, workdir, uncompress_callback=uncompress_callback)
    # We can return more than one subtitle for multi CD versions, for now
    # we are still working out how to handle that in Kodi core
    for sub in subs:
        # XXX: Kodi still can't handle multiple subtitles files returned
        # from an addon, it will always use the first file returned. So
        # there is no point in reporting a forced subtitle file to it.
        # See https://github.com/ramiro/service.subtitles.subdivx/issues/14
        if sub["forced"]:
            continue
        list_item = xbmcgui.ListItem(label=sub["path"])
        log("Adding entry %s" % sub["path"])
        xbmcplugin.addDirectoryItem(
            handle=kodi_dir_handle,
            url=sub["path"],
            listitem=list_item,
            isFolder=False,
        )
    # Send end of directory to Kodi
    xbmcplugin.endOfDirectory(kodi_dir_handle)


def uncompress_callback(workdir, compressed_file, _):
    src = "archive" + "://" + quote_plus(compressed_file) + "/"
    _, cfiles = xbmcvfs.listdir(src)
    for cfile in cfiles:
        fsrc = "%s%s" % (src, cfile)
        log("Decompressing from %s to %s" % (fsrc, workdir + cfile))
        xbmcvfs.copy(fsrc, workdir + cfile)


def double_dot_fix_hack(video_filename):
    """Corrects filename of downloaded subtitle from Foo-Blah..srt to Foo-Blah.es.srt"""
    log("video_filename = %s" % video_filename)
    work_path = video_filename
    if subtitles_setting("storagemode"):
        custom_subs_path = subtitles_setting("custompath")
        if custom_subs_path:
            _, fname = os.path.split(video_filename)
            work_path = pjoin(custom_subs_path, fname)

    log("work_path = %s" % work_path)
    parts = work_path.rsplit(".", 1)
    if len(parts) > 1:
        rest = parts[0]
        for ext in ("srt", "ssa", "sub", "idx"):
            bad = rest + ".." + ext
            old = rest + ".es." + ext
            if xbmcvfs.exists(bad):
                log("%s exists" % bad)
                if xbmcvfs.exists(old):
                    log("%s exists, removing" % old)
                    xbmcvfs.delete(old)
                log("renaming %s to %s" % (bad, old))
                xbmcvfs.rename(bad, old)


def subtitles_setting(name):
    """
    Uses Kodi JSON-RPC API to retrieve subtitles location settings values.
    """
    command = """{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "Settings.GetSettingValue",
    "params": {
        "setting": "subtitles.%s"
    }
}"""
    result = xbmc.executeJSONRPC(command % name)
    py = loads(result)
    if "result" in py and "value" in py["result"]:
        return py["result"]["value"]
    else:
        raise ValueError


def debug_dump_path(victim, name):
    _type = type(victim)
    log("%s (%s): %s" % (name, _type, victim))


def cleanup_tempdir(dir_path, verbose=False):
    try:
        shutil.rmtree(dir_path, ignore_errors=True)
    except Exception:
        if verbose:
            log("Failed to remove %s" % dir_path, level=logging.WARNING)
        return False
    return True


def cleanup_tempdirs(profile_path):
    dirs, _ = xbmcvfs.listdir(profile_path)
    total, ok = 0, 0
    for total, dir_path in enumerate(dirs[:10]):
        result = cleanup_tempdir(os.path.join(profile_path, dir_path), verbose=False)
        if result:
            ok += 1
    log("Results: %d of %d dirs removed" % (ok, total + 1))


def sleep(secs):
    """Sleeps efficiently for secs seconds"""
    xbmc.Monitor().waitForAbort(secs)
