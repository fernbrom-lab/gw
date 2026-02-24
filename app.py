import os
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

app = Flask(__name__, static_folder='.')

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin():
    return send_from_directory('.', 'admin.html')

@app.route('/api/projects', methods=['GET'])
def get_projects():
    res = supabase.table("projects").select("id, project_name").execute()
    return jsonify(res.data)

@app.route('/api/protocol', methods=['GET'])
def get_protocol():
    return jsonify({
        "data_sources": "環境部國家碳足跡資料庫",
        "factors": {
            "new_steel_factor": os.getenv('MAT_COEF_NEW', 2.5),
            "recycled_factor": os.getenv('MAT_COEF_REUSE', 0.5),
            "avg_sink_rate": 0.05
        }
    })

@app.route('/api/calculate/<project_id>', methods=['GET'])
def calculate(project_id):
    p_res = supabase.table("projects").select("*").eq("id", project_id).single().execute()
    p = p_res.data
    f_res = supabase.table("farms").select("*").limit(1).execute() 
    f = f_res.data[0] if f_res.data else {}

    coef = float(os.getenv('MAT_COEF_REUSE', 0.5)) if p['is_recycled'] else float(os.getenv('MAT_COEF_NEW', 2.5))
    emission = p['area_sqm'] * 15.0 * coef
    sink = p['plant_total_count'] * float(f.get('carbon_rate_monthly', 0.05)) * 12

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
        "verifier": "蕨積數位認證 (Verified by Green-Accumulate)"
    })

@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    res = supabase.table("farms").insert(request.json).execute()
    return jsonify(res.data)

@app.route('/api/add_project', methods=['POST'])
def add_project():
    res = supabase.table("projects").insert(request.json).execute()
    return jsonify(res.data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
