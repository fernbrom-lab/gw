import os, uuid
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

# 初始化 Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

# ISO 14064-1 Cat.4 碳排係數表
FACTORS = {
    "grid": {"spot_weld": 2.4, "galvanized": 2.8, "stainless": 6.8}, # 網材
    "vehicle": {"diesel": 2.73, "gasoline": 2.31}, # 運輸 (每趟)
    "pot": 1.2,        # 塑膠花槽
    "drip_pipe": 0.15, # 滴灌管 (每米)
    "water": 0.00016,  # 自來水 (每公升)
    "man_day": 0.5,    # 施工能耗 (每人天)
    "acc": 2.5         # 其他金屬配件 (每公斤)
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
    
    # 1. 材料碳排 (含滴灌管: 層數 * 長度 * 係數)
    drip_e = p.get('drip_layers', 0) * p.get('drip_len', 0) * FACTORS["drip_pipe"]
    mat_e = (p.get('grid_weight', 0) * FACTORS["grid"].get(p.get('grid_type'), 2.5)) + \
            (p.get('pot_count', 0) * FACTORS["pot"]) + \
            (p.get('acc_weight', 0) * FACTORS["acc"]) + drip_e
    
    # 2. 運輸碳排
    trans_e = p.get('vehicle_count', 0) * FACTORS["vehicle"].get(p.get('vehicle_type'), 2.3)
    
    # 3. 施工與營運碳排
    const_e = (p.get('man_day', 0) * FACTORS["man_day"]) + (p.get('water_est', 0) * FACTORS["water"])
    
    total_e = mat_e + trans_e + const_e
    total_s = p.get('plant_total_count', 0) * 0.05 * 12 # 預估年固碳量

    return jsonify({
        "project_name": p['project_name'],
        "details": {
            "material": round(mat_e, 2),
            "transport": round(trans_e, 2),
            "site": round(const_e, 2)
        },
        "emission_kg": round(total_e, 2),
        "sink_kg": round(total_s, 2),
        "net_impact": round(total_e - total_s, 2),
        "iso": "ISO 14064-1:2018 Category 4"
    })

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
        "quantity": int(f.get('quantity', 0)), "photo_url": p_url
    }).execute()
    return jsonify({"status": "ok"})

@app.route('/api/add_project', methods=['POST'])
def add_project():
    supabase.table("projects").insert(request.json).execute()
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
