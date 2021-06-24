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

import qbittorrentapi
from hurry.filesize import size, alternative
from tqdm import tqdm

CATEGORY_NAME = "jellyfin-downloader"


def get_filtered_name(file_name: str, count: int = 3):
    filtered = re.sub(r"(\[.*?\])|(\d{3,4}p)|(\((?!\d{4}).*?\))", "", file_name)
    filtered = re.sub(r"(\s+(?=\.\w+$))", "", filtered).strip()  # clean up whitespace
    filtered = re.sub(r"(\s{2,})", " ", filtered)  # clean up multiple white space characters
    if count != 0:
        return get_filtered_name(filtered, count - 1) if len(filtered) > 4 else file_name
    return filtered


def rename(path: str):
    files = listdir(path)
    amount = 0
    for file_name in files:
        filtered_name = get_filtered_name(file_name)
        if file_name != filtered_name:
            os.rename(os.path.join(path, file_name), os.path.join(path, filtered_name))
            amount += 1
    print(f"Renamed {amount} item{'' if amount == 1 else 's'}.")


def get_hash(url: str):
    md5 = hashlib.md5(url.encode('utf-8'))
    return base64.b64encode(md5.digest()).decode()[:-2]


def get_torrent(url: str, torrents: list):
    md5 = get_hash(url)
    try:
        return list(filter(lambda t: t.category == CATEGORY_NAME and t.tags == md5, torrents))[0]
    except IndexError:
        raise RuntimeError("Cannot find torrent: " + md5)


def wait_for_torrent(url: str, client: qbittorrentapi.Client) -> str:
    torrent = get_torrent(url, client.torrents.info())
    total_size = size(torrent.properties.total_size, system=alternative)
    print(f"Torrent file: '{torrent.name}' ({total_size})")

    custom_format = "{desc}{percentage:5.2f}% |{bar}| [{elapsed}{postfix}]"
    with tqdm(total=100, bar_format=custom_format, dynamic_ncols=True, colour="green") as bar:
        while True:
            torrent = get_torrent(url, client.torrents.info())
            progress = torrent.progress * 100
            bar.n = progress
            if progress >= 100.0:
                client.torrents_delete(torrent_hashes=torrent.hash)
                client.torrent_tags.delete_tags(tags=get_hash(url))
                bar.update(0)
                return torrent.name
            state = torrent.state_enum.name.capitalize().replace("_", " ")
            bar.set_description(f"{state} '{get_filtered_name(torrent.name)}'")

            eta = round(torrent.eta / 60)
            speed = size(torrent.dlspeed, system=alternative)
            bar.set_postfix_str(f"{eta if eta > 0 else '< 1'}m, {speed}/s")
            bar.update(0)
            sleep(1)


def run(path: str, url: str):
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

    client = qbittorrentapi.Client(host=f'{ip}:{port}', username=username, password=password)
    client.torrents_add(urls=url, category=CATEGORY_NAME, tags=get_hash(url))
    sleep(1)

    torrent_name = wait_for_torrent(url, client)
    print()
    initial_file_name = os.path.join(downloads, torrent_name)
    final_file_name = os.path.join(final_path, torrent_name)
    print(f"Moving from {initial_file_name} to {final_file_name}")
    shutil.move(os.path.join(downloads, torrent_name), final_file_name)

    if not isfile(final_file_name):
        rename(final_file_name)
    rename(final_path)
    print("Finished successfully.")


def main():
    if os.geteuid() != 0:
        print("Error, script not started as root.")
    elif len(sys.argv) == 3:
        path = sys.argv[1]
        url = sys.argv[2]
        run(path, url)
    else:
        print("Error, incorrect arguments.")


if __name__ == "__main__":
    main()
