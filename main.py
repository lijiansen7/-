# main.py - 完整的在线点歌系统（使用VLC播放器）
import os
import sys
import time
import threading
import requests
import re
import random
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify


# ============ 修复 VLC 路径问题 ============
def setup_vlc_path():
    """设置 VLC 动态库路径"""
    possible_paths = [
        r"D:\Program Files\VideoLAN\VLC",
        r"D:\Program Files (x86)\VideoLAN\VLC",
        r"C:\Program Files\VideoLAN\VLC",
        r"C:\Program Files (x86)\VideoLAN\VLC",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            dll_path = os.path.join(path, "libvlc.dll")
            if os.path.exists(dll_path):
                os.environ['PATH'] = path + os.pathsep + os.environ.get('PATH', '')
                print(f"✅ 找到 VLC: {path}")
                return True

    print("❌ 未找到 VLC 安装，请安装 VLC 播放器")
    print("   下载地址: https://www.videolan.org/vlc/download-windows.html")
    return False


setup_vlc_path()

# 导入 VLC
import vlc

# ============ Flask 应用初始化 ============
app = Flask(__name__)

# ============ 音乐API配置 ============
MUSIC_API = "https://api.xcvts.cn/api/music/bdyy"

# QQ音乐歌单解析API（使用 api.tjit.net）
QQ_MUSIC_API = "https://api.tjit.net/api/qqmusic/"
QQ_API_KEY = "Xpr6ctBR4ZRFRTcx9cnHUvWNJQ"  # 你的API Key

# ============ 歌单存储目录 ============
PLAYLISTS_DIR = os.path.join(os.path.dirname(__file__), 'playlists')
os.makedirs(PLAYLISTS_DIR, exist_ok=True)

# ============ 初始化播放器和队列 ============
song_queue = []
song_history = []
queue_lock = threading.Lock()


# ============ VLC播放器类 ============
class VlcPlayer:
    def __init__(self):
        self.instance = vlc.Instance('--no-video', '--quiet', '--network-caching=1000')
        self.player = self.instance.media_player_new()
        self.current_song = None
        self.is_playing = False
        self.volume = 80
        self.player.audio_set_volume(self.volume)
        self._paused = False

    def play(self, song_data):
        if not song_data or not song_data.get('play_url'):
            return False

        self.stop()
        print(f"🎵 正在加载: {song_data['name']}...")

        media = self.instance.media_new(song_data['play_url'])
        media.add_option('network-caching=1000')
        media.add_option('http-caching=1000')

        self.player.set_media(media)
        self.current_song = song_data

        ret = self.player.play()
        if ret == 0:
            self.is_playing = True
            self._paused = False
            print(f"✅ 开始播放: {song_data['name']} - {song_data['artist']}")
            return True
        else:
            print(f"❌ 播放失败: {song_data['name']}")
            self.current_song = None
            return False

    def stop(self):
        self.player.stop()
        self.is_playing = False
        self.current_song = None
        self._paused = False

    def pause(self):
        if self.is_playing:
            self.player.pause()
            self._paused = not self._paused

    def set_volume(self, volume):
        self.volume = max(0, min(100, volume))
        self.player.audio_set_volume(self.volume)

    def get_status(self):
        state = self.player.get_state()
        state_map = {
            vlc.State.Playing: 'playing',
            vlc.State.Paused: 'paused',
            vlc.State.Stopped: 'stopped',
            vlc.State.Ended: 'stopped',
            vlc.State.Error: 'error'
        }
        status = state_map.get(state, 'stopped')

        if status == 'playing':
            self.is_playing = True
            self._paused = False
        elif status == 'paused':
            self.is_playing = True
            self._paused = True
        else:
            self.is_playing = False
            if status in ('stopped', 'ended'):
                self.current_song = None

        return {
            'status': status,
            'is_playing': self.is_playing,
            'current_song': self.current_song
        }

    def get_progress(self):
        try:
            if self.current_song and self.player.is_playing():
                current_time = self.player.get_time() / 1000.0
                duration = self.player.get_length() / 1000.0
                if duration < 0:
                    duration = 300
                return {
                    'current_time': current_time,
                    'duration': duration,
                    'is_playing': self.is_playing
                }
        except:
            pass
        return {
            'current_time': 0,
            'duration': 0,
            'is_playing': False
        }

    def seek(self, time_sec):
        try:
            self.player.set_time(int(time_sec * 1000))
            return True
        except:
            return False


# 初始化播放器
player = VlcPlayer()

# ============ 随机歌单关键词 ============
RANDOM_KEYWORDS = [
    '周杰伦', '林俊杰', '邓紫棋', '陈奕迅', '蔡依林', '王菲', '张学友', '李荣浩',
    '薛之谦', '张碧晨', '毛不易', '华晨宇', '张杰', '谭维维', '徐佳莹', '方大同',
    '五月天', 'Beyond', '草东没有派对', '逃跑计划', '痛仰乐队', '新裤子', '万能青年旅店',
    '赵雷', '宋冬野', '马頔', '陈粒', '房东的猫', '好妹妹乐队', '朴树', '许巍',
    'Taylor Swift', 'Ed Sheeran', 'Adele', 'Coldplay', 'Maroon 5',
    'Justin Bieber', 'Rihanna', 'Katy Perry', 'Bruno Mars', 'The Weeknd',
    'BTS', 'BLACKPINK', 'IU', 'BigBang', 'TWICE', 'EXO',
    '邓丽君', '张国荣', '梅艳芳', '刘德华', '王杰', '齐秦',
    '米津玄师', 'YOASOBI', 'Aimer', 'Radwimps', '宇多田光', '坂本龙一',
    '周延', '艾热', '王以太', '法老', '杨和苏',
    'Alan Walker', 'The Chainsmokers', 'Marshmello'
]


# ============ 队列处理线程 ============
def process_queue():
    while True:
        try:
            state = player.player.get_state()

            if state == vlc.State.Playing and not player.is_playing:
                player.is_playing = True

            if state in (vlc.State.Stopped, vlc.State.Ended, vlc.State.Error):
                if player.is_playing or player.current_song is not None:
                    print(f"⏹️ 播放结束: {player.current_song.get('name', '未知') if player.current_song else '未知'}")
                    player.is_playing = False
                    player.current_song = None

            if not player.is_playing and song_queue:
                with queue_lock:
                    next_song = song_queue.pop(0)
                    if player.play(next_song):
                        song_history.append(next_song)
                        print(f"🎵 正在播放: {next_song['name']} - {next_song['artist']}")
                    else:
                        print(f"⚠️ 播放失败: {next_song.get('name', '未知')}，跳过")

            time.sleep(1)
        except Exception as e:
            print(f"队列处理错误: {e}")
            time.sleep(5)


threading.Thread(target=process_queue, daemon=True).start()

# ============ 在线用户管理 ============
online_users = {}
online_lock = threading.Lock()
USER_TIMEOUT = 30


def update_user_online(nickname):
    if not nickname:
        return
    with online_lock:
        online_users[nickname] = time.time()


def get_online_count():
    now = time.time()
    with online_lock:
        expired = [nick for nick, last_time in online_users.items() if now - last_time > USER_TIMEOUT]
        for nick in expired:
            del online_users[nick]
        return len(online_users)


def get_online_users():
    now = time.time()
    with online_lock:
        expired = [nick for nick, last_time in online_users.items() if now - last_time > USER_TIMEOUT]
        for nick in expired:
            del online_users[nick]
        return list(online_users.keys())


def clean_online_users():
    while True:
        time.sleep(10)
        get_online_count()


threading.Thread(target=clean_online_users, daemon=True).start()

# ============ 聊天室功能 ============
chat_messages = []
chat_lock = threading.Lock()
MAX_CHAT_MESSAGES = 200


# ============ 歌词解析 ============
def parse_lrc(lrc_text):
    if not lrc_text:
        return []
    lines = lrc_text.strip().split('\n')
    parsed = []
    time_pattern = re.compile(r'\[(\d{2}):(\d{2})(?:\.(\d{2}))?\]')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        matches = list(time_pattern.finditer(line))
        if not matches:
            continue
        text = line
        for match in matches:
            text = text.replace(match.group(0), '')
        text = text.strip()
        if not text:
            continue
        for match in matches:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            centiseconds = int(match.group(3)) if match.group(3) else 0
            time_sec = minutes * 60 + seconds + centiseconds / 100
            parsed.append({
                'time': time_sec,
                'text': text,
                'time_str': f"{minutes:02d}:{seconds:02d}"
            })
    parsed.sort(key=lambda x: x['time'])
    return parsed


# ============ 歌单存储功能 ============
def get_user_playlists(user):
    """获取用户的歌单列表"""
    file_path = os.path.join(PLAYLISTS_DIR, f"{user}.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_user_playlist(user, playlist_name, songs):
    """保存用户的歌单"""
    file_path = os.path.join(PLAYLISTS_DIR, f"{user}.json")
    data = get_user_playlists(user)

    if playlist_name in data:
        return {'exists': True, 'message': f'歌单 "{playlist_name}" 已存在'}

    data[playlist_name] = {
        'songs': songs,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'count': len(songs)
    }

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {'success': True, 'message': f'歌单 "{playlist_name}" 已保存'}


def delete_user_playlist(user, playlist_name):
    """删除用户的歌单"""
    file_path = os.path.join(PLAYLISTS_DIR, f"{user}.json")
    data = get_user_playlists(user)

    if playlist_name not in data:
        return {'error': '歌单不存在'}

    del data[playlist_name]

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {'success': True, 'message': f'歌单 "{playlist_name}" 已删除'}


# ============ Flask路由 ============

@app.route('/login')
def login():
    return render_template('login.html')


@app.route('/')
def index():
    return render_template('index.html')


# ============ 在线人数API ============
@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    data = request.json
    nickname = data.get('nickname', '').strip()
    if not nickname:
        return jsonify({'error': '昵称不能为空'}), 400
    update_user_online(nickname)
    return jsonify({
        'success': True,
        'online_count': get_online_count(),
        'online_users': get_online_users()
    })


@app.route('/api/online_users', methods=['GET'])
def get_online_users_api():
    return jsonify({
        'online_count': get_online_count(),
        'online_users': get_online_users()
    })


# ============ 聊天API ============
@app.route('/api/chat/send', methods=['POST'])
def send_chat_message():
    data = request.json
    nickname = data.get('nickname', '').strip()
    content = data.get('content', '').strip()
    if not nickname:
        return jsonify({'error': '昵称不能为空'}), 400
    if not content:
        return jsonify({'error': '消息内容不能为空'}), 400
    if len(content) > 500:
        return jsonify({'error': '消息过长（最多500字符）'}), 400
    message = {
        'nickname': nickname,
        'content': content,
        'time': datetime.now().strftime('%H:%M:%S'),
        'timestamp': time.time()
    }
    with chat_lock:
        chat_messages.append(message)
        if len(chat_messages) > MAX_CHAT_MESSAGES:
            chat_messages[:len(chat_messages) - MAX_CHAT_MESSAGES] = []
    update_user_online(nickname)
    return jsonify({'success': True, 'message': message})


@app.route('/api/chat/messages', methods=['GET'])
def get_chat_messages():
    limit = request.args.get('limit', 50, type=int)
    limit = min(limit, 100)
    with chat_lock:
        messages = chat_messages[-limit:] if chat_messages else []
    return jsonify({'success': True, 'messages': messages, 'total': len(chat_messages)})


@app.route('/api/chat/clear', methods=['POST'])
def clear_chat_messages():
    with chat_lock:
        chat_messages.clear()
    return jsonify({'success': True, 'message': '聊天记录已清空'})


# ============ 音乐搜索与播放API ============

@app.route('/api/search', methods=['GET'])
def search():
    keyword = request.args.get('keyword', '').strip()
    if not keyword:
        return jsonify({'error': '请输入搜索关键词'}), 400
    try:
        params = {'msg': keyword, 'br': '2000kflac', 'type': 'json'}
        response = requests.get(MUSIC_API, params=params, timeout=10)
        data = response.json()
        if data.get('code') == 200 and data.get('data'):
            results = []
            for idx, item in enumerate(data['data'], start=1):
                results.append({
                    'index': idx,
                    'name': item.get('name', '未知歌曲'),
                    'artist': item.get('artist', '未知歌手'),
                    'cover': item.get('pic', ''),
                    'detail_page': item.get('detail_page', '')
                })
            return jsonify({'success': True, 'results': results, 'keyword': keyword})
        else:
            return jsonify({'error': '未找到相关歌曲'}), 404
    except Exception as e:
        return jsonify({'error': f'搜索失败: {str(e)}'}), 500


@app.route('/api/get_song_url', methods=['POST'])
def get_song_url():
    data = request.json
    keyword = data.get('keyword', '')
    index = data.get('index', 1)
    if not keyword:
        return jsonify({'error': '关键词不能为空'}), 400
    try:
        params = {'msg': keyword, 'n': index, 'br': '2000kflac', 'type': 'json'}
        response = requests.get(MUSIC_API, params=params, timeout=10)
        result = response.json()
        if result.get('code') == 200 and result.get('data'):
            song_data = result['data']
            return jsonify({
                'success': True,
                'name': song_data.get('name', ''),
                'artist': song_data.get('artist', ''),
                'play_url': song_data.get('play_url', ''),
                'cover': song_data.get('cover', '')
            })
        else:
            return jsonify({'error': '获取播放地址失败'}), 404
    except Exception as e:
        return jsonify({'error': f'请求失败: {str(e)}'}), 500


@app.route('/api/add_song', methods=['POST'])
def add_song():
    data = request.json
    song = {
        'name': data.get('name', ''),
        'artist': data.get('artist', '未知歌手'),
        'play_url': data.get('play_url', ''),
        'cover': data.get('cover', ''),
        'user': data.get('user', '匿名'),
        'added_time': datetime.now().strftime('%H:%M:%S')
    }
    if not song['name'] or not song['play_url']:
        return jsonify({'error': '歌曲信息不完整'}), 400
    with queue_lock:
        song_queue.append(song)
        position = len(song_queue)
    return jsonify({
        'message': f'已添加: {song["name"]}',
        'position': position,
        'queue_length': position
    })


@app.route('/api/queue', methods=['GET'])
def get_queue():
    with queue_lock:
        queue_copy = song_queue.copy()
    state = player.player.get_state()
    status_map = {
        vlc.State.Playing: 'playing',
        vlc.State.Paused: 'paused',
        vlc.State.Stopped: 'stopped',
        vlc.State.Ended: 'stopped',
        vlc.State.Error: 'error'
    }
    real_status = status_map.get(state, 'stopped')
    if real_status == 'playing' and player.current_song is None:
        if queue_copy:
            player.current_song = queue_copy[0]
            player.is_playing = True
    current = player.current_song
    if current:
        current['is_playing'] = player.is_playing
    return jsonify({
        'queue': queue_copy,
        'current': current,
        'history': song_history[-10:]
    })


@app.route('/api/next', methods=['POST'])
def next_song():
    player.stop()
    return jsonify({'message': '已跳过'})


@app.route('/api/clear', methods=['POST'])
def clear_queue():
    with queue_lock:
        song_queue.clear()
    player.stop()
    return jsonify({'message': '队列已清空'})


@app.route('/api/volume', methods=['POST'])
def set_volume():
    volume = request.json.get('volume', 80)
    player.set_volume(volume)
    return jsonify({'volume': volume})


@app.route('/api/progress', methods=['GET'])
def get_progress():
    try:
        state = player.player.get_state()
        if state == vlc.State.Playing:
            current_time = player.player.get_time() / 1000.0
            duration = player.player.get_length() / 1000.0
            if duration < 0:
                duration = 0
            if player.current_song is None and song_queue:
                with queue_lock:
                    if song_queue:
                        player.current_song = song_queue[0]
                        player.is_playing = True
            return jsonify({
                'current_time': max(0, current_time),
                'duration': max(0, duration),
                'is_playing': True,
                'current_song': player.current_song
            })
        elif state == vlc.State.Paused:
            return jsonify({
                'current_time': player.player.get_time() / 1000.0 if player.player.get_time() > 0 else 0,
                'duration': player.player.get_length() / 1000.0 if player.player.get_length() > 0 else 0,
                'is_playing': False,
                'current_song': player.current_song
            })
        else:
            return jsonify({
                'current_time': 0,
                'duration': 0,
                'is_playing': False,
                'current_song': None
            })
    except Exception as e:
        print(f"获取进度错误: {e}")
        return jsonify({
            'current_time': 0,
            'duration': 0,
            'is_playing': False,
            'current_song': None
        })


@app.route('/api/seek', methods=['POST'])
def seek_to():
    try:
        time_sec = request.json.get('time', 0)
        if player.seek(time_sec):
            return jsonify({'success': True})
        else:
            return jsonify({'error': '跳转失败'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/toggle_play', methods=['POST'])
def toggle_play():
    try:
        state = player.player.get_state()
        if state == vlc.State.Playing:
            player.pause()
        elif state == vlc.State.Paused:
            player.pause()
        else:
            with queue_lock:
                if song_queue:
                    next_song = song_queue.pop(0)
                    player.play(next_song)
                else:
                    return jsonify({'error': '队列为空'}), 400
        new_state = player.player.get_state()
        is_playing = new_state == vlc.State.Playing
        return jsonify({
            'is_playing': is_playing,
            'status': 'playing' if is_playing else 'paused'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============ 随机歌单API ============
@app.route('/api/random_playlist', methods=['POST'])
def random_playlist():
    try:
        num_keywords = random.randint(2, 4)
        keywords = random.sample(RANDOM_KEYWORDS, num_keywords)
        all_songs = []
        used_names = set()
        for keyword in keywords:
            try:
                params = {'msg': keyword, 'br': '2000kflac', 'type': 'json'}
                response = requests.get(MUSIC_API, params=params, timeout=10)
                data = response.json()
                if data.get('code') == 200 and data.get('data'):
                    for idx, item in enumerate(data['data'], start=1):
                        song_name = item.get('name', '')
                        if song_name and song_name not in used_names:
                            used_names.add(song_name)
                            all_songs.append({
                                'name': song_name,
                                'artist': item.get('artist', '未知歌手'),
                                'cover': item.get('pic', ''),
                                'keyword': keyword,
                                'index': idx
                            })
            except Exception as e:
                print(f"搜索关键词 '{keyword}' 失败: {e}")
                continue
        random.shuffle(all_songs)
        all_songs = all_songs[:30]
        return jsonify({
            'success': True,
            'songs': all_songs,
            'count': len(all_songs),
            'keywords': keywords
        })
    except Exception as e:
        return jsonify({'error': f'生成随机歌单失败: {str(e)}'}), 500


# ============ 队列管理API ============
@app.route('/api/remove_song', methods=['POST'])
def remove_song():
    data = request.json
    position = data.get('position', -1)
    if position < 0:
        return jsonify({'error': '无效的位置'}), 400
    with queue_lock:
        if position >= len(song_queue):
            return jsonify({'error': '位置超出队列长度'}), 400
        removed_song = song_queue.pop(position)
    return jsonify({
        'success': True,
        'message': f'已移除: {removed_song["name"]}',
        'removed': removed_song,
        'queue_length': len(song_queue)
    })


@app.route('/api/remove_all', methods=['POST'])
def remove_all_songs():
    with queue_lock:
        removed_count = len(song_queue)
        song_queue.clear()
    return jsonify({
        'success': True,
        'message': f'已移除 {removed_count} 首歌曲',
        'removed_count': removed_count
    })


@app.route('/api/move_to_top', methods=['POST'])
def move_to_top():
    data = request.json
    position = data.get('position', -1)
    if position < 0:
        return jsonify({'error': '无效的位置'}), 400
    with queue_lock:
        if position >= len(song_queue):
            return jsonify({'error': '位置超出队列长度'}), 400
        if position == 0:
            return jsonify({
                'success': True,
                'message': '这首歌已经在最前面',
                'song': song_queue[0]
            })
        song = song_queue.pop(position)
        song_queue.insert(0, song)
    return jsonify({
        'success': True,
        'message': f'已置顶: {song["name"]}',
        'song': song,
        'queue_length': len(song_queue)
    })


# ============ 歌词获取API ============
@app.route('/api/get_lyrics', methods=['POST'])
def get_lyrics():
    data = request.json
    keyword = data.get('keyword', '')
    index = data.get('index', 1)
    if not keyword:
        return jsonify({'error': '关键词不能为空'}), 400
    try:
        params = {'msg': keyword, 'n': index, 'br': '2000kflac', 'type': 'json'}
        response = requests.get(MUSIC_API, params=params, timeout=10)
        result = response.json()
        if result.get('code') == 200 and result.get('data'):
            song_data = result['data']
            lrc_text = song_data.get('lrc', '')
            parsed_lyrics = parse_lrc(lrc_text)
            return jsonify({
                'success': True,
                'name': song_data.get('name', ''),
                'artist': song_data.get('artist', ''),
                'lyrics': parsed_lyrics,
                'raw_lrc': lrc_text
            })
        else:
            return jsonify({'error': '获取歌词失败'}), 404
    except Exception as e:
        return jsonify({'error': f'请求失败: {str(e)}'}), 500


# ============ 歌单导入API（仅QQ音乐） ============
@app.route('/api/import_playlist', methods=['POST'])
def import_playlist():
    """导入QQ音乐歌单 - 只返回歌单数据，不加入队列"""
    data = request.json
    playlist_url = data.get('url', '').strip()
    user = data.get('user', '匿名')

    if not playlist_url:
        return jsonify({'error': '请输入歌单链接'}), 400

    # 提取歌单ID
    match = re.search(r'id=(\d+)', playlist_url) or re.search(r'playlist[/=](\d+)', playlist_url)
    if not match:
        return jsonify({'error': '无法提取歌单ID，请检查链接格式'}), 400

    playlist_id = match.group(1)
    print(f"📥 解析歌单: ID={playlist_id}, 用户={user}")

    try:
        # 调用 api.tjit.net 获取歌单
        api_url = f"{QQ_MUSIC_API}?key={QQ_API_KEY}&id={playlist_id}&type=songlist"
        response = requests.get(api_url, timeout=15)
        result = response.json()

        if result.get('Code') != 'OK':
            return jsonify({'error': f'获取歌单失败: {result.get("Code", "未知错误")}'}), 400

        # 提取歌曲列表
        songs = result.get('Body', [])
        if not songs:
            return jsonify({'error': '歌单为空或解析失败'}), 400

        print(f"📋 歌单共有 {len(songs)} 首歌曲")

        # 返回候选列表（只返回元数据，不获取播放地址）
        candidate_songs = []
        for idx, song in enumerate(songs, 1):
            candidate_songs.append({
                'index': idx,
                'name': song.get('title', '未知歌曲'),
                'artist': song.get('author', '未知歌手'),
                'mid': song.get('mid', '')
            })

        return jsonify({
            'success': True,
            'songs': candidate_songs,
            'total': len(candidate_songs),
            'playlist_name': result.get('listname', '未命名歌单'),
            'playlist_owner': result.get('nickname', '未知')
        })

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'网络请求失败: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'解析失败: {str(e)}'}), 500


# ============ 歌单API路由 ============

@app.route('/api/playlists/save', methods=['POST'])
def save_playlist():
    """保存歌单"""
    data = request.json
    user = data.get('user', '').strip()
    playlist_name = data.get('playlist_name', '').strip()
    songs = data.get('songs', [])

    if not user:
        return jsonify({'error': '用户不能为空'}), 400
    if not playlist_name:
        return jsonify({'error': '歌单名称不能为空'}), 400
    if not songs:
        return jsonify({'error': '歌单为空'}), 400

    result = save_user_playlist(user, playlist_name, songs)
    return jsonify(result)


@app.route('/api/playlists/list', methods=['POST'])
def list_playlists():
    """获取用户的歌单列表"""
    data = request.json
    user = data.get('user', '').strip()

    if not user:
        return jsonify({'error': '用户不能为空'}), 400

    playlists = get_user_playlists(user)
    return jsonify({
        'success': True,
        'playlists': playlists
    })


@app.route('/api/playlists/load', methods=['POST'])
def load_playlist():
    """加载指定的歌单"""
    data = request.json
    user = data.get('user', '').strip()
    playlist_name = data.get('playlist_name', '').strip()

    if not user:
        return jsonify({'error': '用户不能为空'}), 400
    if not playlist_name:
        return jsonify({'error': '歌单名称不能为空'}), 400

    playlists = get_user_playlists(user)

    if playlist_name not in playlists:
        return jsonify({'error': '歌单不存在'}), 404

    return jsonify({
        'success': True,
        'playlist': {
            'name': playlist_name,
            'songs': playlists[playlist_name]['songs'],
            'created_at': playlists[playlist_name].get('created_at', ''),
            'count': len(playlists[playlist_name]['songs'])
        }
    })


@app.route('/api/playlists/delete', methods=['POST'])
def delete_playlist():
    """删除歌单"""
    data = request.json
    user = data.get('user', '').strip()
    playlist_name = data.get('playlist_name', '').strip()

    if not user:
        return jsonify({'error': '用户不能为空'}), 400
    if not playlist_name:
        return jsonify({'error': '歌单名称不能为空'}), 400

    result = delete_user_playlist(user, playlist_name)
    return jsonify(result)


# ============ 批量添加选中的歌曲 ============
@app.route('/api/add_selected_songs', methods=['POST'])
def add_selected_songs():
    """批量添加用户选中的歌曲到播放队列"""
    data = request.json
    songs = data.get('songs', [])
    user = data.get('user', '匿名')

    if not songs:
        return jsonify({'error': '请选择要添加的歌曲'}), 400

    imported = 0
    failed = 0

    for song in songs:
        try:
            song_name = song.get('name', '未知歌曲')
            song_artist = song.get('artist', '未知歌手')

            # 使用搜索API获取播放地址
            search_params = {
                'msg': f"{song_artist} {song_name}",
                'n': 1,
                'br': '2000kflac',
                'type': 'json'
            }
            search_resp = requests.get(MUSIC_API, params=search_params, timeout=10)
            search_data = search_resp.json()

            play_url = ''
            if search_data.get('code') == 200 and search_data.get('data'):
                play_url = search_data['data'].get('play_url', '')

            if play_url:
                with queue_lock:
                    song_queue.append({
                        'name': song_name,
                        'artist': song_artist,
                        'play_url': play_url,
                        'user': user,
                        'added_time': datetime.now().strftime('%H:%M:%S')
                    })
                    imported += 1
            else:
                print(f"⚠️ 未找到播放地址: {song_name} - {song_artist}")
                failed += 1
        except Exception as e:
            print(f"❌ 添加歌曲失败 {song.get('name', '未知')}: {e}")
            failed += 1
            continue

    return jsonify({
        'success': True,
        'message': f'成功添加 {imported} 首歌曲到队列' + (f'，{failed} 首未找到播放地址' if failed > 0 else ''),
        'count': imported,
        'failed': failed
    })


# ============ 启动服务 ============
if __name__ == '__main__':
    print("🎵 在线音乐点歌系统启动中...")
    print("🌐 访问地址: http://localhost:5000")
    print("🎵 音乐API: " + MUSIC_API)
    print("🎬 使用VLC播放器，支持进度条和跳转")
    print("📥 QQ音乐歌单导入已启用 (api.tjit.net)")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)