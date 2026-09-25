# chunba Network AI Photo Classifier v2.0 R2

GUI 內部署名：**峻爸製作**

## 本版定位

這是「只使用網路 AI 判讀」的版本，不再內嵌 YuNet / ArcFace / YOLO 等本機 AI 模型，因此 EXE 會比前一版小，GitHub Actions 也會更快。

- 網路 AI：Gemini 3.5 Flash-Lite（預設）
- 備援模型：Gemini 3.1 Flash-Lite
- 日期分類：只讀 EXIF / 檔案日期；這是中繼資料處理，不是本機 AI 判讀。
- 原始照片：不刪除、不移動；只有按「輸出所選分類檔案」才複製。

## 功能

1. 所有檔名、EXE、Artifact、輸出照片使用英文 `chunba`；只有 App 內顯示「峻爸製作」。
2. 快速掃描後直接顯示縮圖牆。
3. 每張卡片直接顯示：人數、場景、AI內容標籤、AI判斷依據，不需先點進去。
4. 點縮圖可開大圖預覽。
5. 可自由勾選：
   - 純人物辨識
   - 人數分類
   - 日期分類
   - 場景分類
   - 指定人物人工確認候選
6. 有「暫停／繼續」以及「完全取消並重來」。
7. 「精確進階所選」只對已勾選照片用更高解析度重新送 Gemini 分析。
8. 每次自動使用不重複編號：`chunba_YYYYMMDD_001`、`002`、`003`…
9. 每次會儲存 preview / advanced / export manifest CSV。
10. 輸出照片英文重新命名：`chunba_YYYYMMDD_001_00001.jpg`。

## 指定人物功能的重要差異

此「網路 AI 版」**不讓 AI 自動判定某張照片中的真人是不是參考照片中的特定人物**。

做法改為：
- 可加入 1~多張參考照片供你人工對照。
- Gemini 只標記「是否有足夠清楚的人物／臉部可供人工比對」。
- 你可以在大圖預覽按「人工標記指定人物」。
- 最後輸出會依你的人工標記分類為 `target_manual_yes`。

這樣仍保留指定人物整理工作流，但最終身分判定由使用者確認。

## 為什麼免費網路 AI 只內建 Gemini？

本版目標是「免費層可用」。Gemini API 有免費使用層，並支援圖片輸入。
OpenAI/ChatGPT API 與 Perplexity API 的消費者免費方案不等於可免費大量呼叫 API，因此這個免費版不把它們當預設後端，以免意外產生費用。

## GitHub 編譯

### 最穩定的網頁上傳方式

如果 `.github` 資料夾沒有跟著上傳：

1. 先把根目錄檔案上傳 GitHub，包括 `build-windows.yml`。
2. 提交後點進 `build-windows.yml`。
3. 編輯檔名為：
   `.github/workflows/build-windows.yml`
4. 提交。
5. 到 Actions → `Build chunba Network AI Photo Classifier v2.0 R2` → Run workflow。
6. 成功後在 Artifacts 下載：
   `chunba-network-photo-classifier-v2-0-r2-windows`

### EXE

`chunba_network_photo_classifier_v2_0_r2.exe`

## API Key

請從 Google AI Studio 建立 Gemini API Key，開啟程式後貼入「API Key」，先按「測試 API」。

## 免費額度與隱私

- 免費層有 RPM / TPM / RPD 限制，實際額度請以 Google AI Studio 顯示為準。
- 超過免費速率時程式會自動短暫等待後重試。
- 使用網路 AI 時，縮小後的照片會傳送到 Google Gemini API。
- 若照片涉及隱私、未成年人、公司機密或敏感內容，請先確認是否適合上傳到雲端服務。
