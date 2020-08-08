import os
import re
import shutil
import subprocess
import sys
import time
import requests
from urllib import parse
from os import listdir
from os.path import isfile, join
from pathlib import Path


def get_filtered_name(file_name: str):
    filtered = re.sub(r'(\[.*?\])|(\d{3,4}p)|(\((?!\d{4}).*?\))', '', file_name)
    filtered = re.sub(r'(\s+(?=\.\w+$))', '', filtered).lstrip()  # clean up whitespace
    return filtered


def rename(path: str):
    # files = [f for f in listdir(path) if isfile(join(path, f))]
    files = listdir(path)
    for file_name in files:
        filtered_name = get_filtered_name(file_name)
        if file_name != filtered_name:
            os.rename(os.path.join(path, file_name), os.path.join(path, filtered_name))


def get_torrent_name(url: str) -> str:
    r = requests.get(url, allow_redirects=True)
    response = r.headers.get('content-disposition')
    match = re.search(r"(?<=UTF-8'').*?(?=.torrent)", response)
    return parse.unquote(match.group())


def wait_for_torrent(final_path: str, url: str) -> str:
    t = time.time()
    # torrent_name = get_torrent_name(url)
    initial_items = listdir(final_path)
    while True:
        for i in range(1, 4):
            s = f'\rWaiting {int(time.time() - t)} seconds{"." * i}'
            print(f'{s: <22}', end='')
            dir_items = listdir(final_path)
            if len(dir_items) > len(initial_items):
                print()
                return list(set(dir_items) - set(initial_items))[0]
            time.sleep(1)


def run(path: str, url: str):
    base_path = '/home/media/'
    downloads = os.path.normpath(os.path.join(base_path, 'downloads'))
    final_path = os.path.normpath(os.path.join(base_path, path))
    if not final_path.endswith('/'):
        final_path += '/'
    Path(final_path).mkdir(parents=True, exist_ok=True)

    pwd = ['-n', '{USERNAME}:{PASSWORD}']
    cmd = ['transmission-remote', '9096', '-a', url, '-w', downloads] + pwd
    subprocess.run(cmd)

    torrent_name = wait_for_torrent(downloads, url)
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


if __name__ == '__main__':
    main()
