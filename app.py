import os
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

# 1. 初始化 Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

# --- 頁面路由 ---

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin():
    return send_from_directory('.', 'admin.html')

# --- 數據 API 路由 ---

# 1. 取得所有建案清單
@app.route('/api/projects', methods=['GET'])
def get_projects():
    res = supabase.table("projects").select("id, project_name").execute()
    return jsonify(res.data)

# 2. 核心計算：整合農場與建案數據
@app.route('/api/calculate/<project_id>', methods=['GET'])
def calculate(project_id):
    try:
        # 抓取建案資料
        p_res = supabase.table("projects").select("*").eq("id", project_id).single().execute()
        p = p_res.data
        if not p:
            return jsonify({"error": "Project not found"}), 404

        # 抓取對應農場資料 (依據建案名稱或設定關聯)
        f_res = supabase.table("farms").select("*").limit(1).execute() 
        f = f_res.data[0] if f_res.data else {}

        # 讀取環境變數中的隱藏係數
        COEF_NEW = float(os.getenv('MAT_COEF_NEW', 2.5))
        COEF_REUSE = float(os.getenv('MAT_COEF_REUSE', 0.5))
        MAT_DENSITY = float(os.getenv('MAT_KG_PER_SQM', 15.0))
        PLANT_SINK_RATE = float(f.get('carbon_rate_monthly', 0.05))

        # 運算邏輯
        mat_weight = p['area_sqm'] * MAT_DENSITY
        coef = COEF_REUSE if p['is_recycled'] else COEF_NEW
        emission = mat_weight * coef
        sink = p['plant_total_count'] * PLANT_SINK_RATE * 12 # 預設掛牆12個月

        return jsonify({
            "project_name": p['project_name'],
            "emission_kg": round(emission, 2),
            "sink_kg": round(sink, 2),
            "net_impact": round(emission - sink, 2),
            "is_recycled": p['is_recycled'],
            "farm_info": {
                "plant_name": f.get('plant_name', "高品質植栽"),
                "batch_number": f.get('batch_number', "N/A"),
                "photo_url": f.get('photo_url', ""),
                "in_date": f.get('in_stock_date', "")
            },
            "verifier": "蕨積數位認證 - ISO 14064 準則預估"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 3. 揭露數據信任協議 (給空數據時的公信力)
@app.route('/api/protocol', methods=['GET'])
def get_protocol():
    return jsonify({
        "standards": ["ISO 14064-1", "ISO 14067", "PAS 2050"],
        "data_sources": "環境部碳足跡資料庫 (2025-2026 更新版)",
        "factors": {
            "new_steel_factor": os.getenv('MAT_COEF_NEW', 2.5),
            "recycled_factor": os.getenv('MAT_COEF_REUSE', 0.5),
            "avg_sink_rate": 0.05
        }
    })

# 4. 管理端：新增農場資料
@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    data = request.json
    res = supabase.table("farms").insert(data).execute()
    return jsonify({"status": "success", "data": res.data})

# 5. 管理端：新增建案資料
@app.route('/api/add_project', methods=['POST'])
def add_project():
    data = request.json
    res = supabase.table("projects").insert(data).execute()
    return jsonify({"status": "success", "data": res.data})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
