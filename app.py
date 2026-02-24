import os
from flask import Flask, request, jsonify
from supabase import create_client

app = Flask(__name__)

# 初始化 Supabase (變數設定在 Render 後台)
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

@app.route('/calculate/<project_id>', methods=['GET'])
def calculate(project_id):
    # 1. 抓取建案數據
    res = supabase.table("projects").select("*").eq("id", project_id).single().execute()
    p = res.data

    # 2. 抓取環境變數中的隱藏係數 (你的商業機密)
    COEF_NEW = float(os.getenv('MAT_COEF_NEW', 2.5))
    COEF_REUSE = float(os.getenv('MAT_COEF_REUSE', 0.5))
    PLANT_SINK = float(os.getenv('PLANT_SINK_RATE', 0.05))

    # 3. 核心運算
    # 假設每平方米資材重 15kg
    mat_weight = p['area_sqm'] * 15 
    coef = COEF_REUSE if p['is_recycled'] else COEF_NEW
    emission = mat_weight * coef
    
    # 植物固碳 (以月份計算)
    sink = p['plant_total_count'] * PLANT_SINK 

    return jsonify({
        "project": p['project_name'],
        "carbon_emission_kg": round(emission, 2),
        "carbon_sink_kg": round(sink, 2),
        "net_impact": round(emission - sink, 2),
        "status": "Verified by 蕨積"
    })

if __name__ == '__main__':
    app.run(debug=True)
