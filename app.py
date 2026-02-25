import os
import uuid
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

CARBON_FACTOR = 0.05  # 每株每月吸收 kg CO2

# 上傳照片到 Supabase Storage
def upload_photo(photo, folder="farms"):
    if not photo or not photo.filename:
        return ""
    try:
        file_ext = photo.filename.split('.')[-1] if '.' in photo.filename else 'jpg'
        file_name = f"{folder}/{uuid.uuid4()}.{file_ext}"
        file_content = photo.read()
        
        supabase.storage.from_('evidences').upload(
            file_name, 
            file_content,
            {"content-type": photo.content_type}
        )
        return supabase.storage.from_('evidences').get_public_url(file_name)
    except Exception as e:
        print(f"照片上傳失敗: {e}")
        return ""

@app.route('/')
def index(): 
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin(): 
    return send_from_directory('.', 'admin.html')

# ========== 農場主表 ==========
@app.route('/api/farms', methods=['GET'])
def get_farms():
    try:
        # 取得所有批次
        farms_res = supabase.table("farms").select("*").order("created_at", desc=True).execute()
        farms = farms_res.data
        
        result = []
        for farm in farms:
            # 取得該批次的所有生長紀錄
            growth_res = supabase.table("farm_growth_records")\
                .select("*")\
                .eq("farm_id", farm['id'])\
                .order("record_date", desc=True)\
                .execute()
            
            # 取得該批次的所有出貨紀錄
            shipments_res = supabase.table("farm_shipments")\
                .select("*")\
                .eq("farm_id", farm['id'])\
                .order("shipment_date", desc=True)\
                .execute()
            
            farm_data = {
                **farm,
                "growth_records": growth_res.data,
                "shipments": shipments_res.data,
                "total_shipped": sum(s.get('quantity', 0) for s in shipments_res.data)
            }
            result.append(farm_data)
        
        # 計算總碳吸收（根據當前庫存）
        total_plants = sum(f.get('current_quantity', 0) for f in farms)
        total_carbon = total_plants * CARBON_FACTOR * 30  # 粗略估算
        
        return jsonify({
            "farms": result,
            "summary": {
                "total_plants": total_plants,
                "total_carbon_kg": round(total_carbon, 2),
                "active_batches": len([f for f in farms if f.get('current_quantity', 0) > 0])
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 新增植物批次
@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    try:
        batch_number = request.form.get('batch_number')
        if not batch_number:
            return jsonify({"error": "批號為必填"}), 400
        
        quantity = int(request.form.get('quantity', 0))
        
        # 插入主表
        farm_data = {
            "batch_number": batch_number,
            "plant_name": request.form.get('plant_name', ''),
            "initial_quantity": quantity,
            "current_quantity": quantity,
            "in_date": request.form.get('in_date') or None,
            "supplier": request.form.get('supplier', ''),
            "notes": request.form.get('notes', '')
        }
        
        farm_res = supabase.table("farms").insert(farm_data).execute()
        farm_id = farm_res.data[0]['id']
        
        # 處理照片（如果有）
        photo = request.files.get('photo')
        if photo and photo.filename:
            photo_url = upload_photo(photo)
            if photo_url:
                # 建立初始生長紀錄
                growth_data = {
                    "farm_id": farm_id,
                    "record_date": request.form.get('in_date') or datetime.now().strftime('%Y-%m-%d'),
                    "quantity": quantity,
                    "photo_url": photo_url,
                    "notes": "初始入庫"
                }
                supabase.table("farm_growth_records").insert(growth_data).execute()
        
        return jsonify({"status": "ok", "farm_id": farm_id})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 生長紀錄 ==========
@app.route('/api/add_growth_record', methods=['POST'])
def add_growth_record():
    try:
        farm_id = request.form.get('farm_id')
        record_date = request.form.get('record_date') or datetime.now().strftime('%Y-%m-%d')
        quantity = request.form.get('quantity')
        notes = request.form.get('notes', '')
        
        # 處理照片
        photo_url = ""
        photo = request.files.get('photo')
        if photo and photo.filename:
            photo_url = upload_photo(photo, f"growth/{farm_id}")
        
        growth_data = {
            "farm_id": farm_id,
            "record_date": record_date,
            "quantity": int(quantity) if quantity else None,
            "photo_url": photo_url,
            "notes": notes
        }
        
        result = supabase.table("farm_growth_records").insert(growth_data).execute()
        
        # 如果有更新數量，同步更新主表的 current_quantity
        if quantity:
            supabase.table("farms")\
                .update({"current_quantity": int(quantity)})\
                .eq("id", farm_id)\
                .execute()
        
        return jsonify({"status": "ok", "data": result.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 出貨紀錄 ==========
@app.route('/api/add_shipment', methods=['POST'])
def add_shipment():
    try:
        data = request.json
        farm_id = data.get('farm_id')
        shipment_date = data.get('shipment_date') or datetime.now().strftime('%Y-%m-%d')
        quantity = int(data.get('quantity', 0))
        customer = data.get('customer', '')
        notes = data.get('notes', '')
        
        if quantity <= 0:
            return jsonify({"error": "出貨數量必須大於0"}), 400
        
        # 檢查庫存是否足夠
        farm_res = supabase.table("farms").select("current_quantity").eq("id", farm_id).execute()
        if not farm_res.data:
            return jsonify({"error": "找不到該批次"}), 404
        
        current = farm_res.data[0].get('current_quantity', 0)
        if quantity > current:
            return jsonify({"error": f"庫存不足，目前僅有 {current} 株"}), 400
        
        # 新增出貨紀錄
        shipment_data = {
            "farm_id": farm_id,
            "shipment_date": shipment_date,
            "quantity": quantity,
            "customer": customer,
            "notes": notes
        }
        
        result = supabase.table("farm_shipments").insert(shipment_data).execute()
        
        # 更新庫存
        new_quantity = current - quantity
        supabase.table("farms").update({"current_quantity": new_quantity}).eq("id", farm_id).execute()
        
        return jsonify({"status": "ok", "data": result.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 刪除功能 ==========
@app.route('/api/delete_farm/<farm_id>', methods=['DELETE'])
def delete_farm(farm_id):
    try:
        supabase.table("farms").delete().eq("id", farm_id).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete_growth_record/<record_id>', methods=['DELETE'])
def delete_growth_record(record_id):
    try:
        supabase.table("farm_growth_records").delete().eq("id", record_id).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete_shipment/<shipment_id>', methods=['DELETE'])
def delete_shipment(shipment_id):
    try:
        # 先取得出貨紀錄，以便恢復庫存
        shipment = supabase.table("farm_shipments").select("*").eq("id", shipment_id).execute()
        if shipment.data:
            s = shipment.data[0]
            farm_id = s['farm_id']
            quantity = s['quantity']
            
            # 恢復庫存
            farm = supabase.table("farms").select("current_quantity").eq("id", farm_id).execute()
            if farm.data:
                current = farm.data[0].get('current_quantity', 0)
                supabase.table("farms")\
                    .update({"current_quantity": current + quantity})\
                    .eq("id", farm_id)\
                    .execute()
        
        # 刪除出貨紀錄
        supabase.table("farm_shipments").delete().eq("id", shipment_id).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "農場碳管理系統 v2 - 支援分批出貨"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
