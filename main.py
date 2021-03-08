import os
import re
import shutil
import sys
import requests
from time import sleep
from urllib import parse
from os import listdir
from os.path import isfile
from pathlib import Path
from difflib import get_close_matches
from tqdm import tqdm
import qbittorrentapi
from hurry.filesize import size, alternative


CATEGORY_NAME = "jellyfin-downloader"


def get_filtered_name(file_name: str):
    filtered = re.sub(r"(\[.*?\])|(\d{3,4}p)|(\((?!\d{4}).*?\))", "", file_name)
    filtered = re.sub(r"(\s+(?=\.\w+$))", "", filtered).strip()  # clean up whitespace
    return filtered if len(filtered) > 4 else file_name


def rename(path: str):
    files = listdir(path)
    amount = 0
    for file_name in files:
        filtered_name = get_filtered_name(get_filtered_name(file_name))  # make extra sure everything is removed
        if file_name != filtered_name:
            os.rename(os.path.join(path, file_name), os.path.join(path, filtered_name))
            amount += 1
    print(f"Renamed {amount} item{'' if amount == 1 else 's'}.")


def get_torrent_name(url: str) -> str:
    r = requests.get(url, allow_redirects=True)
    response = r.headers.get("content-disposition")
    match = re.search(r"(?<=filename=\").*?(?=.torrent)", response)
    return parse.unquote(match.group())


def get_torrent(name: str, torrents: list):
    filtered = list(filter(lambda t: t.category == CATEGORY_NAME, torrents))
    torrent_names = list(map(lambda t: t.name, filtered))
    matches = get_close_matches(name, torrent_names)
    if not matches:
        new_name = get_filtered_name(name)
        if new_name == name:
            raise RuntimeError("Cannot find torrent")
        return get_torrent(new_name, torrents)
    match_name = matches[0]
    return list(filter(lambda t: t.name == match_name, torrents))[0]


def wait_for_torrent(url: str, client: qbittorrentapi.Client) -> str:
    name = get_torrent_name(url)
    custom_format = "{desc}{percentage:5.2f}% |{bar}| [{elapsed}{postfix}]"

    torrent = get_torrent(name, client.torrents.info())
    total_size = size(torrent.properties.total_size, system=alternative)
    print(f"Torrent file: '{name}' ({total_size})")

    with tqdm(total=100, bar_format=custom_format, dynamic_ncols=True, colour="green") as bar:
        while True:
            torrent = get_torrent(name, client.torrents.info())
            progress = torrent.progress * 100
            bar.n = progress
            if progress >= 100.0:
                client.torrents_delete(torrent_hashes=torrent.hash)
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
    client.torrents_add(urls=url, category=CATEGORY_NAME)
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
