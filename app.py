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

# 植物基礎係數
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

# 每頁顯示筆數
ITEMS_PER_PAGE = 10

# 提供靜態檔案
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/')
def index(): 
    return send_from_directory('.', 'index.html')

@app.route('/admin')
def admin(): 
    return send_from_directory('.', 'admin.html')

# 上傳照片
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

# ========== 取得統計摘要（輕量級 API）==========
@app.route('/api/summary', methods=['GET'])
def get_summary():
    try:
        # 只取得必要欄位，加快查詢速度
        farms_res = supabase.table("farms").select("id, initial_quantity, quantity, in_date, plant_type, plant_size").execute()
        farms = farms_res.data
        
        total_plants = 0
        total_carbon = 0
        active_batches = 0
        today = date.today()
        
        for farm in farms:
            current_quantity = farm.get('quantity', 0)
            if current_quantity > 0:
                total_plants += current_quantity
                active_batches += 1
                
                if farm.get('in_date'):
                    absorption = calculate_carbon_absorption(
                        plant_type=farm.get('plant_type', '其他'),
                        plant_size=farm.get('plant_size', 'medium'),
                        quantity=current_quantity,
                        in_date=farm.get('in_date'),
                        current_date=today
                    )
                    if absorption:
                        total_carbon += absorption['value']
        
        return jsonify({
            "total_plants": total_plants,
            "total_carbon_kg": round(total_carbon, 2),
            "active_batches": active_batches
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 取得分頁資料 ==========
@app.route('/api/farms', methods=['GET'])
def get_farms():
    try:
        # 取得分頁參數
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', ITEMS_PER_PAGE, type=int)
        offset = (page - 1) * limit
        
        # 先取得總筆數
        count_res = supabase.table("farms").select("id", count="exact").execute()
        total_count = count_res.count if hasattr(count_res, 'count') else 0
        
        # 取得分頁資料
        farms_res = supabase.table("farms")\
            .select("*")\
            .order("created_at", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
        
        farms = farms_res.data
        result = []
        today = date.today()
        
        for farm in farms:
            # 只取得最近3筆生長紀錄
            growth_res = supabase.table("farm_growth_records")\
                .select("*")\
                .eq("farm_id", farm['id'])\
                .order("record_date", desc=True)\
                .limit(3)\
                .execute()
            
            # 只取得最近3筆出貨紀錄
            shipments_res = supabase.table("farm_shipments")\
                .select("*")\
                .eq("farm_id", farm['id'])\
                .order("shipment_date", desc=True)\
                .limit(3)\
                .execute()
            
            # 計算已出貨總量
            shipments_all = supabase.table("farm_shipments")\
                .select("quantity")\
                .eq("farm_id", farm['id'])\
                .execute()
            total_shipped = sum(s.get('quantity', 0) for s in shipments_all.data)
            
            # 當前庫存
            current_quantity = farm.get('initial_quantity', 0) - total_shipped
            if current_quantity < 0:
                current_quantity = 0
            
            # 更新資料庫中的當前庫存
            supabase.table("farms")\
                .update({"quantity": current_quantity})\
                .eq("id", farm['id'])\
                .execute()
            
            # 計算碳吸收量
            absorption_data = None
            if current_quantity > 0 and farm.get('in_date'):
                absorption_data = calculate_carbon_absorption(
                    plant_type=farm.get('plant_type', '其他'),
                    plant_size=farm.get('plant_size', 'medium'),
                    quantity=current_quantity,
                    in_date=farm.get('in_date'),
                    current_date=today
                )
            
            farm_data = {
                **farm,
                "quantity": current_quantity,
                "growth_records": growth_res.data,
                "shipments": shipments_res.data,
                "total_shipped": total_shipped,
                "carbon_absorption": absorption_data,
                "growth_count": len(growth_res.data),
                "shipments_count": len(shipments_all.data)
            }
            result.append(farm_data)
        
        return jsonify({
            "farms": result,
            "pagination": {
                "current_page": page,
                "total_pages": (total_count + limit - 1) // limit,
                "total_items": total_count,
                "items_per_page": limit
            }
        })
    except Exception as e:
        print(f"錯誤: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ========== 取得更多生長紀錄 ==========
@app.route('/api/growth_records/<farm_id>', methods=['GET'])
def get_growth_records(farm_id):
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        offset = (page - 1) * limit
        
        count_res = supabase.table("farm_growth_records")\
            .select("id", count="exact")\
            .eq("farm_id", farm_id)\
            .execute()
        total_count = count_res.count if hasattr(count_res, 'count') else 0
        
        records_res = supabase.table("farm_growth_records")\
            .select("*")\
            .eq("farm_id", farm_id)\
            .order("record_date", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
        
        return jsonify({
            "records": records_res.data,
            "pagination": {
                "current_page": page,
                "total_pages": (total_count + limit - 1) // limit,
                "total_items": total_count
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 取得更多出貨紀錄 ==========
@app.route('/api/shipments/<farm_id>', methods=['GET'])
def get_shipments(farm_id):
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        offset = (page - 1) * limit
        
        count_res = supabase.table("farm_shipments")\
            .select("id", count="exact")\
            .eq("farm_id", farm_id)\
            .execute()
        total_count = count_res.count if hasattr(count_res, 'count') else 0
        
        records_res = supabase.table("farm_shipments")\
            .select("*")\
            .eq("farm_id", farm_id)\
            .order("shipment_date", desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
        
        return jsonify({
            "records": records_res.data,
            "pagination": {
                "current_page": page,
                "total_pages": (total_count + limit - 1) // limit,
                "total_items": total_count
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ========== 新增植物批次 ==========
@app.route('/api/add_farm', methods=['POST'])
def add_farm():
    # ... 保持不變 ...
    pass

# ========== 新增生長紀錄 ==========
@app.route('/api/add_growth_record', methods=['POST'])
def add_growth_record():
    # ... 保持不變 ...
    pass

# ========== 新增出貨紀錄 ==========
@app.route('/api/add_shipment', methods=['POST'])
def add_shipment():
    # ... 保持不變 ...
    pass

# ========== 刪除功能 ==========
@app.route('/api/delete_growth_record/<record_id>', methods=['DELETE'])
def delete_growth_record(record_id):
    # ... 保持不變 ...
    pass

@app.route('/api/delete_shipment/<shipment_id>', methods=['DELETE'])
def delete_shipment(shipment_id):
    # ... 保持不變 ...
    pass

@app.route('/api/delete_farm/<farm_id>', methods=['DELETE'])
def delete_farm(farm_id):
    # ... 保持不變 ...
    pass

# ========== 測試連線 ==========
@app.route('/api/test', methods=['GET'])
def test():
    return jsonify({"status": "ok", "message": "系統正常運作"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
