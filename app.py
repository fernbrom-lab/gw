import os
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

# 1. 初始化 Supabase (環境變數由 Render 注入)
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/projects', methods=['GET'])
def get_projects():
    res = supabase.table("projects").select("id, project_name").execute()
    return jsonify(res.data)

@app.route('/api/calculate/<project_id>', methods=['GET'])
def calculate(project_id):
    try:
        # A. 抓取建案數據
        p_res = supabase.table("projects").select("*").eq("id", project_id).single().execute()
        p = p_res.data
        if not p:
            return jsonify({"error": "Project not found"}), 404

        # B. 抓取農場數據 (假設以 plant_name 關聯，實際可依 batch_number)
        # 這裡模擬抓取該建案對應的農場植物資訊
        f_res = supabase.table("farms").select("*").limit(1).execute() 
        f = f_res.data[0] if f_res.data else {}

        # C. 讀取環境變數中的隱藏係數 (保護商業機密)
        COEF_NEW = float(os.getenv('MAT_COEF_NEW', 2.5))
        COEF_REUSE = float(os.getenv('MAT_COEF_REUSE', 0.5))
        MAT_DENSITY = float(os.getenv('MAT_KG_PER_SQM', 15.0))
        
        # 從農場資料表抓取該植物專屬係數，若無則用預設 0.05
        plant_coef = f.get('carbon_rate_monthly', 0.05)

        # D. 核心計算
        mat_weight = p['area_sqm'] * MAT_DENSITY
        coef = COEF_REUSE if p['is_recycled'] else COEF_NEW
        emission = mat_weight * coef
        
        # 植物固碳 (假設掛牆週期 12 個月)
        sink = p['plant_total_count'] * plant_coef * 12

        return jsonify({
            "project_name": p['project_name'],
            "area_sqm": p['area_sqm'],
            "emission_kg": round(emission, 2),
            "sink_kg": round(sink, 2),
            "net_impact": round(emission - sink, 2),
            "is_recycled": p['is_recycled'],
            # 農場溯源資訊
            "farm_info": {
                "plant_name": f.get('plant_name', "標準植栽"),
                "batch_number": f.get('batch_number', "N/A"),
                "photo_url": f.get('photo_url', ""),
                "in_date": f.get('in_stock_date', ""),
                "out_date": f.get('out_stock_date', "")
            },
            "verifier": "蕨積數位認證 - 全生命週期監控"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
