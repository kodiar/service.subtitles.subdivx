import json
import logging
import os
import os.path
from os.path import join as pjoin
import re
import urllib.error
import urllib.request
from urllib.parse import urlencode

import html2text

from libs.utils import log

__all__ = ["download_subtitle", "search_subtitles"]

MAIN_SUBDIVX_URL = "https://www.subdivx.com/"
SEARCH_PAGE_URL = MAIN_SUBDIVX_URL + "inc/ajax.php"
MAX_RESULTS_COUNT = 40
QS_DICT = {
    "tabla": "resultados",
    "filtros": "",
}
QS_KEY_QUERY = "buscar"
PAGE_ENCODING = "utf-8"
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/53.0.2785.21 Safari/537.36"
)
SUB_EXTS = ["SRT", "SUB", "SSA"]
FORCED_SUB_SENTINELS = ["FORZADO", "FORCED"]


def search_subtitles(search_string, language_short, file_orig_path):
    if language_short != "es":
        return []
    qs_dict = QS_DICT.copy()
    qs_dict[QS_KEY_QUERY] = search_string
    content = get_url(SEARCH_PAGE_URL, qs_dict)
    if content is None:
        return []
    try:
        results_data = json.loads(content)
    except Exception as e:
        log(str(e), logging.DEBUG)
        return []
    subtitle_cnt = results_data["iTotalRecords"]
    log("%d subtitles found" % subtitle_cnt)
    if subtitle_cnt < 1 or not len(results_data["aaData"]):
        return []
    subtitle_items = []
    for counter, subtitle_obj in enumerate(results_data["aaData"], 1):
        descr = cleanup_subdivx_comment(subtitle_obj["descripcion"])

        # If our actual video file's name appears in the description
        # then set sync to True because it has better chances of its
        # synchronization to match
        _, fn = os.path.split(file_orig_path)
        name, _ = os.path.splitext(fn)
        sync = re.search(re.escape(name), descr, re.I) is not None

        item = {
            "descr": descr,
            "sync": sync,
            "subdivx_subtitle_id": subtitle_obj["id"],
            "uploader": subtitle_obj["nick"],
            "downloads": subtitle_obj["descargas"],
            "promedio": float(subtitle_obj["promedio"]),
        }
        subtitle_items.append(item)
        if counter == MAX_RESULTS_COUNT:
            break

    return subtitle_items


def get_url(url, query_data=None):
    if query_data is None:
        req = urllib.request.Request(url)
        log("Fetching %s" % url)
    else:
        urlencoded_query_data = urlencode(query_data)
        req = urllib.request.Request(url, data=urlencoded_query_data.encode(PAGE_ENCODING))
        log("Fetching %s POST data: %s" % (url, urlencoded_query_data))
    req.add_header("User-Agent", HTTP_USER_AGENT)
    req.add_header("X-Requested-With", "XMLHttpRequest")
    req.add_header("Referer", "https://www.subdivx.com")
    try:
        response = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        log("Failed to fetch %s (HTTP status: %d)" % (url, e.code), level=logging.WARNING)
        pass
    except urllib.error.URLError as e:
        log("Failed to fetch %s (URL error %s)" % (url, e.reason), level=logging.WARNING)
        pass
    except Exception as e:
        log("Failed to fetch %s (generic error %s)" % (url, e), level=logging.WARNING)
        pass
    else:
        try:
            content = response.read()
        except Exception as e:
            log("Failed to read response content from %s (generic error %s)" % (url, e), level=logging.WARNING)
        else:
            return content
    return None


def cleanup_subdivx_comment(comment):
    """Convert the subtitle comment HTML to plain text."""
    parser = html2text.HTML2Text()
    parser.unicode_snob = True
    parser.ignore_emphasis = True
    parser.ignore_tables = True
    parser.ignore_links = True
    parser.body_width = 1000
    clean_text = parser.handle(comment)
    # Remove new lines manually
    clean_text = re.sub(r"\n", " ", clean_text)
    clean_text = re.sub(r"\s+", " ", clean_text)
    # Misc cleanups
    clean_text = clean_text.replace("=[ TheSubFactory ]=", "TheSubFactory")
    return clean_text.strip(" \t")


def download_subtitle(subdivx_subtitle_id, workdir, uncompress_callback=None):
    # https://www.subdivx.com/descargar.php?id=217726
    actual_subtitle_file_url = MAIN_SUBDIVX_URL + "descargar.php?id=" + subdivx_subtitle_id
    content = get_url(actual_subtitle_file_url)
    if content is not None:
        saved_fnames = save_subtitles(workdir, content, uncompress_callback)
        return saved_fnames
    log("Got no content when trying to download file", level=logging.CRITICAL)
    return []


def save_subtitles(workdir, content, uncompress_callback=None):
    """
    Save dowloaded file whose content is in 'content' to a temporary file
    If it's a compressed one then uncompress it.

    Returns filename of saved file or None.
    """
    ctype = is_compressed_file(contents=content)
    is_compressed = ctype is not None
    # Never found/downloaded an unpacked subtitles file, but just to be sure ...
    # Assume unpacked sub file is a '.srt'
    cfext = {"RAR": "rar", "ZIP": "zip"}.get(ctype, "srt")
    tmp_fname = pjoin(workdir, "subdivx." + cfext)
    log("Saving downloded content to '%s'" % tmp_fname)
    try:
        with open(tmp_fname, "wb") as fh:
            fh.write(content)
    except Exception:
        log("Failed to save '%s'" % tmp_fname, level=logging.CRITICAL)
        return []
    else:
        if uncompress_callback is not None and is_compressed:
            log("Decompressing %s" % tmp_fname)
            return handle_compressed_subs(workdir, tmp_fname, cfext, uncompress_callback)
        return [{"path": tmp_fname, "forced": False}]


def is_compressed_file(fname=None, contents=None):
    if contents is None:
        assert fname is not None
        contents = open(fname, "rb").read()
    assert len(contents) > 4
    header = contents[:4]
    if header == b"Rar!":
        compression_type = "RAR"
    elif header == b"PK\x03\x04":
        compression_type = "ZIP"
    else:
        compression_type = None
    return compression_type


def handle_compressed_subs(workdir, compressed_file, ext, uncompress_callback=None):
    """
    Uncompress 'compressed_file' in 'workdir'.
    """
    if uncompress_callback is not None:
        uncompress_callback(workdir, compressed_file, ext)

    files = os.listdir(workdir)
    files = [f for f in files if is_subs_file(f)]
    found_files = []
    for fname in files:
        found_files.append({"forced": is_forced_subs_file(fname), "path": pjoin(workdir, fname)})
    if not found_files:
        log("Failed to unpack subtitles", level=logging.CRITICAL)
    return found_files


def is_subs_file(fn):
    """Detect if the file has an extension we recognise as subtitle."""
    ext = fn.split(".")[-1]
    return ext.upper() in SUB_EXTS


def is_forced_subs_file(fn):
    """Detect if the file has some text in its filename we recognise as forced
    subtitle."""
    target = ".".join(fn.split(".")[:-1]) if "." in fn else fn
    return any(s in target.upper() for s in FORCED_SUB_SENTINELS)
