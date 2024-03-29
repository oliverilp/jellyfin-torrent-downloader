import base64
import hashlib
import os
import re
import shutil
import sys
from os import listdir
from os.path import isfile
from pathlib import Path
from time import sleep
import readline
import requests
import requests
import json

import qbittorrentapi
from tqdm import tqdm

CATEGORY_NAME = "jellyfin-downloader"
ALLOWED_FILE_TYPES = (".mkv", ".mp4", ".avi", ".mp3", ".ass", ".srt", ".png", ".jpg", ".txt")
BANNED_FILE_NAMES = {"RARBG.txt"}
BANNED_WORDS = {"rarbg", "bluray", "blu-ray", "x264-", "x265-", "h264-", "h265-", "hevc", "webrip", "hdrip", "web-dl"}


def get_filtered_name(file_name: str, count: int = 3):
    filtered = re.sub(
        r"(\[.*?\])|(\d{3,4}p)|(\((?!\d{4}).*?\))", "", file_name)
    if " " not in file_name and file_name.count(".") >= 3:
        # Replace dots with spaces
        filtered = re.sub(r"\.(?!\w{3}$)", " ", filtered)
    for word in BANNED_WORDS:
        filtered = re.sub(word, '', filtered, flags=re.IGNORECASE)

    filtered = re.sub(r"(\s+(?=\.\w+$))", "",
                      filtered).strip()  # clean up whitespace
    filtered = re.sub(r"(\s{2,})|(\.{2,})", " ", filtered)
    if count != 0:
        return get_filtered_name(filtered, count - 1) if len(filtered) > 4 else file_name
    return filtered


def clean_up_path(path: str, use_recursion=False):
    files = listdir(path)
    amount = 0
    for file_name in files:
        old_path = os.path.join(path, file_name)
        if isfile(old_path) and (not file_name.endswith(ALLOWED_FILE_TYPES) or file_name in BANNED_FILE_NAMES):
            print(f"Removing file {file_name}.")
            os.remove(old_path)
            continue
        if use_recursion and not isfile(old_path):
            print(f"Recursion in directory {file_name}.")
            clean_up_path(old_path, True)

        new_name = get_filtered_name(file_name)
        if file_name != new_name:
            new_path = os.path.join(path, new_name)
            os.rename(old_path, new_path)
            amount += 1
    path = path[:-1] if path.endswith("/") else path
    base_name = os.path.basename(path)
    print(
        f"Renamed {amount} item{'' if amount == 1 else 's'} in path '{base_name}'.")


def get_hash(uri: str):
    md5 = hashlib.md5(uri.encode('utf-8'))
    return base64.b64encode(md5.digest()).decode()[:-2]


def get_torrent(uri: str, torrents: list):
    md5 = get_hash(uri)
    try:
        return list(filter(lambda t: t.category == CATEGORY_NAME and t.tags == md5, torrents))[0]
    except IndexError:
        raise RuntimeError("Cannot find torrent: " + md5)


def human_size(nbytes):
    suffixes = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while nbytes >= 1024 and i < len(suffixes) - 1:
        nbytes /= 1024.
        i += 1
    f = ("%.2f" % nbytes).rstrip("0").rstrip(".")
    return '%s %s' % (f, suffixes[i])


def wait_for_torrent(uri: str, path: str, client: qbittorrentapi.Client) -> str:
    torrent = get_torrent(uri, client.torrents.info())
    total_size = human_size(torrent.properties.total_size)
    print(f"Torrent file: '{torrent.name}' ({total_size})")

    api_url = "http://localhost:5002/torrents"
    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({
        "name": torrent.name,
        "uri": uri,
        "path": path,
        "size": total_size
    })
    requests.post(api_url, headers=headers, data=payload)

    custom_format = "{desc}{percentage:5.2f}% |{bar}| [{elapsed}{postfix}]"
    with tqdm(total=100, bar_format=custom_format, dynamic_ncols=True, colour="green") as bar:
        while True:
            torrent = get_torrent(uri, client.torrents.info())
            progress = torrent.progress * 100
            bar.n = progress
            if progress >= 100.0:
                client.torrents_delete(torrent_hashes=torrent.hash)
                client.torrent_tags.delete_tags(tags=get_hash(uri))
                bar.update(0)
                return os.path.basename(torrent.content_path)
            state = torrent.state_enum.name.capitalize().replace("_", " ")
            bar.set_description(f"{state} '{get_filtered_name(torrent.name)}'")

            eta = round(torrent.eta / 60)
            speed = human_size(torrent.dlspeed)
            bar.set_postfix_str(f"{eta if eta > 0 else '< 1'}m, {speed}/s")
            bar.update(0)
            sleep(1)


def input_with_prefill(prompt, text):
    def hook():
        readline.insert_text(text)
        readline.redisplay()
    readline.set_pre_input_hook(hook)
    result = input(prompt)
    readline.set_pre_input_hook()
    return result


def run(path: str, uri_list: list):
    base_path = "/srv/dev-disk-by-uuid-2ea83a94-368c-46b4-83c5-a8433a4dd5cc/media/"
    downloads = os.path.normpath(os.path.join(base_path, "downloads"))
    final_path = os.path.normpath(os.path.join(base_path, path))
    if not final_path.endswith("/"):
        final_path += "/"
    Path(final_path).mkdir(parents=True, exist_ok=True)

    username = os.environ["TORRENT_USER"]
    password = os.environ["TORRENT_PASS"]
    ip = os.environ["TORRENT_IP"]
    port = os.environ["TORRENT_PORT"]

    client = qbittorrentapi.Client(host=f"{ip}:{port}",
                                   username=username, 
                                   password=password)
    for uri in uri_list:
        client.torrents_add(urls=uri,
                            category=CATEGORY_NAME,
                            tags=get_hash(uri))
    sleep(1)

    for uri in uri_list:
        torrent_name = wait_for_torrent(uri, path, client)
        print()
        downloads_file_name = os.path.join(downloads, torrent_name)
        final_file_name = os.path.join(final_path, torrent_name)
        print(f"Moving from {downloads_file_name} to {final_file_name}\n")
        shutil.move(downloads_file_name, final_file_name)

        if not isfile(final_file_name):
            clean_up_path(final_file_name, use_recursion=True)
        clean_up_path(final_path)
        print("Finished successfully.")


def main():
    # if os.geteuid() != 0:
    #     print("Error, script not started as root.")
    if len(sys.argv) == 3 and "--rename" == sys.argv[2]:
        path = sys.argv[1]
        clean_up_path(path, use_recursion=True)
    elif len(sys.argv) >= 3:
        path = sys.argv[1]
        uri_list = sys.argv[2:]
        run(path, uri_list)
    else:
        print("Error, incorrect arguments.")


if __name__ == "__main__":
    main()
    # x = input_with_prefill("Rename directory: ", "/path/name")
    # print()
    # print(x)
