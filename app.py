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

# ========== 取得所有資料 ==========
@app.route('/api/farms', methods=['GET'])
def get_farms():
    try:
        # 取得所有批次
        farms_res = supabase.table("farms").select("*").order("created_at", desc=True).execute()
        farms = farms_res.data
        
        result = []
        total_plants = 0
        
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
            
            # 計算已出貨總量
            total_shipped = sum(s.get('quantity', 0) for s in shipments_res.data)
            
            # 當前庫存 = 初始數量 - 已出貨總量
            current_quantity = farm.get('initial_quantity', 0) - total_shipped
            
            # 更新資料庫中的當前庫存（保持同步）
            supabase.table("farms")\
                .update({"quantity": current_quantity})\
                .eq("id", farm['id'])\
                .execute()
            
            farm_data = {
                **farm,
                "quantity": current_quantity,  # 確保使用最新計算值
                "growth_records": growth_res.data,
                "shipments": shipments_res.data,
                "total_shipped": total_shipped
            }
            result.append(farm_data)
            
            if current_quantity > 0:
                total_plants += current_quantity
        
        # 計算總碳吸收
        total_carbon = total_plants * CARBON_FACTOR * 30
        
        return jsonify({
            "farms": result,
            "summary": {
                "total_plants": total_plants,
                "total_carbon_kg": round(total_carbon, 2),
                "active_batches": len([f for f in result if f.get('quantity', 0) > 0])
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 新增植物批次 ==========
@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    try:
        batch_number = request.form.get('batch_number')
        if not batch_number:
            return jsonify({"error": "批號為必填"}), 400
        
        quantity = int(request.form.get('quantity', 0))
        
        # 處理照片
        photo_url = ""
        photo = request.files.get('photo')
        if photo and photo.filename:
            photo_url = upload_photo(photo)
        
        # 插入主表
        farm_data = {
            "batch_number": batch_number,
            "plant_name": request.form.get('plant_name', ''),
            "initial_quantity": quantity,
            "quantity": quantity,  # 當前庫存等於初始數量
            "in_date": request.form.get('in_date') or None,
            "supplier": request.form.get('supplier', ''),
            "notes": request.form.get('notes', ''),
            "photo_url": photo_url
        }
        
        result = supabase.table("farms").insert(farm_data).execute()
        
        return jsonify({"status": "ok", "farm_id": result.data[0]['id']})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 新增生長紀錄 ==========
@app.route('/api/add_growth_record', methods=['POST'])
def add_growth_record():
    try:
        farm_id = request.form.get('farm_id')
        record_date = request.form.get('record_date') or datetime.now().strftime('%Y-%m-%d')
        notes = request.form.get('notes', '')
        
        # 處理照片
        photo_url = ""
        photo = request.files.get('photo')
        if photo and photo.filename:
            photo_url = upload_photo(photo, f"growth/{farm_id}")
        
        growth_data = {
            "farm_id": farm_id,
            "record_date": record_date,
            "notes": notes,
            "photo_url": photo_url
        }
        
        result = supabase.table("farm_growth_records").insert(growth_data).execute()
        
        return jsonify({"status": "ok", "data": result.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 新增出貨紀錄 ==========
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
        
        # 取得目前庫存
        farm_res = supabase.table("farms").select("initial_quantity, quantity").eq("id", farm_id).execute()
        if not farm_res.data:
            return jsonify({"error": "找不到該批次"}), 404
        
        farm = farm_res.data[0]
        current = farm.get('quantity', 0)
        initial = farm.get('initial_quantity', 0)
        
        # 計算已出貨總量
        shipments_res = supabase.table("farm_shipments")\
            .select("quantity")\
            .eq("farm_id", farm_id)\
            .execute()
        total_shipped = sum(s.get('quantity', 0) for s in shipments_res.data)
        
        # 檢查庫存是否足夠（考慮到還沒加入這次的出貨）
        if quantity > (initial - total_shipped):
            available = initial - total_shipped
            return jsonify({"error": f"庫存不足，目前可出貨數量為 {available} 株"}), 400
        
        # 新增出貨紀錄
        shipment_data = {
            "farm_id": farm_id,
            "shipment_date": shipment_date,
            "quantity": quantity,
            "customer": customer,
            "notes": notes
        }
        
        result = supabase.table("farm_shipments").insert(shipment_data).execute()
        
        # 更新庫存（新的庫存 = 初始數量 - 所有出貨總和）
        new_total_shipped = total_shipped + quantity
        new_quantity = initial - new_total_shipped
        
        supabase.table("farms")\
            .update({"quantity": new_quantity})\
            .eq("id", farm_id)\
            .execute()
        
        return jsonify({"status": "ok", "data": result.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 刪除生長紀錄 ==========
@app.route('/api/delete_growth_record/<record_id>', methods=['DELETE'])
def delete_growth_record(record_id):
    try:
        supabase.table("farm_growth_records").delete().eq("id", record_id).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 刪除出貨紀錄 ==========
@app.route('/api/delete_shipment/<shipment_id>', methods=['DELETE'])
def delete_shipment(shipment_id):
    try:
        # 先取得出貨紀錄，以便重新計算庫存
        shipment = supabase.table("farm_shipments").select("*").eq("id", shipment_id).execute()
        if not shipment.data:
            return jsonify({"error": "找不到出貨紀錄"}), 404
        
        s = shipment.data[0]
        farm_id = s['farm_id']
        deleted_quantity = s['quantity']
        
        # 刪除出貨紀錄
        supabase.table("farm_shipments").delete().eq("id", shipment_id).execute()
        
        # 重新計算該批次的所有出貨總量
        shipments_res = supabase.table("farm_shipments")\
            .select("quantity")\
            .eq("farm_id", farm_id)\
            .execute()
        total_shipped = sum(s.get('quantity', 0) for s in shipments_res.data)
        
        # 取得初始數量
        farm_res = supabase.table("farms").select("initial_quantity").eq("id", farm_id).execute()
        if farm_res.data:
            initial = farm_res.data[0].get('initial_quantity', 0)
            new_quantity = initial - total_shipped
            
            # 更新庫存
            supabase.table("farms")\
                .update({"quantity": new_quantity})\
                .eq("id", farm_id)\
                .execute()
        
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 刪除整個批次 ==========
@app.route('/api/delete_farm/<farm_id>', methods=['DELETE'])
def delete_farm(farm_id):
    try:
        supabase.table("farms").delete().eq("id", farm_id).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "農場碳管理系統 v3 - 修正出貨邏輯"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
