import os
import re
import shutil
import subprocess
import sys
import requests
from time import sleep
from urllib import parse
from os import listdir
from os.path import isfile
from pathlib import Path
from difflib import get_close_matches
from tqdm import tqdm
from transmission_rpc import Client


def get_filtered_name(file_name: str):
    filtered = re.sub(r"(\[.*?\])|(\d{3,4}p)|(\((?!\d{4}).*?\))", "", file_name)
    filtered = re.sub(r"(\s+(?=\.\w+$))", "", filtered).strip()  # clean up whitespace
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


def get_torrent_name(url: str) -> str:
    r = requests.get(url, allow_redirects=True)
    response = r.headers.get("content-disposition")
    match = re.search(r"(?<=filename=\").*?(?=.torrent)", response)
    return parse.unquote(match.group())


def get_torrent(name: str, torrents: list):
    torrent_names = list(map(lambda t: t.name, torrents))
    match_name = get_close_matches(name, torrent_names)[0]
    return list(filter(lambda t: t.name == match_name, torrents))[0]


def wait_for_torrent(url: str, username: str, password: str) -> str:
    c = Client(host="localhost", port=9096, username=username, password=password)
    name = get_torrent_name(url)
    custom_format = "{desc}{percentage:5.2f}% |{bar}| [{elapsed}{postfix}]"
    with tqdm(total=100, bar_format=custom_format, dynamic_ncols=True, colour="green") as bar:
        while True:
            torrents = c.get_torrents()
            torrent = get_torrent(name, torrents)
            bar.n = torrent.progress
            if torrent.progress >= 100.0:
                c.remove_torrent(torrent.id)
                bar.update(0)
                return torrent.name
            bar.set_description(f"{torrent.status.capitalize()} '{name}'")
            eta = torrent.format_eta().replace("0 ", "")
            speed = round(torrent.rateDownload / 1000000, 1)
            bar.set_postfix_str(f"{eta}, {speed} MB/s")
            bar.update(0)
            sleep(1)


def run(path: str, url: str):
    base_path = "/home/media/"
    downloads = os.path.normpath(os.path.join(base_path, "downloads"))
    final_path = os.path.normpath(os.path.join(base_path, path))
    if not final_path.endswith("/"):
        final_path += "/"
    Path(final_path).mkdir(parents=True, exist_ok=True)

    username = os.environ["TRANSMISSION_USER"]
    password = os.environ["TRANSMISSION_PASS"]
    cmd = ["transmission-remote", "9096", "-a", url, "-w", downloads, "-n", f"{username}:{password}"]
    subprocess.run(cmd)

    torrent_name = wait_for_torrent(url, username, password)
    print()
    final_file_name = os.path.join(final_path, torrent_name)
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
