# MiniMax Token Plan 配置

本项目把密钥放在本地 `.env` 中，不建议在网页表单或前端代码里填写 API key。

## 官方直连配置

你的 MiniMax Token Plan key 可以通过官方 OpenAI-compatible 接口调用文本模型：

```powershell
MINIMAX_API_KEY=你的_minimax_api_key
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_API_KEY=你的_minimax_api_key
LLM_MODEL=MiniMax-M2.7
```

语音生成使用 MiniMax 官方 TTS：

```powershell
TTS_PROVIDER=minimax-official
TTS_API_KEY=你的_minimax_api_key
TTS_BASE_URL=https://api.minimaxi.com/v1
TTS_MODEL=speech-2.8-hd
TTS_VOICE=male-qn-qingse
MINIMAX_GROUP_ID=
```

当前官方接口不需要 `MINIMAX_GROUP_ID`。如果你后续使用旧版 `api.minimax.chat` 或控制台给了 GroupId，也可以填入该变量。

## 套餐额度对应模型

截图里的图像、视频、音乐额度已在 `.env` 中记录为模型名，方便后续扩展功能时直接读取：

```powershell
IMAGE_BASE_URL=https://api.minimaxi.com/v1
IMAGE_MODEL=image-01
VIDEO_BASE_URL=https://api.minimaxi.com/v1
VIDEO_MODEL=video-01
MUSIC_BASE_URL=https://api.minimaxi.com/v1
MUSIC_MODEL=music-2.6
MUSIC_COVER_MODEL=music-cover
LYRICS_MODEL=lyrics_generation
```

本仓库当前网页主要使用文本生成和配音来制作视频解说；图像、视频生成、音乐生成变量已经预留，但还没有对应的页面功能。

## 重启与测试

修改 `.env` 后重启服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\stop_web.ps1
powershell -ExecutionPolicy Bypass -File .\start_web.ps1
```

打开页面后，在“文案”页点击“测试模型连接”，在“配音”页点击“测试配音连接”。
