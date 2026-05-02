# MiniMax Token Plan 配置

本项目把密钥放在本地 `.env` 中，不建议在网页表单或前端代码里填写 API key。

## 国内站 API 入口

当前使用的是 MiniMax 国内站 Token Plan key，正确入口是：

```powershell
https://api.minimaxi.com/v1
```

如果使用 `https://api.minimax.io/v1`，国内站 key 会返回 `invalid api key (2049)`。

## 文本模型

```powershell
MINIMAX_API_KEY=你的_minimax_api_key
LLM_BASE_URL=https://api.minimaxi.com/v1
LLM_API_KEY=你的_minimax_api_key
LLM_MODEL=MiniMax-M2.7
```

## 语音合成

```powershell
TTS_PROVIDER=minimax-official
TTS_API_KEY=你的_minimax_api_key
TTS_BASE_URL=https://api.minimaxi.com/v1
TTS_MODEL=speech-2.8-hd
TTS_VOICE=male-qn-qingse
MINIMAX_GROUP_ID=
```

常用可选音色：

- `male-qn-qingse`
- `female-shaonv`
- `male-qn-jingying`
- `female-yujie`
- `audiobook_male_1`
- `audiobook_female_1`
- `male-qn-qingse-jingpin`
- `female-shaonv-jingpin`

## 多模态额度模型名

这些变量预留给后续图像、视频、音乐生成功能：

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

## 字幕/转写说明

MiniMax key 负责文案和 TTS。若要做语音转字幕，需要额外配置 OpenAI 或其他 ASR 服务：

```powershell
OPENAI_API_KEY=你的_openai_key
```

没有 ASR key 时，项目仍可读取字幕文件和内嵌字幕；如果视频只有硬字幕，则当前不会自动 OCR。
