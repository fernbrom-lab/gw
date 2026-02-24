import os
import uuid
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

# 初始化 Supabase (金鑰只存在伺服器端)
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin():
    return send_from_directory('.', 'admin.html')

# 1. 核心計算與揭露 API (略，維持原樣)
# ... [保留原本的 /api/projects, /api/calculate, /api/protocol] ...

# 2. 新增：農場數據登錄 (含圖片處理)
@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    try:
        # 接收 Form Data (包含檔案與文字)
        batch = request.form.get('batch_number')
        plant = request.form.get('plant_name')
        qty = request.form.get('quantity')
        in_date = request.form.get('in_stock_date')
        out_date = request.form.get('out_stock_date')
        file = request.files.get('photo')

        photo_url = ""
        if file:
            # 將檔案上傳至 Supabase Storage
            file_ext = file.filename.split('.')[-1]
            file_name = f"{uuid.uuid4()}.{file_ext}"
            file_data = file.read()
            
            # 上傳至 'evidences' Bucket
            storage_res = supabase.storage.from_('evidences').upload(file_name, file_data, {"content-type": file.content_type})
            # 取得公開網址
            photo_url = supabase.storage.from_('evidences').get_public_url(file_name)

        # 寫入資料表
        payload = {
            "batch_number": batch,
            "plant_name": plant,
            "quantity": int(qty) if qty else 0,
            "in_stock_date": in_date if in_date else None,
            "out_stock_date": out_date if out_date else None,
            "photo_url": photo_url
        }
        res = supabase.table("farms").insert(payload).execute()
        return jsonify({"status": "success", "data": res.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 3. 新增案場 (純文字)
@app.route('/api/add_project', methods=['POST'])
def add_project():
    try:
        data = request.json
        res = supabase.table("projects").insert(data).execute()
        return jsonify({"status": "success", "data": res.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
