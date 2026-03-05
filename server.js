const express = require('express');
const cors = require('cors');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json({ limit: '10mb' }));

// 植物辨識 API
app.post('/api/identify', async (req, res) => {
  const { imageBase64, mimeType } = req.body;

  if (!imageBase64 || !mimeType) {
    return res.status(400).json({ error: '缺少圖片資料' });
  }

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: '伺服器未設定 API Key' });
  }

  const prompt = `請辨識這張照片中的植物，並以以下 JSON 格式回答（只回傳 JSON，不要有其他說明）：

{
  "name": "中文名稱（若無法辨識請填「無法辨識」）",
  "english_name": "英文名稱",
  "scientific_name": "學名",
  "features": "外觀特徵描述（2-4句）",
  "habitat": "生長環境與分布地區（2-3句）",
  "care": "照顧方式，包含澆水、日照、施肥等建議（3-5句）",
  "other": "其他重要資訊，例如是否有毒、可食用性、藥用價值、相似植物等（2-3句）"
}`;

  try {
    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{
            parts: [
              { inline_data: { mime_type: mimeType, data: imageBase64 } },
              { text: prompt }
            ]
          }],
          generationConfig: { maxOutputTokens: 1000 }
        })
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error?.message || `Gemini API 錯誤 (${response.status})`);
    }

    const text = data.candidates?.[0]?.content?.parts?.map(p => p.text || '').join('') || '';
    const clean = text.replace(/```json|```/g, '').trim();
    const result = JSON.parse(clean);

    res.json(result);
  } catch (err) {
    res.status(500).json({ error: '辨識失敗：' + err.message });
  }
});

// 靜態檔案放在路由後面
app.use(express.static(path.join(__dirname, '.')));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`伺服器啟動於 port ${PORT}`);
});
