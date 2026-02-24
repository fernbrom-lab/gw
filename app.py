import os, uuid
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

# 初始化 Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

# ISO 14064-1 碳排係數
FACTORS = {
    "grid": {"spot_weld": 2.4, "galvanized": 2.8, "stainless": 6.8},
    "fuel": {"diesel": 2.7, "gasoline": 2.3},
    "pot": 1.2, "drip_pipe": 0.15, "water": 0.00016, "man_day": 0.5, "acc": 2.5
}

def safe_val(val, default=0):
    """確保數值運算時不會因為 None 而崩潰"""
    try:
        return float(val) if val is not None else default
    except:
        return default
@app.route('/api/farms', methods=['GET'])
def get_farms():
    # 抓取最新的農場入庫數據
    res = supabase.table("farms").select("*").order("created_at", desc=True).limit(4).execute()
    return jsonify(res.data)
@app.route('/')
def index(): return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin(): return send_from_directory('.', 'admin.html')

@app.route('/api/projects', methods=['GET'])
def get_projects():
    res = supabase.table("projects").select("id, project_name").execute()
    return jsonify(res.data)

@app.route('/api/calculate/<project_id>', methods=['GET'])
def calculate(project_id):
    try:
        p = supabase.table("projects").select("*").eq("id", project_id).single().execute().data
        if not p: return jsonify({"error": "找不到案場"}), 404

        # 1. 材料與容器
        drip_e = safe_val(p.get('drip_layers')) * safe_val(p.get('drip_len')) * FACTORS["drip_pipe"]
        mat_e = (safe_val(p.get('grid_weight')) * FACTORS["grid"].get(p.get('grid_type'), 2.5)) + \
                (safe_val(p.get('pot_count')) * FACTORS["pot"]) + \
                (safe_val(p.get('acc_weight')) * FACTORS["acc"]) + drip_e
        
        # 2. 能源 (柴汽油分計)
        energy_e = (safe_val(p.get('diesel_liters')) * FACTORS["fuel"]["diesel"]) + \
                   (safe_val(p.get('gasoline_liters')) * FACTORS["fuel"]["gasoline"])
        
        # 3. 施工營運
        site_e = (safe_val(p.get('est_days')) * FACTORS["man_day"]) + (safe_val(p.get('water_est')) * FACTORS["water"])
        
        total_e = mat_e + energy_e + site_e
        total_s = safe_val(p.get('plant_total_count')) * 0.05 * 12

        return jsonify({
            "project_name": p.get('project_name', '未命名'),
            "details": {"material": round(mat_e, 2), "energy": round(energy_e, 2), "site": round(site_e, 2)},
            "emission_kg": round(total_e, 2), "sink_kg": round(total_s, 2), "net_impact": round(total_e - total_s, 2)
        })
    except Exception as e:
        print(f"DEBUG ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    f = request.form
    photo = request.files.get('photo')
    p_url = ""
    if photo:
        f_name = f"farm_{uuid.uuid4()}.jpg"
        supabase.storage.from_('evidences').upload(f_name, photo.read(), {"content-type": "image/jpeg"})
        p_url = supabase.storage.from_('evidences').get_public_url(f_name)
    
    supabase.table("farms").insert({
        "batch_number": f.get('batch_number'), "plant_name": f.get('plant_name'),
        "quantity": int(f.get('quantity', 0)), "in_stock_date": f.get('in_date'),
        "out_stock_date": f.get('out_date'), "photo_url": p_url
    }).execute()
    return jsonify({"status": "ok"})

@app.route('/api/add_project', methods=['POST'])
def add_project():
    supabase.table("projects").insert(request.json).execute()
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
