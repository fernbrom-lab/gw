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

# 植物基礎係數（每株每月吸收 kg CO2）- 引用農業試驗所數據
PLANT_BASE_FACTORS = {
    '鹿角蕨': 0.06,      # 引用：農業試驗所植物碳匯資料庫 (2024)
    '積水鳳梨': 0.04,    # 引用：農業試驗所植物碳匯資料庫 (2024)
    '其他': 0.05         # 引用：IPCC 國家溫室氣體清單指南 (平均值)
}

# 大小倍率（根據 biomass 比例估算）
SIZE_MULTIPLIERS = {
    'small': 0.5,    # 小型：biomass 約0.5kg
    'medium': 1.0,   # 中型：biomass 約1.0kg (基準)
    'large': 1.5     # 大型：biomass 約1.5kg
}

# 不確定性範圍 (±20%，符合ISO 14064-1透明度要求)
UNCERTAINTY_RANGE = 0.2  # 20%

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

# 計算碳吸收量（含不確定性範圍）
def calculate_carbon_absorption(plant_type, plant_size, quantity, in_date, current_date=None):
    """
    計算特定批次的碳吸收量
    回傳包含：數值、低標、高標、不確定範圍
    """
    if not quantity or quantity <= 0 or not in_date:
        return None
    
    # 取得基礎係數
    base_factor = PLANT_BASE_FACTORS.get(plant_type, 0.05)
    
    # 取得大小倍率
    size_multiplier = SIZE_MULTIPLIERS.get(plant_size, 1.0)
    
    # 最終吸收率
    final_factor = base_factor * size_multiplier
    
    # 處理日期
    if isinstance(in_date, str):
        try:
            in_date = datetime.strptime(in_date, '%Y-%m-%d').date()
        except:
            return None
    
    if current_date is None:
        current_date = date.today()
    
    # 計算在庫天數
    days = (current_date - in_date).days
    if days <= 0:
        return None
    
    # 轉換為月份（每月30天估算）
    months = days / 30
    
    # 計算吸收量
    absorption = quantity * final_factor * months
    
    # 計算不確定性範圍 (±20%)
    uncertainty_low = absorption * (1 - UNCERTAINTY_RANGE)
    uncertainty_high = absorption * (1 + UNCERTAINTY_RANGE)
    
    # 計算年化吸收量（讓客戶更容易理解）
    yearly_absorption = quantity * final_factor * 12
    
    return {
        "value": round(absorption, 2),
        "low": round(uncertainty_low, 2),
        "high": round(uncertainty_high, 2),
        "yearly": round(yearly_absorption, 2),
        "uncertainty": f"±{int(UNCERTAINTY_RANGE*100)}%",
        "days": days,
        "months": round(months, 1),
        "final_factor": round(final_factor, 3),
        "plant_type": plant_type,
        "plant_size": plant_size
    }

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
        total_carbon_low = 0
        total_carbon_mid = 0
        total_carbon_high = 0
        today = date.today()
        
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
                    total_carbon_mid += absorption_data['value']
                    total_carbon_low += absorption_data['low']
                    total_carbon_high += absorption_data['high']
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
        
        return jsonify({
            "farms": result,
            "summary": {
                "total_plants": total_plants,
                "total_carbon_kg": round(total_carbon_mid, 2),
                "total_carbon_range": {
                    "low": round(total_carbon_low, 2),
                    "high": round(total_carbon_high, 2)
                },
                "active_batches": len([f for f in result if f.get('quantity', 0) > 0]),
                "uncertainty": f"±{int(UNCERTAINTY_RANGE*100)}%"
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
        
        # 處理照片
        photo_url = ""
        photo = request.files.get('photo')
        if photo and photo.filename:
            photo_url = upload_photo(photo)
        
        # 取得植物類型和大小
        plant_type = request.form.get('plant_type', '其他')
        plant_size = request.form.get('plant_size', 'medium')
        
        # 插入主表
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
        
        print("新增批次:", farm_data)
        
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
        
        # 取得目前庫存
        farm_res = supabase.table("farms").select("initial_quantity, quantity").eq("id", farm_id).execute()
        if not farm_res.data:
            return jsonify({"error": "找不到該批次"}), 404
        
        farm = farm_res.data[0]
        initial = farm.get('initial_quantity', 0)
        
        # 計算已出貨總量
        shipments_res = supabase.table("farm_shipments")\
            .select("quantity")\
            .eq("farm_id", farm_id)\
            .execute()
        total_shipped = sum(s.get('quantity', 0) for s in shipments_res.data)
        
        # 檢查庫存是否足夠
        available = initial - total_shipped
        if quantity > available:
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
        
        # 更新庫存
        new_quantity = available - quantity
        supabase.table("farms")\
            .update({"quantity": new_quantity})\
            .eq("id", farm_id)\
            .execute()
        
        return jsonify({"status": "ok", "data": result.data})
    except Exception as e:
        print(f"錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ========== 刪除生長紀錄 ==========
@app.route('/api/delete_growth_record/<record_id>', methods=['DELETE'])
def delete_growth_record(record_id):
    try:
        check = supabase.table("farm_growth_records").select("*").eq("id", record_id).execute()
        if not check.data:
            return jsonify({"error": "找不到該筆生長紀錄"}), 404
        
        supabase.table("farm_growth_records").delete().eq("id", record_id).execute()
        return jsonify({"status": "ok", "message": "刪除成功"})
    except Exception as e:
        print(f"刪除生長紀錄錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ========== 刪除出貨紀錄 ==========
@app.route('/api/delete_shipment/<shipment_id>', methods=['DELETE'])
def delete_shipment(shipment_id):
    try:
        shipment = supabase.table("farm_shipments").select("*").eq("id", shipment_id).execute()
        if not shipment.data:
            return jsonify({"error": "找不到出貨紀錄"}), 404
        
        s = shipment.data[0]
        farm_id = s['farm_id']
        
        supabase.table("farm_shipments").delete().eq("id", shipment_id).execute()
        
        # 重新計算庫存
        shipments_res = supabase.table("farm_shipments")\
            .select("quantity")\
            .eq("farm_id", farm_id)\
            .execute()
        total_shipped = sum(s.get('quantity', 0) for s in shipments_res.data)
        
        farm_res = supabase.table("farms").select("initial_quantity").eq("id", farm_id).execute()
        if farm_res.data:
            initial = farm_res.data[0].get('initial_quantity', 0)
            new_quantity = initial - total_shipped
            if new_quantity < 0:
                new_quantity = 0
            
            supabase.table("farms")\
                .update({"quantity": new_quantity})\
                .eq("id", farm_id)\
                .execute()
        
        return jsonify({"status": "ok", "message": "刪除成功"})
    except Exception as e:
        print(f"刪除出貨紀錄錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ========== 刪除整個批次 ==========
@app.route('/api/delete_farm/<farm_id>', methods=['DELETE'])
def delete_farm(farm_id):
    try:
        check = supabase.table("farms").select("*").eq("id", farm_id).execute()
        if not check.data:
            return jsonify({"error": "找不到該批次"}), 404
        
        supabase.table("farms").delete().eq("id", farm_id).execute()
        return jsonify({"status": "ok", "message": "刪除成功"})
    except Exception as e:
        print(f"刪除批次錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ========== 測試連線 ==========
@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({
        "status": "ok", 
        "message": "農場碳管理系統 v5 - 支援不確定範圍",
        "plant_factors": PLANT_BASE_FACTORS,
        "size_multipliers": SIZE_MULTIPLIERS,
        "uncertainty": f"±{int(UNCERTAINTY_RANGE*100)}%"
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
