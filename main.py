import asyncio
import glob
import os
import logging
import time
import shutil
import json
import sys
import zipfile

import yaml
from notion2md.exporter.block import MarkdownExporter
from notion_client import AsyncClient
from dateutil import parser as dateutil

logging.basicConfig(level=logging.DEBUG if os.environ.get("debug") else logging.INFO)
author = None
change = {
    "updated": [],
    "deleted": []
}
subdir = False if os.environ.get("SUBDIR") == 'false' else True

async def request_wrapper(job):
    begin = time.time()
    res = await job()
    end = time.time()
    time.sleep(max(0, 0.35 - (end - begin)))
    return res

async def getAuthor(page):
    if author is not None:
        return author
    try:
        notion = AsyncClient(auth=os.environ["NOTION_TOKEN"])
        async def job():
            return await notion.users.retrieve(user_id=page["created_by"]["id"])
        res = await request_wrapper(job)
        return res['name']
    except Exception as e:
        logging.error(e)    
    return 'From Notion'

def extrat_block_id(url):
    return url.split('/')[-1].split('?')[0].split('-')[-1]


def extrat_front_matter(path):
    front_matter = {}
    with open(path, 'r') as f:
        data = f.read()
    if not data.startswith('---'):
        return {}
    end_index = data.find('---', 3)
    if end_index == -1:
        return {}
    front_matter_str = data[3:end_index]
    front_matter = yaml.load(front_matter_str, Loader=yaml.FullLoader)
    return front_matter


async def update_file(path, block_id=None, page=None, forceUpdate=False):
    logging.debug(f"updating {path}")

    notion = AsyncClient(auth=os.environ["NOTION_TOKEN"])
    if os.path.isfile(path):
        front_matter = extrat_front_matter(path)
        if front_matter.get('notion_url') is None and front_matter.get('notion-url') is None and block_id is None:
            logging.debug(f"{front_matter.get('notion_url')=} and {front_matter.get('notion-url')=}, skip")
            return None
    else:
        front_matter = {}
    logging.debug(f"{front_matter=}")
    
    if block_id is None:
        url = front_matter.get('notion_url') or front_matter.get('notion-url')
        block_id = extrat_block_id(url)
    logging.debug(f"{block_id=}")
    
    if page is None:
        async def job():
            return await notion.pages.retrieve(page_id=block_id)
        page = await request_wrapper(job)
    logging.debug(f"{page=}")

    if_update = False
    try:
        title = page["properties"].get("Name") or page["properties"]['title']
        title = title["title"][0]["plain_text"]
        if front_matter.get('title') != title:
            front_matter['title'] = title
            if_update = True
    except Exception as e:
        logging.warning(e)

    try:
        date = page['created_time']
        date = date.replace('T', ' ').replace('Z', '')
        if front_matter.get('date') is None:
            front_matter['date'] = date
            if_update = True
    except Exception as e:
        logging.warning(e)


    if page.get('url'):
        front_matter['from_notion'] = page['url']
        if_update = True

    remote_author = await getAuthor(page)
    if front_matter.get('author') != remote_author:
        front_matter['author'] = remote_author
        if_update = True

    last_edited_time = page['last_edited_time']
    last_edited_time = last_edited_time.replace('T', ' ').replace('Z', '')
    logging.debug(f"{last_edited_time=}")
    if front_matter.get('last_edited_time') is not None:
        remote_last_edited_time_timestamp = dateutil.parse(last_edited_time).timestamp()
        local_last_edited_time_timestamp = dateutil.parse(front_matter['last_edited_time']).timestamp()
        if remote_last_edited_time_timestamp > local_last_edited_time_timestamp:
            if_update = True
    if not if_update and not forceUpdate:
        print(f'[-] {path} is up to date, skip.')
        return None
    front_matter['last_edited_time'] = last_edited_time
    
    MarkdownExporter(block_id=block_id,output_path='.',download=True).export()
    with zipfile.ZipFile(f'{block_id}.zip', 'r') as zip_ref:
        zip_ref.extractall(f'{block_id}_tmp')
    os.remove(f'{block_id}.zip')
    try:
        with open(f'{block_id}_tmp/{block_id}.md', 'r') as f:
            content = f.read()
            logging.debug(f"{content=}")
        front_matter_all_str = yaml.dump(front_matter, sort_keys=False, indent=2, allow_unicode=True)
        with open(path, 'w') as f:
            f.write("---\n")
            f.write(front_matter_all_str)
            f.write('---\n')
            f.write(content)
    except Exception as e:
        logging.error("Error:" + str(e))
        return None
    finally:
        os.remove(f'{block_id}_tmp/{block_id}.md')
    files = []
    try:
        path_dir = os.path.dirname(path)
        for file in glob.glob(f'{block_id}_tmp/*'):
            files.append(file.replace(f'{block_id}_tmp/', ''))
            if os.path.isdir(file):
                shutil.copytree(file, path_dir)
            else:
                shutil.copy(file, path_dir)
    except Exception as e:
        logging.error("Error:" + str(e))
        return None
    finally:
        shutil.rmtree(f'{block_id}_tmp')
    print(f"[+] {path} is successfully updated.")
    change['updated'].append(front_matter.get('title') or path)
    return files


async def update_list(file_path):
    with open(file_path, "r") as f:
        database_id = f.read()

    dir_path = os.path.dirname(file_path)
    database_id = extrat_block_id(database_id)
    notion = AsyncClient(auth=os.environ["NOTION_TOKEN"])
    async def job():
        return await notion.databases.query(database_id=database_id)
    res = await request_wrapper(job)
    assert res["object"] == "list"

    if os.path.isfile(os.path.join(dir_path, "notion/.notion_files")):
        with open(os.path.join(dir_path, "notion/.notion_files"), "r") as f:
            old_files = json.load(f)
    else:
        old_files = {}

    new_files = set()
    for page in res["results"]:
        logging.debug(f"{page['id']=}")
        ppath = f"{page['id']}" if subdir else ""
        fpath = os.path.join(dir_path, f"notion/{ppath}")
        if not os.path.exists(fpath):
            os.makedirs(fpath)
        forceUpdate = False
        if not old_files.get(page["id"]):
            forceUpdate = True
        markdown_path = os.path.join(fpath, f"{page['id']}.md")
        files = await update_file(markdown_path, page["id"], page, forceUpdate=forceUpdate)
        file_list = old_files.get(page["id"], [])
        if subdir:
            new_files.add(page['id'])
            file_list = [page['id']]
        else:
            if files is not None:
                new_files.add(f"{page['id']}.md")
                file_list = [f"{page['id']}.md"]
                for file in files:
                    new_files.add(os.path.join(ppath, file))
                    file_list.append(os.path.join(ppath, file))
            else:
                for file in file_list:
                    new_files.add(file)
        old_files[page["id"]] = file_list
    now_files = set(os.listdir(os.path.join(dir_path, "notion")))
    for files in now_files - new_files:
        if files.endswith(".notion_files"):
            continue
        path = os.path.join(os.path.join(dir_path, "notion"), files)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        logging.info(f"[*] Removed {files}")
        change['deleted'].append(files)

    with open(os.path.join(dir_path, "notion/.notion_files"), "w") as f:
        json.dump(old_files, f, indent=2)

print("====== notion-sync ======")
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python main.py <path> [token] [author]')
        exit(0)
    
    if len(sys.argv) > 2:
        os.environ["NOTION_TOKEN"] = sys.argv[2]

    if len(sys.argv) > 3:
        author = sys.argv[3]

    failed = False
    print("WORK DIR:", sys.argv[1])
    
    for (root, dirs, files) in os.walk(sys.argv[1]):
        for file in files:
            full_path = os.path.join(root, file)
            try:
                if file.endswith('.md'):
                    logging.debug(f"found file {file}")
                    asyncio.run(update_file(full_path))
                elif file.endswith(".notion_list"):
                    logging.debug(f"found list {file}")
                    asyncio.run(update_list(full_path))
            except Exception as e:
                failed = True
                print("[!] An error was encountered when update", full_path, ":")
                import traceback
                traceback.print_exception(type(e), e, e.__traceback__)
            
    summary = ''
    detail = ''
    if len(change['updated']) > 0:
        summary += f"Updated {len(change['updated'])} file(s)"
    if len(change['deleted']) > 0:
        if len(summary) > 0:
            summary += " and "
        summary += f"Deleted {len(change['deleted'])} file(s)"
    for file in change['updated']:
        detail += f"Updated {file}\n"
    for file in change['deleted']:
        detail += f"Deleted {file}\n"

    with open("/tmp/changelog", "w") as f:
        f.write(summary + "\n" + detail)

    if failed:
        exit(1)
