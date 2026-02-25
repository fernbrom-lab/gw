import os
import uuid
from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client
from flask_cors import CORS
from datetime import datetime, date

app = Flask(__name__, static_folder='.')
CORS(app)

# 初始化 Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

# 植物基礎係數（每株每月吸收 kg CO2）
PLANT_BASE_FACTORS = {
    '鹿角蕨': 0.06,
    '積水鳳梨': 0.04,
    '其他': 0.05
}

# 大小倍率
SIZE_MULTIPLIERS = {
    'small': 0.5,
    'medium': 1.0,
    'large': 1.5
}

# 不確定性範圍
UNCERTAINTY_RANGE = 0.2

# 提供靜態檔案（包含 logo.png）
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/')
def index(): 
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin(): 
    return send_from_directory('.', 'admin.html')

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

# 計算碳吸收量
def calculate_carbon_absorption(plant_type, plant_size, quantity, in_date, current_date=None):
    if not quantity or quantity <= 0 or not in_date:
        return None
    
    base_factor = PLANT_BASE_FACTORS.get(plant_type, 0.05)
    size_multiplier = SIZE_MULTIPLIERS.get(plant_size, 1.0)
    final_factor = base_factor * size_multiplier
    
    if isinstance(in_date, str):
        try:
            in_date = datetime.strptime(in_date, '%Y-%m-%d').date()
        except:
            return None
    
    if current_date is None:
        current_date = date.today()
    
    days = (current_date - in_date).days
    if days <= 0:
        return None
    
    months = days / 30
    absorption = quantity * final_factor * months
    
    return {
        "value": round(absorption, 2),
        "low": round(absorption * (1 - UNCERTAINTY_RANGE), 2),
        "high": round(absorption * (1 + UNCERTAINTY_RANGE), 2),
        "days": days,
        "months": round(months, 1),
        "final_factor": round(final_factor, 3)
    }

# ========== 取得所有資料 ==========
@app.route('/api/farms', methods=['GET'])
def get_farms():
    try:
        # 取得所有批次
        farms_res = supabase.table("farms").select("*").order("created_at", desc=True).execute()
        farms = farms_res.data
        
        result = []
        total_plants = 0
        total_carbon = 0
        today = date.today()
        
        for farm in farms:
            # 取得生長紀錄
            growth_res = supabase.table("farm_growth_records")\
                .select("*")\
                .eq("farm_id", farm['id'])\
                .order("record_date", desc=True)\
                .execute()
            
            # 取得出貨紀錄
            shipments_res = supabase.table("farm_shipments")\
                .select("*")\
                .eq("farm_id", farm['id'])\
                .order("shipment_date", desc=True)\
                .execute()
            
            # 計算已出貨總量
            total_shipped = sum(s.get('quantity', 0) for s in shipments_res.data)
            
            # 當前庫存 = 初始數量 - 已出貨總量
            current_quantity = farm.get('initial_quantity', 0) - total_shipped
            if current_quantity < 0:
                current_quantity = 0
            
            # 更新資料庫中的當前庫存
            supabase.table("farms")\
                .update({"quantity": current_quantity})\
                .eq("id", farm['id'])\
                .execute()
            
            # 計算此批次的碳吸收量
            absorption_data = None
            if current_quantity > 0 and farm.get('in_date'):
                plant_type = farm.get('plant_type', '其他')
                plant_size = farm.get('plant_size', 'medium')
                
                absorption_data = calculate_carbon_absorption(
                    plant_type=plant_type,
                    plant_size=plant_size,
                    quantity=current_quantity,
                    in_date=farm.get('in_date'),
                    current_date=today
                )
                
                if absorption_data:
                    total_carbon += absorption_data['value']
            
            # 加到總庫存（只加有庫存的）
            if current_quantity > 0:
                total_plants += current_quantity
            
            farm_data = {
                **farm,
                "quantity": current_quantity,
                "growth_records": growth_res.data,
                "shipments": shipments_res.data,
                "total_shipped": total_shipped,
                "carbon_absorption": absorption_data
            }
            result.append(farm_data)
        
        # 計算進行中批次（庫存大於0的數量）
        active_batches = len([f for f in result if f.get('quantity', 0) > 0])
        
        print(f"總庫存計算: {total_plants}")  # 除錯用
        print(f"進行中批次: {active_batches}")
        
        return jsonify({
            "farms": result,
            "summary": {
                "total_plants": total_plants,
                "total_carbon_kg": round(total_carbon, 2),
                "active_batches": active_batches
            }
        })
    except Exception as e:
        print(f"錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ========== 新增植物批次 ==========
@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    try:
        batch_number = request.form.get('batch_number')
        if not batch_number:
            return jsonify({"error": "批號為必填"}), 400
        
        quantity = int(request.form.get('quantity', 0))
        
        photo_url = ""
        photo = request.files.get('photo')
        if photo and photo.filename:
            photo_url = upload_photo(photo)
        
        plant_type = request.form.get('plant_type', '其他')
        plant_size = request.form.get('plant_size', 'medium')
        
        farm_data = {
            "batch_number": batch_number,
            "plant_name": request.form.get('plant_name', ''),
            "plant_type": plant_type,
            "plant_size": plant_size,
            "initial_quantity": quantity,
            "quantity": quantity,
            "in_date": request.form.get('in_date') or None,
            "supplier": request.form.get('supplier', ''),
            "notes": request.form.get('notes', ''),
            "photo_url": photo_url
        }
        
        result = supabase.table("farms").insert(farm_data).execute()
        
        return jsonify({"status": "ok", "farm_id": result.data[0]['id']})
        
    except Exception as e:
        print(f"錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ========== 新增生長紀錄 ==========
@app.route('/api/add_growth_record', methods=['POST'])
def add_growth_record():
    try:
        farm_id = request.form.get('farm_id')
        record_date = request.form.get('record_date') or datetime.now().strftime('%Y-%m-%d')
        notes = request.form.get('notes', '')
        
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
        print(f"錯誤: {str(e)}")
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
        
        farm_res = supabase.table("farms").select("initial_quantity").eq("id", farm_id).execute()
        if not farm_res.data:
            return jsonify({"error": "找不到該批次"}), 404
        
        initial = farm_res.data[0].get('initial_quantity', 0)
        
        shipments_res = supabase.table("farm_shipments")\
            .select("quantity")\
            .eq("farm_id", farm_id)\
            .execute()
        total_shipped = sum(s.get('quantity', 0) for s in shipments_res.data)
        
        available = initial - total_shipped
        if quantity > available:
            return jsonify({"error": f"庫存不足，目前可出貨數量為 {available} 株"}), 400
        
        shipment_data = {
            "farm_id": farm_id,
            "shipment_date": shipment_date,
            "quantity": quantity,
            "customer": customer,
            "notes": notes
        }
        
        result = supabase.table("farm_shipments").insert(shipment_data).execute()
        
        new_quantity = available - quantity
        supabase.table("farms")\
            .update({"quantity": new_quantity})\
            .eq("id", farm_id)\
            .execute()
        
        return jsonify({"status": "ok", "data": result.data})
    except Exception as e:
        print(f"錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ========== 刪除功能 ==========
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
        shipment = supabase.table("farm_shipments").select("*").eq("id", shipment_id).execute()
        if not shipment.data:
            return jsonify({"error": "找不到出貨紀錄"}), 404
        
        s = shipment.data[0]
        farm_id = s['farm_id']
        
        supabase.table("farm_shipments").delete().eq("id", shipment_id).execute()
        
        shipments_res = supabase.table("farm_shipments")\
            .select("quantity")\
            .eq("farm_id", farm_id)\
            .execute()
        total_shipped = sum(s.get('quantity', 0) for s in shipments_res.data)
        
        farm_res = supabase.table("farms").select("initial_quantity").eq("id", farm_id).execute()
        if farm_res.data:
            initial = farm_res.data[0].get('initial_quantity', 0)
            new_quantity = initial - total_shipped
            supabase.table("farms")\
                .update({"quantity": new_quantity})\
                .eq("id", farm_id)\
                .execute()
        
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/delete_farm/<farm_id>', methods=['DELETE'])
def delete_farm(farm_id):
    try:
        supabase.table("farms").delete().eq("id", farm_id).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 測試連線 ==========
@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "系統正常運作"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
