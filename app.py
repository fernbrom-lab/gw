import os
import uuid
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)  # 允許跨域請求

# 初始化 Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

# ISO 14064-1 係數
FACTORS = {
    "grid": {"spot_weld": 2.4, "galvanized": 2.8, "stainless": 6.8},
    "fuel": {"diesel": 2.7, "gasoline": 2.3},
    "pot": 1.2, "drip_pipe": 0.15, "water": 0.00016, "man_day": 0.5, "acc": 2.5
}

def safe_float(v):
    try: return float(v) if v else 0.0
    except: return 0.0

@app.route('/')
def index(): 
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin(): 
    return send_from_directory('.', 'admin.html')

# 取得所有案場
@app.route('/api/projects', methods=['GET'])
def get_projects():
    try:
        res = supabase.table("projects").select("id, project_name").execute()
        return jsonify(res.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 取得最近50筆農場資料
@app.route('/api/farms', methods=['GET'])
def get_farms():
    try:
        res = supabase.table("farms").select("*").order("created_at", desc=True).limit(50).execute()
        return jsonify(res.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 計算碳排
@app.route('/api/calculate/<project_id>', methods=['GET'])
def calculate(project_id):
    try:
        p = supabase.table("projects").select("*").eq("id", project_id).single().execute().data
        if not p: 
            return jsonify({"error": "找不到案場"}), 404
        
        # 碳排計算邏輯
        drip_e = safe_float(p.get('drip_layers')) * safe_float(p.get('drip_len')) * FACTORS["drip_pipe"]
        
        grid_factor = FACTORS["grid"].get(p.get('grid_type'), 2.5)
        mat_e = (safe_float(p.get('grid_weight')) * grid_factor) + \
                (safe_float(p.get('pot_count')) * FACTORS["pot"]) + \
                (safe_float(p.get('acc_weight')) * FACTORS["acc"]) + drip_e
        
        energy_e = (safe_float(p.get('diesel_liters')) * FACTORS["fuel"]["diesel"]) + \
                   (safe_float(p.get('gasoline_liters')) * FACTORS["fuel"]["gasoline"])
        
        site_e = (safe_float(p.get('est_days')) * FACTORS["man_day"]) + \
                 (safe_float(p.get('water_est')) * FACTORS["water"])
        
        total_e = mat_e + energy_e + site_e
        total_s = safe_float(p.get('plant_total_count')) * 0.05 * 12

        return jsonify({
            "project_name": p.get('project_name'),
            "details": {
                "material": round(mat_e, 1), 
                "energy": round(energy_e, 1), 
                "site": round(site_e, 1)
            },
            "emission_kg": round(total_e, 1),
            "sink_kg": round(total_s, 1),
            "net_impact": round(total_e - total_s, 1)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 新增農場資料
@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    try:
        # 取得表單資料
        batch_number = request.form.get('batch_number')
        if not batch_number:
            return jsonify({"error": "批號為必填"}), 400
        
        # 處理照片上傳
        photo_url = ""
        photo = request.files.get('photo')
        if photo and photo.filename:
            try:
                # 生成唯一檔名
                file_ext = photo.filename.split('.')[-1] if '.' in photo.filename else 'jpg'
                file_name = f"farm_{uuid.uuid4()}.{file_ext}"
                
                # 讀取檔案內容
                file_content = photo.read()
                
                # 上傳到 Supabase Storage
                supabase.storage.from_('evidences').upload(
                    file_name, 
                    file_content,
                    {"content-type": photo.content_type}
                )
                
                # 獲取公開 URL
                photo_url = supabase.storage.from_('evidences').get_public_url(file_name)
                print(f"照片上傳成功: {photo_url}")
                
            except Exception as e:
                print(f"照片上傳失敗: {str(e)}")
                # 繼續執行，不要讓照片上傳失敗影響資料儲存
        
        # 準備資料
        farm_data = {
            "batch_number": batch_number,
            "plant_name": request.form.get('plant_name', ''),
            "quantity": int(request.form.get('quantity', 0)) if request.form.get('quantity') else 0,
            "in_stock_date": request.form.get('in_date') if request.form.get('in_date') else None,
            "out_stock_date": request.form.get('out_date') if request.form.get('out_date') else None,
            "photo_url": photo_url
        }
        
        print("插入 farms:", farm_data)
        
        # 插入資料庫
        result = supabase.table("farms").insert(farm_data).execute()
        return jsonify({"status": "ok", "data": result.data, "photo_url": photo_url})
        
    except Exception as e:
        print(f"錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 新增案場資料
@app.route('/api/add_project', methods=['POST'])
def add_project():
    try:
        data = request.json
        
        # 準備案場資料
        project_data = {
            "project_name": data.get('project_name', '未命名案場'),
            "grid_type": data.get('grid_type', 'spot_weld'),
            "grid_weight": float(data.get('grid_weight', 0)),
            "diesel_liters": float(data.get('diesel_liters', 0)),
            "gasoline_liters": float(data.get('gasoline_liters', 0)),
            "est_days": float(data.get('est_days', 0)),
            "pot_count": int(data.get('pot_count', 0)),
            "plant_total_count": int(data.get('plant_total_count', 0)),
            "drip_layers": int(data.get('drip_layers', 0)),
            "drip_len": float(data.get('drip_len', 0)),
            "water_est": float(data.get('water_est', 0)),
            "acc_weight": float(data.get('acc_weight', 0))
        }
        
        print("插入 projects:", project_data)
        
        # 插入資料庫
        result = supabase.table("projects").insert(project_data).execute()
        return jsonify({"status": "ok", "data": result.data})
        
    except Exception as e:
        print(f"錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 測試連線
@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "伺服器正常運作"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
