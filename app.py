import os, uuid
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

# 初始化 Supabase (請於 Render 設定環境變數)
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

# ISO 參考係數 (kgCO2e/單位)
FACTORS = {
    "grid": {"spot_weld": 2.4, "galvanized": 2.8, "stainless": 6.8},
    "vehicle": {"diesel": 2.73, "gasoline": 2.31},
    "pot": 1.2, "water": 0.00016, "man_day": 0.5
}

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
    p = supabase.table("projects").select("*").eq("id", project_id).single().execute().data
    
    # 分項計算
    mat_e = (p.get('grid_weight',0) * FACTORS["grid"].get(p.get('grid_type'), 2.5)) + \
            (p.get('pot_count',0) * FACTORS["pot"]) + (p.get('acc_weight',0) * 2.5)
    trans_e = p.get('vehicle_count',0) * FACTORS["vehicle"].get(p.get('vehicle_type'), 2.3)
    const_e = (p.get('man_day',0) * FACTORS["man_day"]) + (p.get('water_est',0) * FACTORS["water"])
    
    total_e = mat_e + trans_e + const_e
    total_s = p.get('plant_total_count',0) * 0.05 * 12 # 預估固碳

    return jsonify({
        "project_name": p['project_name'],
        "details": {"material": round(mat_e,2), "transport": round(trans_e,2), "site": round(const_e,2)},
        "emission_kg": round(total_e, 2),
        "sink_kg": round(total_s, 2),
        "net_impact": round(total_e - total_s, 2),
        "iso": "ISO 14064-1 Cat.4"
    })

@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    f = request.form
    photo = request.files.get('photo')
    p_url = ""
    if photo:
        f_name = f"{uuid.uuid4()}.jpg"
        supabase.storage.from_('evidences').upload(f_name, photo.read(), {"content-type": "image/jpeg"})
        p_url = supabase.storage.from_('evidences').get_public_url(f_name)
    
    payload = {
        "batch_number": f.get('batch_number'), "plant_name": f.get('plant_name'),
        "quantity": int(f.get('quantity', 0)), "photo_url": p_url
    }
    supabase.table("farms").insert(payload).execute()
    return jsonify({"status": "ok"})

@app.route('/api/add_project', methods=['POST'])
def add_project():
    supabase.table("projects").insert(request.json).execute()
    return jsonify({"status": "ok"})

@app.route('/api/protocol')
def protocol():
    return jsonify({"source": "環境部碳足跡資料庫 2026", "standard": "ISO 14064-1:2018"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
