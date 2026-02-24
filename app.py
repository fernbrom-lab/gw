import os
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

# 1. 初始化 Supabase (由 Render 環境變數讀取)
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

# --- 路由設定 ---

# 首頁：直接讀取 index.html
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# API: 取得所有建案清單 (讓前端下拉選單使用)
@app.route('/api/projects', methods=['GET'])
def get_projects():
    res = supabase.table("projects").select("id, project_name").execute()
    return jsonify(res.data)

# API: 核心計算邏輯
@app.route('/api/calculate/<project_id>', methods=['GET'])
def calculate(project_id):
    try:
        # 抓取建案數據
        res = supabase.table("projects").select("*").eq("id", project_id).single().execute()
        p = res.data
        if not p:
            return jsonify({"error": "Project not found"}), 404

        # 抓取環境變數係數
        COEF_NEW = float(os.getenv('MAT_COEF_NEW', 2.5))
        COEF_REUSE = float(os.getenv('MAT_COEF_REUSE', 0.5))
        PLANT_SINK = float(os.getenv('PLANT_SINK_RATE', 0.05))
        MAT_DENSITY = float(os.getenv('MAT_KG_PER_SQM', 15.0))

        # 計算資材排碳
        mat_weight = p['area_sqm'] * MAT_DENSITY
        coef = COEF_REUSE if p['is_recycled'] else COEF_NEW
        emission = mat_weight * coef
        
        # 植物固碳
        sink = p['plant_total_count'] * PLANT_SINK 

        return jsonify({
            "project_name": p['project_name'],
            "area_sqm": p['area_sqm'],
            "emission_kg": round(emission, 2),
            "sink_kg": round(sink, 2),
            "net_impact": round(emission - sink, 2),
            "is_recycled": p['is_recycled'],
            "verifier": "蕨積數位認證 (Verified by Green-Accumulate)"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Render 會自動指定 PORT，本機測試則用 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
