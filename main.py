import asyncio
import glob
import os
import logging
import time
import shutil
import sys
import zipfile

import yaml
from notion2md.exporter.block import MarkdownExporter
from notion_client import AsyncClient
from dateutil import parser as dateutil

logging.basicConfig(level=logging.INFO)

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

async def try_to_update(path):
    logging.debug(f"updating {path}")
    notion = AsyncClient(auth=os.environ["NOTION_TOKEN"])
    front_matter = extrat_front_matter(path)
    logging.debug(f"{front_matter=}")
    if front_matter.get('notion_url') is None and front_matter.get('notion-url') is None:
        logging.debug(f"{front_matter.get('notion_url')=} and {front_matter.get('notion-url')=}, skip")
        return
    url = front_matter.get('notion_url') or front_matter.get('notion-url')
    block_id = extrat_block_id(url)
    logging.debug(f"{block_id=}")
    
    page = await notion.pages.retrieve(page_id=block_id)
    logging.debug(f"{page=}")
    try:
        title = page["properties"]["title"]["title"][0]["plain_text"]
        front_matter['title'] = title
    except Exception as e:
        pass
    last_edited_time = page['last_edited_time']
    last_edited_time = last_edited_time.replace('T', ' ').replace('Z', '')
    logging.debug(f"{last_edited_time=}")
    if front_matter.get('last_edited_time') is not None:
        remote_last_edited_time_timestamp = dateutil.parse(last_edited_time).timestamp()
        local_last_edited_time_timestamp = dateutil.parse(front_matter['last_edited_time']).timestamp()
        if remote_last_edited_time_timestamp <= local_last_edited_time_timestamp:
            print(f'[-] {path} is up to date, skip.')
            return
    front_matter['last_edited_time'] = last_edited_time
    
    MarkdownExporter(block_id=block_id,output_path='.',download=True).export()
    with zipfile.ZipFile(f'{block_id}.zip', 'r') as zip_ref:
        zip_ref.extractall(f'{block_id}')
    os.remove(f'{block_id}.zip')
    try:
        with open(f'{block_id}/{block_id}.md', 'r') as f:
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
        return
    finally:
        os.remove(f'{block_id}/{block_id}.md')
    try:
        path_dir = os.path.dirname(path)
        for file in glob.glob(f'{block_id}/*'):
            if os.path.isdir(file):
                shutil.copytree(f'{file}', path_dir)
            else:
                shutil.copy(f'{file}', path_dir)
    except Exception as e:
        logging.error("Error:" + str(e))
        return
    finally:
        shutil.rmtree(f'{block_id}')
    print(f"[+] {full_path} is successfully updated.")


print("====== notion-sync ======")
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python main.py <path>')
        exit(0)
    
    if len(sys.argv) > 2:
        os.environ["NOTION_TOKEN"] = sys.argv[2]

    failed = False
    print("WORK DIR:", sys.argv[1])
    
    for (root, dirs, files) in os.walk(sys.argv[1]):
        for file in files:
            if file.endswith('.md'):
                logging.debug(f"found {file}")
                full_path = os.path.join(root, file)
                try:
                    begin = time.time()
                    asyncio.run(try_to_update(full_path))
                    time.sleep(max(0, 1 - (time.time() - begin)))
                except Exception as e:
                    failed = True
                    print("[!] An error was encountered when update", full_path, ":")
                    import traceback
                    traceback.print_exception(type(e), e, e.__traceback__)
    
    if failed:
        exit(1)
