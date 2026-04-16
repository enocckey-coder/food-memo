"""
クラウド版 食事メモアプリ
Supabase (PostgreSQL + Storage) を使用
"""
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from supabase import create_client
from PIL import Image
import io
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()
BUCKET = 'photos'

if not SUPABASE_URL or not SUPABASE_KEY:
    print('エラー: SUPABASE_URL または SUPABASE_KEY が設定されていません')
    exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

MAX_IMAGE_SIZE = (1200, 1200)
JPEG_QUALITY = 82
ALLOWED_MIMES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/heic', 'image/bmp'}


def compress_image(file_bytes, mime_type):
    """画像を圧縮してJPEGバイト列で返す"""
    img = Image.open(io.BytesIO(file_bytes))
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    img.thumbnail(MAX_IMAGE_SIZE, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def upload_photo(file_bytes, mime_type, filename_hint='photo'):
    """Supabase Storage に画像をアップロードして公開URLを返す"""
    compressed = compress_image(file_bytes, mime_type)
    key = f"{uuid.uuid4()}.jpg"
    sb.storage.from_(BUCKET).upload(
        key,
        compressed,
        file_options={"content-type": "image/jpeg", "upsert": "false"}
    )
    url = sb.storage.from_(BUCKET).get_public_url(key)
    return url, key


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/meals', methods=['GET'])
def get_meals():
    PAGE = 1000
    all_data = []
    offset = 0
    while True:
        result = sb.table('meals').select('*').order('datetime', desc=True) \
                   .range(offset, offset + PAGE - 1).execute()
        all_data.extend(result.data)
        if len(result.data) < PAGE:
            break
        offset += PAGE
    return jsonify(all_data)


@app.route('/api/meals', methods=['POST'])
def add_meal():
    import json as _json
    meal_id = str(uuid.uuid4())
    dt = request.form.get('datetime', datetime.now().strftime('%Y-%m-%dT%H:%M'))

    photo_url = None
    photo_key = None
    photo_urls = []
    photo_keys = []
    if 'photo' in request.files:
        photo = request.files['photo']
        if photo and photo.filename:
            file_bytes = photo.read()
            try:
                photo_url, photo_key = upload_photo(file_bytes, photo.content_type)
                photo_urls = [photo_url]
                photo_keys = [photo_key]
            except Exception:
                pass

    meal = {
        'id': meal_id,
        'datetime': dt,
        'meal_type': request.form.get('meal_type', 'other'),
        'description': request.form.get('description', ''),
        'location': request.form.get('location', ''),
        'photo_url': photo_url,
        'photo_key': photo_key,
        'photo_urls': _json.dumps(photo_urls),
        'photo_keys': _json.dumps(photo_keys),
        'created_at': datetime.now().isoformat(),
    }
    result = sb.table('meals').insert(meal).execute()
    return jsonify(result.data[0]), 201


@app.route('/api/meals/<meal_id>', methods=['PUT'])
def update_meal(meal_id):
    import json as _json
    updates = {
        'datetime': request.form.get('datetime'),
        'meal_type': request.form.get('meal_type'),
        'description': request.form.get('description'),
        'location': request.form.get('location'),
        'updated_at': datetime.now().isoformat(),
    }
    updates = {k: v for k, v in updates.items() if v is not None}

    if 'photo' in request.files:
        photo = request.files['photo']
        if photo and photo.filename:
            old = sb.table('meals').select('photo_key,photo_keys').eq('id', meal_id).execute()
            if old.data:
                # 古いキーをすべて削除
                old_keys = []
                if old.data[0].get('photo_key'):
                    old_keys.append(old.data[0]['photo_key'])
                try:
                    extra = _json.loads(old.data[0].get('photo_keys') or '[]')
                    old_keys.extend(extra)
                except Exception:
                    pass
                old_keys = list(set(old_keys))
                if old_keys:
                    try:
                        sb.storage.from_(BUCKET).remove(old_keys)
                    except Exception:
                        pass
            file_bytes = photo.read()
            try:
                url, key = upload_photo(file_bytes, photo.content_type)
                updates['photo_url'] = url
                updates['photo_key'] = key
                updates['photo_urls'] = _json.dumps([url])
                updates['photo_keys'] = _json.dumps([key])
            except Exception:
                pass

    result = sb.table('meals').update(updates).eq('id', meal_id).execute()
    return jsonify(result.data[0] if result.data else {})


@app.route('/api/meals/<meal_id>', methods=['DELETE'])
def delete_meal(meal_id):
    row = sb.table('meals').select('photo_key').eq('id', meal_id).execute()
    if row.data and row.data[0].get('photo_key'):
        try:
            sb.storage.from_(BUCKET).remove([row.data[0]['photo_key']])
        except Exception:
            pass
    sb.table('meals').delete().eq('id', meal_id).execute()
    return jsonify({'success': True})


if __name__ == '__main__':
    print('\n=== クラウド版 食事メモアプリ ===')
    print('  http://localhost:5000')
    app.run(host='0.0.0.0', port=5000, debug=False)
