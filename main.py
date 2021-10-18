import json
import re
import os
from asyncio import create_task, gather, run, sleep
from aiohttp import ClientSession, TCPConnector
from dotenv import load_dotenv

load_dotenv()
# edit this
sess_id = os.getenv("SESS_ID")
username = os.getenv("ACC_USERNAME")
email = os.getenv("EMAIL")
password = os.getenv("PASSWORD")
course_id = os.getenv("COURSE_ID")

# constant
DEBUG_MODE = False
CHUNK_SIZE = 1024
CLIENT_ID = "wGSpSAiKsam8CgBpYvClGBvPVJoLdgni6OpQnjR2"

def normPath(filename):
    return re.sub(r'[<>:"/\\|?*]', "", filename)

async def download_html(s: ClientSession, index, path, block):
    name = os.path.join(path, index + "_" + normPath(block["display_name"]))

    async with s.get(block["student_view_url"], cookies={"lms_sessionid": sess_id}) as r:
        with open(name + ".html", "wb") as f:
            async for c in  r.content.iter_chunked(CHUNK_SIZE):
                f.write(c)

async def download_video(s: ClientSession, index, path, block):
    name = os.path.join(path, index + "_" + normPath(block["display_name"]))

    download_data = [
        # (block["student_view_data"]["encoded_videos"]["hls"]["url"], ".m3u8"),
        (block["student_view_data"]["transcripts"]["en"], ".srt")
    ]

    if "desktop_mp4" in block["student_view_data"]["encoded_videos"]:
        download_data.append((block["student_view_data"]["encoded_videos"]["desktop_mp4"]["url"], ".mp4"))

    if "youtube" in block["student_view_data"]["encoded_videos"]:
        with open(name+"_youtube.txt", "wb") as f:
            f.write(block["student_view_data"]["encoded_videos"]["youtube"]["url"].encode("utf-8"))

    async def func(url, ext):
        async with s.get(url) as r:
            with open(name+ext, "wb") as f:
                async for c in  r.content.iter_chunked(CHUNK_SIZE):
                    f.write(c)
    
    tasks = [create_task(func(url, ext)) for url, ext in download_data]

    if "hls" in block["student_view_data"]["encoded_videos"]:
        with open(name+"_stream.txt", "wb") as f:
            f.write(block["student_view_data"]["encoded_videos"]["hls"]["url"].encode("utf-8"))

    await gather(*tasks)

async def main():
    async with ClientSession(
        connector=TCPConnector(limit=5, limit_per_host=5)
    ) as s:
        async with s.post(
            "https://courses.edx.org/oauth2/access_token",
            data={
                "grant_type": "password",
                "client_id": CLIENT_ID,
                "username": email,
                "password": password
            }
        ) as r:
            if r.status != 200:
                raise BaseException("login error")
            data = json.loads(await r.text())
            token = data["access_token"]

        async with s.get(
            "https://courses.edx.org/api/courses/v2/blocks/",
            params={
                "depth": "all",
                "requested_fields": "contains_gated_content,show_gated_sections,special_exam_info,graded,format,student_view_multi_device,due,completion",
                "student_view_data": "video",
                "block_counts": "video",
                "nav_depth": "3",
                "username": username,
                "course_id": course_id
            },
            headers={
                "authorization": f"Bearer {token}"
            }
        ) as r:
            if r.status != 200:
                print(await r.text())
                raise BaseException("error loading course info")
            data = json.loads(await r.text())["blocks"]

        if DEBUG_MODE:
            json.dump(data, open("data.json", "w"), indent=4)

            for k in ["html", "vertical", "sequential", "video", "chapter"]:
                json.dump(list(filter(lambda x: x["type"]==k, data.values())), open(f"data{k}.json", "w"), indent=4)

        for c_ind, chap in enumerate(filter(lambda x: x["type"]=="chapter", data.values())):
            chap_path = os.path.join(normPath(course_id), normPath(f"{c_ind}_" + chap["display_name"]))
            print(f"{'-'*50}\nChapter: {chap['display_name']}")

            for s_ind, seq in enumerate(map(lambda seq: data[seq] , chap["descendants"])):
                seq_path = os.path.join(chap_path, normPath(f"{s_ind}_" + seq["display_name"]))
                make_seq_path = lambda : os.makedirs(seq_path, exist_ok=True)

                tasks = set()

                for v_ind, vert in enumerate(map(lambda vert: data[vert] , seq["descendants"])):
                    html_videos = list(filter(lambda b: b["type"] in ["video", "html"], map(lambda b: data[b] , vert["descendants"])))
                    
                    if len(html_videos) > 0:
                        make_seq_path()

                    for b in html_videos:
                        func = download_video if b["type"] == "video" else download_html
                        tasks.add(create_task(func(s, str(v_ind), seq_path, b)))

                if len(tasks) > 0:
                    await gather(*tasks)
                    print(f"Downloaded sequence: {seq['display_name']}")

    await sleep(.1)

run(main())