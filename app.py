import os, uuid
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

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
def index(): return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin(): return send_from_directory('.', 'admin.html')

@app.route('/api/projects', methods=['GET'])
def get_projects():
    res = supabase.table("projects").select("id, project_name").execute()
    return jsonify(res.data)

@app.route('/api/farms', methods=['GET'])
def get_farms():
    res = supabase.table("farms").select("*").order("created_at", desc=True).limit(10).execute()
    return jsonify(res.data)

@app.route('/api/calculate/<project_id>', methods=['GET'])
def calculate(project_id):
    try:
        p = supabase.table("projects").select("*").eq("id", project_id).single().execute().data
        if not p: return jsonify({"error": "No data"}), 404
        
        # 碳排計算邏輯
        drip_e = safe_float(p.get('drip_layers')) * safe_float(p.get('drip_len')) * FACTORS["drip_pipe"]
        mat_e = (safe_float(p.get('grid_weight')) * FACTORS["grid"].get(p.get('grid_type'), 2.5)) + \
                (safe_float(p.get('pot_count')) * FACTORS["pot"]) + \
                (safe_float(p.get('acc_weight')) * FACTORS["acc"]) + drip_e
        
        energy_e = (safe_float(p.get('diesel_liters')) * FACTORS["fuel"]["diesel"]) + \
                   (safe_float(p.get('gasoline_liters')) * FACTORS["fuel"]["gasoline"])
        
        site_e = (safe_float(p.get('est_days')) * FACTORS["man_day"]) + (safe_float(p.get('water_est')) * FACTORS["water"])
        
        total_e = mat_e + energy_e + site_e
        total_s = safe_float(p.get('plant_total_count')) * 0.05 * 12

        return jsonify({
            "project_name": p.get('project_name'),
            "details": {"material": round(mat_e, 1), "energy": round(energy_e, 1), "site": round(site_e, 1)},
            "emission_kg": round(total_e, 1),
            "sink_kg": round(total_s, 1),
            "net_impact": round(total_e - total_s, 1)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    try:
        f, photo = request.form, request.files.get('photo')
        p_url = ""
        if photo:
            f_name = f"farm_{uuid.uuid4()}.jpg"
            supabase.storage.from_('evidences').upload(f_name, photo.read(), {"content-type": "image/jpeg"})
            p_url = supabase.storage.from_('evidences').get_public_url(f_name)
        
        # 修正：確保空日期不會導致 SQL 錯誤
        supabase.table("farms").insert({
            "batch_number": f.get('batch_number'),
            "plant_name": f.get('plant_name'),
            "quantity": int(f.get('quantity', 0)) if f.get('quantity') else 0,
            "in_stock_date": f.get('in_date') if f.get('in_date') else None,
            "out_stock_date": f.get('out_date') if f.get('out_date') else None,
            "photo_url": p_url
        }).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"DEBUG: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/add_project', methods=['POST'])
def add_project():
    try:
        supabase.table("projects").insert(request.json).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
